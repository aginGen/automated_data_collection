import argparse
import gzip
import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib import robotparser
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

from .breaker import CircuitBreaker
from .detector import inspect_response
from .limiter import DomainLease, TokenBucket
from .observability import Journal, report
from .retry import classify, retry_delay


ROOT = Path(__file__).resolve().parents[1]
USER_AGENT = 'university-lab7/1.0 (+https://github.com/aginGen/automated_data_collection)'


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def parse_records(body, content_type):
    if 'json' in content_type:
        payload = json.loads(body)
        if 'records' in payload:
            return payload['records']
        return [dict(key='api:' + r['key'], title=r['title'], source='openlibrary',
                     url='https://openlibrary.org' + r['key']) for r in payload.get('docs', [])]
    soup = BeautifulSoup(body, 'html.parser')
    return [dict(key=card.get('data-key') or 'html:' + str(index),
                 title=card.select_one('.text').get_text(' ', strip=True),
                 author=card.select_one('.author').get_text(' ', strip=True),
                 source='quotes_html', url=card.get('data-url') or 'https://quotes.toscrape.com/')
            for index, card in enumerate(soup.select('.quote'))]


class Client:
    def __init__(self, base, profile, journal, cache, rate=2.0, budget=8.0):
        self.base, self.host = base, urlsplit(base).hostname
        self.profile, self.journal, self.cache, self.budget = profile, journal, cache, budget
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': USER_AGENT, 'Accept': 'application/json,text/html'})
        self.limiter, self.breaker = TokenBucket(rate=rate), CircuitBreaker()
        self.blocked, self.robot = False, None

    def close(self):
        self.session.close()

    def request(self, url, resource='records', conditional=False, compressed=False):
        if self.blocked:
            self.journal.write('skip_blocked', host=self.host, url=url)
            return None
        if self.robot is not None and not self.robot.can_fetch(USER_AGENT, url):
            self.journal.write('robots_denied', host=self.host, url=url, error='robots.txt запрещает URL')
            return None
        started = time.monotonic()
        attempts = 1 if self.profile == 'A' else 3
        for attempt in range(attempts):
            before = self.breaker.state
            if self.profile != 'A' and not self.breaker.allow():
                self.journal.write('skip_open', host=self.host, url=url, state=self.breaker.state)
                return None
            if before == 'open':
                self.journal.write('circuit_half_open', host=self.host, url=url)
            if self.profile != 'A':
                self.limiter.acquire()
            remaining = self.budget - (time.monotonic()-started)
            if remaining <= 0:
                self.journal.write('url_budget_exhausted', host=self.host, url=url)
                return None
            headers = {'Accept-Encoding': 'gzip' if compressed else 'identity'}
            previous = self.cache.get(url)
            if conditional and previous:
                if previous.get('etag'):
                    headers['If-None-Match'] = previous['etag']
                elif previous.get('last_modified'):
                    headers['If-Modified-Since'] = previous['last_modified']
            begin = time.perf_counter()
            exception, response, status, wire, body = None, None, None, b'', b''
            try:
                response = self.session.get(url, headers=headers, timeout=min(5.0, remaining), stream=True)
                status = response.status_code
                wire = response.raw.read(decode_content=False)
                body = gzip.decompress(wire) if response.headers.get('Content-Encoding') == 'gzip' else wire
            except requests.RequestException as error:
                exception = error
            latency = time.perf_counter()-begin
            self.limiter.observe(latency, status)
            self.journal.write('request', host=self.host, url=url, status=status,
                               ms=round(latency*1000, 4), attempt=attempt+1, bytes=len(wire),
                               decoded_bytes=len(body), resource=resource, error=str(exception or ''))
            error_class, retry = classify(status, exception)
            if self.profile != 'A' and (retry or status in (200, 304)):
                old = self.breaker.state
                self.breaker.record(status in (200, 304))
                if old != 'open' and self.breaker.state == 'open':
                    self.journal.write('circuit_open', host=self.host, url=url)
                elif old == 'half-open' and self.breaker.state == 'closed':
                    self.journal.write('circuit_closed', host=self.host, url=url)
            if status == 304:
                if response is not None:
                    response.close()
                if previous is None:
                    raise ValueError('HTTP 304 без локальной копии')
                self.journal.write('cache_reuse', host=self.host, url=url)
                return previous
            records = []
            expected = True
            content_type = response.headers.get('Content-Type', '') if response is not None else ''
            if status == 200 and resource == 'records':
                try:
                    records = parse_records(body, content_type)
                    expected = bool(records)
                except (ValueError, KeyError, AttributeError) as error:
                    expected = False
                    self.journal.write('reject', host=self.host, url=url, error=str(error))
            verdict = inspect_response(status, body, expected, min_bytes=30 if resource!='records' else 80)
            if verdict['verdict'] == 'blocked':
                directory = ROOT/'logs'/'incidents'/self.journal.run_id
                directory.mkdir(parents=True, exist_ok=True)
                digest = uuid.uuid4().hex[:8]
                (directory/(digest+'.body.txt')).write_bytes(body)
                saved_headers = dict(response.headers) if response is not None else {}
                save_json(directory/(digest+'.headers.json'), saved_headers)
                self.blocked = True
                self.journal.write('blocked_domain', host=self.host, url=url, error=verdict['reason'])
                if response is not None:
                    response.close()
                return None
            if status == 200:
                result = dict(body=body.decode('utf-8'), records=records,
                              etag=response.headers.get('ETag'),
                              last_modified=response.headers.get('Last-Modified'),
                              content_type=content_type)
                self.cache[url] = result
                response.close()
                return result
            if response is not None:
                retry_after = response.headers.get('Retry-After')
                response.close()
            else:
                retry_after = None
            if not retry or attempt+1 >= attempts:
                self.journal.write('request_failed', host=self.host, url=url, status=status,
                                   error=error_class)
                return None
            delay, origin = retry_delay(attempt, retry_after)
            if time.monotonic()-started+delay >= self.budget:
                self.journal.write('url_budget_exhausted', host=self.host, url=url,
                                   error='Retry-After превышает оставшийся бюджет; запрос не повторяется')
                return None
            self.journal.write('retry', host=self.host, url=url, status=status,
                               attempt=attempt+1, delay_s=delay, delay_source=origin)
            time.sleep(delay)
        return None

    def read_robots(self, conditional=False, compressed=False):
        url = urljoin(self.base, '/robots.txt')
        result = self.request(url, resource='robots', conditional=conditional, compressed=compressed)
        parser = robotparser.RobotFileParser(url)
        if result:
            parser.parse(result['body'].splitlines())
        else:
            requests_rows = [r for r in self.journal.rows if r['event']=='request' and r['url']==url]
            if requests_rows and requests_rows[-1]['status']==404:
                parser.parse([])
            else:
                parser.parse(['User-agent: *', 'Disallow: /'])
        self.robot = parser
        delay = parser.crawl_delay(USER_AGENT)
        rate = parser.request_rate(USER_AGENT)
        if delay is not None:
            self.limiter.crawl_delay = delay
        if rate:
            self.limiter.rate = min(self.limiter.rate, rate.requests/rate.seconds)
        return dict(url=url, can_fetch=parser.can_fetch(USER_AGENT, urljoin(self.base, '/page/1')),
                    crawl_delay=delay, request_rate=str(rate), sitemaps=parser.site_maps(),
                    missing_policy='404: запрета нет; лимит сборщика сохраняется')


def run_profile(profile='B', html_base='http://127.0.0.1:8797', api_base='http://127.0.0.2:8798',
                conditional=None, compressed=None, incremental=None, run_label=None, workers=4):
    if profile == 'A' and any(urlsplit(base).hostname not in ('localhost','127.0.0.1','127.0.0.2')
                              for base in (html_base,api_base)):
        raise ValueError('Прогон A разрешён только на локальной учебной площадке')
    conditional = profile == 'C' if conditional is None else conditional
    compressed = profile == 'C' if compressed is None else compressed
    incremental = profile == 'C' if incremental is None else incremental
    label = run_label or profile
    run_id = label+'_'+uuid.uuid4().hex[:10]
    journal = Journal(ROOT/'logs'/('run_'+run_id+'.jsonl'), run_id)
    cache_path, watermark_path = ROOT/'state'/'etags.json', ROOT/'state'/'watermark.json'
    cache = json.loads(cache_path.read_text(encoding='utf-8')) if cache_path.exists() else {}
    watermarks = json.loads(watermark_path.read_text(encoding='utf-8')) if watermark_path.exists() else {}
    start = time.perf_counter()
    results, robots = {}, {}
    def source(base):
        client = Client(base, profile, journal, cache)
        try:
            with DomainLease(ROOT/'state'/'worker_locks', client.host):
                robots[client.host] = client.read_robots(conditional,compressed)
                manifest_url = urljoin(base, '/manifest')
                response = client.request(manifest_url, 'manifest', conditional,compressed)
                if response is None:
                    return []
                manifest = json.loads(response['body'])
                records = []
                for resource in manifest['resources']:
                    url = urljoin(base,resource['path'])
                    if incremental and watermarks.get(url)==resource['version'] and url in cache:
                        result = cache[url]
                        journal.write('watermark_skip',host=client.host,url=url)
                    else:
                        result = client.request(url,'records',conditional,compressed)
                    if result:
                        records.extend(result['records'])
                        watermarks[url] = resource['version']
                return records
        finally:
            client.close()
    with ThreadPoolExecutor(max_workers=min(4,max(1,workers))) as pool:
        for base, records in zip((html_base,api_base),pool.map(source,(html_base,api_base))):
            results[base] = records
    materialized = {r['key']:r for rows in results.values() for r in rows}
    if profile == 'A' and sum(r['event']=='request' for r in journal.rows)>30:
        raise RuntimeError('Превышен учебный предел A: 30 запросов')
    history_path = ROOT/'reports'/'history.json'
    history = json.loads(history_path.read_text(encoding='utf-8')) if history_path.exists() else []
    summary = report(journal.rows,len(materialized),time.perf_counter()-start,history[-5:])
    summary.update(profile=profile,run_id=run_id,log=journal.path.relative_to(ROOT).as_posix(),
                   source_records={b:len(v) for b,v in results.items()},
                   archived_records=len(materialized), network_records=sum(
                       len(cache.get(r['url'],{}).get('records',[])) for r in journal.rows
                       if r['event']=='request' and r['resource']=='records' and r['status']==200))
    save_json(ROOT/'reports'/('run_report_'+label+'.json'),summary)
    save_json(ROOT/'reports'/'robots_training.json',robots)
    save_json(cache_path,cache)
    save_json(watermark_path,watermarks)
    save_json(ROOT/'reports'/('records_'+label+'.json'),list(materialized.values()))
    if summary['verdict']=='green':
        save_json(history_path,history+[summary])
    return summary


def run_faults(html_base='http://127.0.0.1:8797',api_base='http://127.0.0.2:8798',blocked=False):
    label='blocked' if blocked else 'faults'
    journal=Journal(ROOT/'logs'/('run_'+label+'_'+uuid.uuid4().hex[:8]+'.jsonl'),label)
    cache={}
    html,api=Client(html_base,'B',journal,cache),Client(api_base,'B',journal,cache)
    started=time.perf_counter()
    try:
        if blocked:
            html.request(html_base+'/blocked')
            html.request(html_base+'/page/1')
            recovered=api.request(api_base+'/page/1')
            notes=dict(api_continues=bool(recovered),html_stopped=html.blocked)
        else:
            failed=html.request(html_base+'/fault-500')
            html.request(html_base+'/page/1')
            healthy=api.request(api_base+'/page/1')
            time.sleep(html.breaker.cooldown+0.05)
            recovered=html.request(html_base+'/fault-500')
            for path in ('/missing-one','/missing-two','/rate-seconds','/rate-date','/rate-none'):
                api.request(api_base+path)
            notes=dict(initial_html_failed=failed is None,api_continues=bool(healthy),
                       html_recovered=bool(recovered),final_breaker_state=html.breaker.state)
        unique={r['key'] for value in (recovered,) if value for r in value['records']} if blocked else {r['key'] for value in (healthy,recovered) if value for r in value['records']}
        summary=report(journal.rows,len(unique),time.perf_counter()-started)
        summary.update(notes=notes,log=journal.path.relative_to(ROOT).as_posix())
        save_json(ROOT/'reports'/('scenario_'+label+'.json'),summary)
        return summary
    finally:
        html.close()
        api.close()


def probe_real():
    journal=Journal(ROOT/'logs'/('run_real_'+uuid.uuid4().hex[:8]+'.jsonl'),'real')
    outcomes=[]
    targets=[
        ('https://quotes.toscrape.com','https://quotes.toscrape.com/page/1/'),
        ('https://openlibrary.org','https://openlibrary.org/search.json?q=python&limit=3'),
    ]
    for base,url in targets:
        client=Client(base,'B',journal,{},rate=0.9,budget=30)
        try:
            robots=client.read_robots()
            robots['can_fetch']=client.robot.can_fetch(USER_AGENT,url)
            result=client.request(url)
            outcomes.append(dict(url=url,robots=robots,records=len(result['records']) if result else 0,
                                 blocked=client.blocked))
        finally:
            client.close()
    save_json(ROOT/'reports'/'real_probe.json',outcomes)
    return outcomes


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--profile',choices=['A','B','C'],default='B')
    parser.add_argument('--scenario',choices=['faults','blocked','real'])
    parser.add_argument('--html-base',default='http://127.0.0.1:8797')
    parser.add_argument('--api-base',default='http://127.0.0.2:8798')
    parser.add_argument('--workers',type=int,default=4)
    args=parser.parse_args()
    if args.scenario=='real':
        result=probe_real()
    elif args.scenario:
        result=run_faults(args.html_base,args.api_base,args.scenario=='blocked')
    else:
        result=run_profile(args.profile,args.html_base,args.api_base,workers=args.workers)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if isinstance(result,dict) and result.get('verdict')=='red':
        raise SystemExit(2)
