import os, sys, json, time, gzip, hashlib, urllib.parse, urllib.robotparser, requests, urllib3, multiprocessing, uuid, tempfile, shutil, subprocess
sys.dont_write_bytecode = True
from types import SimpleNamespace
from pathlib import Path
from bs4 import BeautifulSoup
from limiter import Limiter
from retry import classify, retry_delay
from breaker import Breaker
from detector import detect
from observability import Log, summarize

ROOT = Path(__file__).resolve().parent.parent
UA = "PGU-DataMining-Lab7/1.0 (educational; contact: https://github.com/aginGen/automated_data_collection)"
URLS = [f"https://books.toscrape.com/catalogue/page-{i}.html" for i in range(1, 4)] + [
    f"https://openlibrary.org/works/{i}.json"
    for i in ("OL10056472W", "OL1033722W", "OL10538818W")
]


def save(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf8")


def load(path, default):
    return json.loads(path.read_text(encoding="utf8")) if path.exists() else default


def _http_worker(pipe, url, headers, trust_env, timeout):
    try:
        session = requests.Session()
        session.trust_env = trust_env
        response = session.get(
            url,
            headers=headers,
            timeout=(min(8, timeout), timeout),
            stream=True,
            allow_redirects=False,
        )
        response.raw.decode_content = False
        body = response.raw.read()
        pipe.send((response.status_code, dict(response.headers), body, None))
    except Exception as e:
        pipe.send((None, {}, b"", str(e)))
    finally:
        pipe.close()


def bounded_get(url, headers, trust_env, deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("URL budget exhausted")
    recv, send = multiprocessing.Pipe(duplex=False)
    process = multiprocessing.Process(
        target=_http_worker, args=(send, url, headers, trust_env, remaining)
    )
    process.start()
    send.close()
    try:
        if not recv.poll(max(0, deadline - time.monotonic())):
            raise TimeoutError("URL budget exceeded during HTTP")
        status, hdr, raw, error = recv.recv()
        if error:
            raise OSError(error)
        return (
            SimpleNamespace(
                status_code=status, headers=requests.structures.CaseInsensitiveDict(hdr)
            ),
            raw,
        )
    finally:
        if process.is_alive():
            process.terminate()
        process.join()
        recv.close()


class DomainLock:
    def __init__(self, host):
        self.f = open(
            Path(tempfile.gettempdir())
            / ("lab7_domain_lock_" + hashlib.sha256(host.encode()).hexdigest()[:12] + ".bin"),
            "a+b",
        )
        self.f.seek(0)
        self.f.write(b"0")
        self.f.flush()
        self.f.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(self.f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(self.f, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def close(self):
        self.f.close()


class Collector:
    def __init__(self, mode, run, robots=True):
        run = run if robots else run + "_" + uuid.uuid4().hex[:12]
        self.mode = mode
        self.run = run
        self.log = Log(ROOT / "logs" / f"run_{run}.jsonl", run)
        self.cache = load(ROOT / "state" / "etags.json", {})
        self.limits = {}
        self.breakers = {}
        self.blocked = set()
        self.locks = {}
        self.robots = robots
        self.rules = {}
        self.parsers = {}
        self.session = requests.Session()
        self.session.trust_env = robots
        self.session.headers.update(
            {"User-Agent": UA, "Accept-Encoding": "gzip" if mode == "C" else "identity"}
        )
        self.items = []
        self.rejected = 0
        self.url_budget = 40

    def setup(self, url):
        u = urllib.parse.urlsplit(url)
        host = u.netloc
        if host in self.limits:
            return host
        self.locks[host] = DomainLock(host)
        delay = 0
        info = {
            "url": u.scheme + "://" + host + "/robots.txt",
            "can_fetch": None,
            "crawl_delay": None,
            "request_rate": None,
            "sitemaps": [],
        }
        if self.robots:
            try:
                r = self.session.get(
                    info["url"], timeout=12, headers={"Accept-Encoding": "identity"}
                )
                rp = urllib.robotparser.RobotFileParser()
                rp.set_url(info["url"])
                rp.parse(r.text.splitlines() if r.status_code == 200 else [])
                rr = rp.request_rate(UA)
                info.update(
                    status=r.status_code,
                    can_fetch=rp.can_fetch(UA, url),
                    crawl_delay=rp.crawl_delay(UA),
                    request_rate=rr._asdict() if rr else None,
                    sitemaps=rp.site_maps() or [],
                )
                self.parsers[host] = rp
                delay = info["crawl_delay"] or 0
                if r.status_code not in (200, 404):
                    info["can_fetch"] = False
            except requests.RequestException as e:
                info.update(status=None, error=str(e), can_fetch=False)
        else:
            info.update(status="fixture", can_fetch=True)
        self.rules[host] = info
        self.limits[host] = Limiter(rate=0.5, burst=1, delay=delay)
        self.breakers[host] = Breaker()
        return host

    def fetch(self, url):
        host = self.setup(url)
        lim = self.limits[host]
        br = self.breakers[host]
        rule = self.rules[host]
        path_allowed = (
            self.parsers[host].can_fetch(UA, url)
            if host in self.parsers
            else bool(rule["can_fetch"])
        )
        rule.setdefault("paths", {})[url] = path_allowed
        breaker_before = br.state
        allowed = br.allow()
        if br.state != breaker_before:
            self.log.emit("breaker_transition", host, url, before=breaker_before, after=br.state)
        if (
            host in self.blocked
            or (rule.get("status") not in (200, 404, "fixture"))
            or not path_allowed
            or not allowed
        ):
            self.log.emit("skip", host, url, error="blocked, robots or breaker OPEN")
            return None
        deadline = time.monotonic() + self.url_budget
        for attempt in range(1, 4 if self.mode != "A" else 2):
            if attempt > 1:
                breaker_before = br.state
                allowed = br.allow()
                if br.state != breaker_before:
                    self.log.emit("breaker_transition", host, url, before=breaker_before, after=br.state)
                if not allowed:
                    self.log.emit("skip", host, url, attempt=attempt, error="breaker OPEN")
                    return None
            if (self.mode != "A" or lim.delay) and not lim.acquire(deadline):
                self.log.emit(
                    "budget_exhausted",
                    host,
                    url,
                    attempt=attempt,
                    error="limiter exceeds URL budget",
                )
                return None
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            headers = {}
            cached = self.cache.get(url, {})
            if self.mode == "C":
                if cached.get("etag"):
                    headers["If-None-Match"] = cached["etag"]
                if cached.get("last_modified"):
                    headers["If-Modified-Since"] = cached["last_modified"]
            start = time.monotonic()
            response = None
            raw = b""
            body = b""
            err = None
            try:
                all_headers = dict(self.session.headers)
                all_headers.update(headers)
                response, raw = bounded_get(url, all_headers, self.robots, deadline)
                body = (
                    gzip.decompress(raw)
                    if response.headers.get("Content-Encoding", "").lower() == "gzip"
                    else raw
                )
                status = response.status_code
            except (
                requests.RequestException,
                urllib3.exceptions.HTTPError,
                OSError,
                EOFError,
            ) as e:
                err = str(e)
                status = None
            ms = (time.monotonic() - start) * 1000
            lim.observe(ms, status)
            kind, repeat = classify(status, err)
            breaker_before = br.state
            br.result(repeat)
            if br.state != breaker_before:
                self.log.emit("breaker_transition", host, url, status, ms, attempt, len(raw), before=breaker_before, after=br.state)
            backoff = 0
            source = None
            if repeat and attempt < 3 and self.mode != "A":
                backoff, source = retry_delay(
                    (
                        response.headers.get("Retry-After")
                        if response is not None
                        else None
                    ),
                    attempt,
                )
            self.log.emit(
                "request",
                host,
                url,
                status,
                ms,
                attempt,
                len(raw),
                err,
                classification=kind,
                entity_bytes=(
                    cached.get("entity_bytes", 0) if status == 304 else len(body)
                ),
                backoff_seconds=round(backoff, 3),
                backoff_source=source,
                encoding=(
                    response.headers.get("Content-Encoding")
                    if response is not None
                    else None
                ),
                breaker=br.state,
                breaker_before=breaker_before,
            )
            verdict = None
            if status in (403, 429):
                verdict = detect(status, body)
                self.log.emit("detector", host, url, status, ms, attempt, len(raw), verdict=verdict)
            if status == 304:
                if "records" not in cached:
                    self.log.emit(
                        "cache_error",
                        host,
                        url,
                        304,
                        ms,
                        attempt,
                        0,
                        "304 without cached records",
                    )
                    return None
                return cached["records"]
            if status == 200:
                expected = True
                records = []
                if "books.toscrape" in host or (not self.robots and url.split("?")[0].endswith(".html")):
                    soup = BeautifulSoup(body, "html.parser")
                    cards = soup.select("article.product_pod")
                    expected = bool(cards)
                    records = [
                        {"source": "books", "title": x.h3.a.get("title")} for x in cards
                    ]
                elif "openlibrary" in host:
                    try:
                        data = json.loads(body)
                        expected = "key" in data and "title" in data
                        records = (
                            [
                                {
                                    "source": "openlibrary",
                                    "key": data.get("key"),
                                    "title": data.get("title"),
                                }
                            ]
                            if expected
                            else []
                        )
                    except ValueError:
                        expected = False
                else:
                    try:
                        fixture = json.loads(body)
                        expected = isinstance(fixture.get("rows"), list) and isinstance(
                            fixture.get("cursor"), int
                        )
                        records = fixture["rows"] if expected else []
                        self.last_cursor = fixture.get("cursor")
                    except (ValueError, AttributeError):
                        records = [{"fixture": True}]
                verdict = detect(status, body, expected)
                self.log.emit(
                    "detector",
                    host,
                    url,
                    status,
                    ms,
                    attempt,
                    len(raw),
                    None,
                    verdict=verdict,
                )
                if verdict == "blocked":
                    self.blocked.add(host)
                    p = (
                        ROOT
                        / "logs"
                        / "incidents"
                        / f"{self.run}_{hashlib.sha256(url.encode()).hexdigest()[:12]}"
                    )
                    p.with_suffix(".body").write_bytes(body)
                    save(p.with_suffix(".headers.json"), dict(response.headers))
                    self.log.emit(
                        "incident",
                        host,
                        url,
                        status,
                        ms,
                        attempt,
                        len(raw),
                        "blocked",
                        verdict=verdict,
                    )
                    return None
                if verdict == "suspicion":
                    self.rejected += len(records)
                    return None
                self.cache[url] = {
                    "etag": response.headers.get("ETag"),
                    "last_modified": response.headers.get("Last-Modified"),
                    "entity_bytes": len(body),
                    "records": records,
                }
                return records
            if status in (403, 429) and verdict == "blocked":
                self.blocked.add(host)
                p = (
                    ROOT
                    / "logs"
                    / "incidents"
                    / f"{self.run}_{hashlib.sha256(url.encode()).hexdigest()[:12]}"
                )
                p.with_suffix(".body").write_bytes(body)
                save(p.with_suffix(".headers.json"), dict(response.headers))
                self.log.emit(
                    "incident", host, url, status, ms, attempt, len(raw), "blocked"
                )
                return None
            if not repeat or self.mode == "A" or attempt == 3:
                return None
            if time.monotonic() + backoff > deadline:
                self.log.emit(
                    "budget_exhausted",
                    host,
                    url,
                    attempt=attempt,
                    error="retry delay exceeds URL budget",
                    backoff_seconds=backoff,
                    backoff_source=source,
                )
                return None
            time.sleep(backoff)
        return None

    def collect_incremental(self, feed_url, namespace):
        """Merge a documented monotonic change feed into a persistent local snapshot."""
        state_path = ROOT / "state" / "watermark.json"
        store = load(state_path, {"feeds": {}})
        state = store.setdefault("feeds", {}).get(namespace, {"cursor": 0, "records": []})
        self.last_cursor = None
        separator = "&" if "?" in feed_url else "?"
        changes = self.fetch(feed_url + separator + "since=" + str(state["cursor"]))
        if (
            changes is None
            or self.last_cursor is None
            or self.last_cursor < state["cursor"]
        ):
            return None
        merged = {str(row["id"]): row for row in state["records"]}
        for row in changes:
            if "id" not in row:
                return None
            merged[str(row["id"])] = row
        result = {"cursor": self.last_cursor, "records": list(merged.values())}
        store["feeds"][namespace] = result
        save(state_path, store)
        return result["records"]

    def close(self):
        if self.robots:
            save(ROOT / "state" / "etags.json", self.cache)
        [x.close() for x in self.locks.values()]


def run(mode):
    runid = mode + "_" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    c = Collector(mode, runid)
    start = time.monotonic()
    for url in URLS:
        rows = c.fetch(url)
        if rows:
            c.items.extend(rows)
    history = c.cache.setdefault("__history__", [])
    report = summarize(
        c.log,
        time.monotonic() - start,
        len(c.items),
        c.rejected,
        sum(b.activations for b in c.breakers.values()),
        history,
        profile="remote_books_openlibrary_v1",
        response_profile="full",
        representation_bytes=len(json.dumps(c.items, ensure_ascii=False, sort_keys=True).encode("utf8")),
    )
    report["records"] = c.items
    report["robots"] = c.rules
    history.append({k: v for k, v in report.items() if k not in ("records", "robots")})
    c.close()
    output = Path(tempfile.mkdtemp(prefix="lab7_remote_")) / f"run_report_{mode}.json"
    save(output, report)
    print(json.dumps({"report": str(output), **report}, ensure_ascii=False))
    return int(bool(c.blocked))



# Local reproducible stand (invoked in a temporary copy).
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
import threading

class HTML(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_GET(self):
        if self.headers.get('If-None-Match') == '"html-v1"':
            self.send_response(304); self.send_header('ETag', '"html-v1"'); self.end_headers(); return
        page = int(self.path.rsplit('/', 1)[-1].split('.')[0])
        body = ('<html><body>' + ''.join(f'<article class="product_pod"><h3><a title="HTML book {page * 20 + i}">book</a></h3></article>' for i in range(20)) + '</body></html>').encode()
        self.send_response(200); self.send_header('Content-Type', 'text/html'); self.send_header('ETag', '"html-v1"'); self.end_headers(); self.wfile.write(body)

class API(BaseHTTPRequestHandler):
    version = 100
    def log_message(self, *args): pass
    def do_GET(self):
        query = parse_qs(urlparse(self.path).query)
        since = int(query.get('since', ['0'])[0])
        part = int(query['partition'][0])
        rows = [{'id': i, 'updated': i, 'title': f'API book {i} ' + 'description ' * 10} for i in range(part * 35 + 1, min((part + 1) * 35, self.version) + 1) if i > since]
        body = json.dumps({'rows': rows, 'cursor': self.version, 'description': 'controlled changes feed ' * 5}).encode()
        compressed = 'gzip' in self.headers.get('Accept-Encoding', '')
        if compressed: body = gzip.compress(body)
        self.send_response(200); self.send_header('Content-Type', 'application/json')
        if compressed: self.send_header('Content-Encoding', 'gzip')
        self.end_headers(); self.wfile.write(body)

def benchmark_local():
    servers = [ThreadingHTTPServer(('127.0.0.1', 0), handler) for handler in (HTML, API)]
    for s in servers: threading.Thread(target=s.serve_forever, daemon=True).start()
    html = [f'http://127.0.0.1:{servers[0].server_port}/{i}.html' for i in range(3)]
    feed = [f'http://127.0.0.1:{servers[1].server_port}/changes?partition={i}' for i in range(3)]
    state = [f'partition_{i}' for i in range(3)]
    save(ROOT / 'state' / 'watermark.json', {'feeds': {}})
    try:
        boot = Collector('B', 'abc_bootstrap_controlled', robots=False)
        boot.cache = {}
        for url in html: assert len(boot.fetch(url)) == 20
        assert sum(len(boot.collect_incremental(url, path)) for url, path in zip(feed, state)) == 100
        initial_cache = dict(boot.cache); boot.close()
        API.version = 105
        metrics, datasets = {}, {}
        for mode in 'ABC':
            c = Collector(mode, f'{mode}_abc_controlled', robots=False)
            c.cache = dict(initial_cache) if mode == 'C' else {}
            start = time.monotonic()
            html_parts = [c.fetch(url) for url in html]
            api_parts = [c.collect_incremental(url, path) if mode == 'C' else c.fetch(url + '&since=0') for url, path in zip(feed, state)]
            assert all(part is not None for part in html_parts + api_parts)
            rows = [row for part in html_parts + api_parts for row in part]
            representation = len(json.dumps(rows, ensure_ascii=False, sort_keys=True).encode('utf8'))
            metrics[mode] = summarize(c.log, time.monotonic() - start, len(rows), c.rejected, sum(b.activations for b in c.breakers.values()), list(metrics.values()), profile='local_html_api_165_v1', response_profile='incremental' if mode == 'C' else 'full', representation_bytes=representation)
            datasets[mode] = rows
            c.close()
        assert datasets['A'] == datasets['B'] == datasets['C'] and len(datasets['C']) == 165
        assert metrics['C']['responses_304'] == 3
        c_events = [json.loads(line) for line in (ROOT / 'logs' / ('run_' + metrics['C']['run_id'] + '.jsonl')).read_text(encoding='utf8').splitlines()]
        assert any(e.get('encoding') == 'gzip' and e['status'] == 200 for e in c_events)
        assert all(load(ROOT / 'state' / 'watermark.json', {})['feeds'][key]['cursor'] == 105 for key in state)
        assert 'size_deviation>30%' not in metrics['C']['alerts'] and 'records_deviation>20%' not in metrics['C']['alerts']
        degraded = summarize(c.log, 1, 100, 0, 0, [metrics['B']], profile='local_html_api_165_v1', representation_bytes=metrics['B']['representation_bytes'] // 2)
        assert {'size_deviation>30%', 'records_deviation>20%'} <= set(degraded['alerts'])
        result = {'description': 'Local two-host HTML + API fixture; 100 cached API rows plus 5 changes and 60 HTML rows. Bootstrap is excluded from A/B/C metrics.', 'identical_complete_records': True, 'records': 165, 'history_degraded_test_alerts': degraded['alerts'], 'reports': metrics}
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        for s in servers: s.shutdown(); s.server_close()


class IsolationHandler(BaseHTTPRequestHandler):
    calls = {}
    def log_message(self, *args): pass
    def do_GET(self):
        self.calls[self.path] = self.calls.get(self.path, 0) + 1
        code = 500 if self.path == '/500' else 404 if self.path == '/404' else 200
        self.send_response(code); self.end_headers()
        self.wfile.write((b'valid fixture ' + b'x' * 150) if code == 200 else b'error')

def fixture_local():
    servers = [ThreadingHTTPServer(('127.0.0.1', 0), IsolationHandler) for _ in range(2)]
    for server in servers: threading.Thread(target=server.serve_forever, daemon=True).start()
    a, b = [f'http://127.0.0.1:{server.server_port}' for server in servers]
    c = Collector('B', 'fixture_isolation', robots=False)
    start = time.monotonic()
    try:
        c.fetch(a + '/500')
        assert c.breakers[a.split('//')[1]].state == 'open'
        count = IsolationHandler.calls['/500']
        c.fetch(a + '/500'); assert IsolationHandler.calls['/500'] == count
        assert c.fetch(b + '/healthy')
        time.sleep(c.breakers[a.split('//')[1]].cooldown + 0.1)
        assert c.fetch(a + '/healthy')
        assert c.breakers[a.split('//')[1]].state == 'closed'
        c.fetch(b + '/404'); assert IsolationHandler.calls['/404'] == 1
        transitions = [(e.get('before'), e.get('after')) for e in c.log.events if e['event'] == 'breaker_transition']
        assert ('closed', 'open') in transitions and ('open', 'half-open') in transitions and ('half-open', 'closed') in transitions
        report = summarize(c.log, time.monotonic() - start, 2, c.rejected, sum(br.activations for br in c.breakers.values()), profile='fixture_isolation_v1')
        report['transitions'] = transitions
        report['failure_calls'] = count
        report['404_calls'] = IsolationHandler.calls['/404']
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        c.close()
        for server in servers: server.shutdown(); server.server_close()


_EMBEDDED_TESTS = [('test_pipeline.py', 'import sys, time, json, threading, subprocess, unittest\nfrom pathlib import Path\nfrom http.server import ThreadingHTTPServer, BaseHTTPRequestHandler\nfrom datetime import datetime, timezone, timedelta\nfrom email.utils import format_datetime\nfrom unittest.mock import patch\nfrom types import SimpleNamespace\n\nsys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))\nfrom collect import Collector, ROOT\nfrom retry import classify, retry_delay\nfrom detector import detect\nfrom observability import summarize\n\n\nclass Handler(BaseHTTPRequestHandler):\n    calls = {}\n\n    def log_message(self, *a):\n        pass\n\n    def do_GET(self):\n        self.calls[self.path] = self.calls.get(self.path, 0) + 1\n        if self.path == "/500":\n            code = 500\n            body = b"server failure"\n        elif self.path == "/404":\n            code = 404\n            body = b"not found"\n        elif self.path == "/captcha":\n            code = 200\n            body = b"captcha " + b"x" * 200\n        elif self.path == "/429":\n            code = 429\n            body = b"rate limited"\n        elif self.path == "/403":\n            code = 403\n            body = b"access denied"\n        else:\n            code = 200\n            body = b"healthy fixture " + b"x" * 150\n        self.send_response(code)\n        if self.path == "/429":\n            self.send_header("Retry-After", "0.1")\n        self.end_headers()\n        self.wfile.write(body)\n\n\nclass Suite(unittest.TestCase):\n    @classmethod\n    def setUpClass(cls):\n        cls.servers = [ThreadingHTTPServer(("127.0.0.1", 0), Handler) for _ in range(2)]\n        for s in cls.servers:\n            threading.Thread(target=s.serve_forever, daemon=True).start()\n        cls.urls = [f"http://127.0.0.1:{s.server_port}" for s in cls.servers]\n\n    @classmethod\n    def tearDownClass(cls):\n        for s in cls.servers:\n            s.shutdown()\n\n    def test_error_class_and_retry_after(self):\n        self.assertEqual(classify(404), ("client", False))\n        self.assertEqual(classify(401), ("auth", False))\n        self.assertEqual(classify(403), ("blocked", False))\n        self.assertTrue(classify(429)[1])\n        self.assertTrue(classify(500)[1])\n        self.assertTrue(classify(error="timeout")[1])\n        self.assertEqual(retry_delay("12", 1), (12.0, "Retry-After"))\n        now = datetime.now(timezone.utc).replace(microsecond=0)\n        delay, source = retry_delay(\n            format_datetime(now + timedelta(seconds=20)), 1, now\n        )\n        self.assertEqual((delay, source), (20, "Retry-After"))\n        self.assertEqual(retry_delay(None, 1)[1], "backoff")\n\n    def test_detector(self):\n        self.assertEqual(detect(200, b"captcha" + b"x" * 200), "blocked")\n        self.assertEqual(detect(200, b"x" * 10), "suspicion")\n        self.assertEqual(detect(200, b"x" * 200, False), "suspicion")\n        self.assertEqual(detect(200, b"x" * 200, True), "ok")\n\n    def test_history_compares_matching_full_representation(self):\n        log = SimpleNamespace(run="history_test", events=[{"event": "request", "status": 200, "ms": 1, "bytes": 10, "attempt": 1}])\n        baseline = {"profile": "same", "accepted": 100, "successful_resources": 1, "normalized_mean_response_bytes": 1000}\n        unrelated = {"profile": "other", "accepted": 1, "successful_resources": 1, "normalized_mean_response_bytes": 1}\n        healthy = summarize(log, 1, 100, 0, 0, [baseline, unrelated], profile="same", representation_bytes=1000)\n        self.assertNotIn("size_deviation>30%", healthy["alerts"])\n        degraded = summarize(log, 1, 50, 0, 0, [baseline, unrelated], profile="same", representation_bytes=400)\n        self.assertIn("size_deviation>30%", degraded["alerts"])\n        self.assertIn("records_deviation>20%", degraded["alerts"])\n\n    def test_response_history_matches_incremental_profile(self):\n        event = {"event": "request", "status": 200, "ms": 1, "bytes": 10, "entity_bytes": 100, "attempt": 1}\n        log = SimpleNamespace(run="response_history_test", events=[event])\n        history = [{"profile": "same", "response_profile": "full", "successful_resources": 1, "mean_entity_bytes": 1000}]\n        first = summarize(log, 1, 10, 0, 0, history, profile="same", response_profile="incremental")\n        self.assertEqual(first["response_history_count"], 0)\n        self.assertNotIn("response_size_deviation>30%", first["alerts"])\n        history.append({"profile": "same", "response_profile": "incremental", "successful_resources": 1, "mean_entity_bytes": 1000})\n        second = summarize(log, 1, 10, 0, 0, history, profile="same", response_profile="incremental")\n        self.assertEqual(second["response_history_count"], 1)\n        self.assertIn("response_size_deviation>30%", second["alerts"])\n\n    def test_robots_rules_are_checked_per_path(self):\n        c = Collector("B", "robots_paths_test", robots=True)\n        c.session.get = lambda *args, **kwargs: SimpleNamespace(\n            status_code=200, text="User-agent: *\\nDisallow: /private\\n"\n        )\n        response = SimpleNamespace(status_code=200, headers={})\n        with patch("collect.bounded_get", return_value=(response, b"x" * 150)) as get:\n            self.assertIsNone(c.fetch("http://robots-fixture.invalid/private"))\n            self.assertTrue(c.fetch("http://robots-fixture.invalid/public"))\n            self.assertEqual(get.call_count, 1)\n        for lock in c.locks.values():\n            lock.close()\n\n    def test_isolation_and_404(self):\n        c = Collector("B", "fixture_isolation", robots=False)\n        a, b = self.urls\n        c.fetch(a + "/500")\n        self.assertEqual(c.breakers[a.split("//")[1]].state, "open")\n        before = Handler.calls.get("/500", 0)\n        c.fetch(a + "/500")\n        self.assertEqual(before, Handler.calls["/500"])\n        self.assertTrue(c.fetch(b + "/healthy"))\n        time.sleep(4.1)\n        self.assertTrue(c.fetch(a + "/healthy"))\n        self.assertEqual(c.breakers[a.split("//")[1]].state, "closed")\n        transitions = [(x.get("before"), x.get("after")) for x in c.log.events if x["event"] == "breaker_transition"]\n        self.assertIn(("open", "half-open"), transitions)\n        self.assertIn(("half-open", "closed"), transitions)\n        c.fetch(b + "/404")\n        self.assertEqual(Handler.calls["/404"], 1)\n        c.close()\n\n    def test_block_process(self):\n        script = "import sys;sys.path.insert(0,sys.argv[1]);from collect import Collector;c=Collector(\'B\',\'fixture_block\',robots=False);c.fetch(sys.argv[2]);b=bool(c.blocked);c.close();sys.exit(int(b))"\n        proc = subprocess.run(\n            [sys.executable, "-c", script, str(ROOT / "src"), self.urls[0] + "/captcha"]\n        )\n        self.assertEqual(proc.returncode, 1)\n        self.assertTrue(list((ROOT / "logs" / "incidents").glob("fixture_block*.body")))\n\n    def test_429_retry_after(self):\n        c = Collector("B", "fixture_429", robots=False)\n        c.fetch(self.urls[0] + "/429")\n        c.close()\n        events = [e for e in c.log.events if e["event"] == "request"]\n        self.assertEqual(len(events), 2)\n        self.assertEqual(events[0]["backoff_source"], "Retry-After")\n        self.assertEqual(events[0]["backoff_seconds"], 0.1)\n        verdicts = [e["verdict"] for e in c.log.events if e["event"] == "detector"]\n        self.assertEqual(verdicts, ["suspicion", "suspicion"])\n\n    def test_403_detector_stops_domain(self):\n        c = Collector("B", "fixture_403", robots=False)\n        c.fetch(self.urls[0] + "/403")\n        self.assertTrue(c.blocked)\n        self.assertEqual([e["verdict"] for e in c.log.events if e["event"] == "detector"], ["blocked"])\n        self.assertEqual(len([e for e in c.log.events if e["event"] == "request"]), 1)\n        c.close()\n\n'), ('test_limiter.py', 'import sys\nimport unittest\nfrom pathlib import Path\nfrom unittest.mock import patch\n\nsys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))\nfrom limiter import Limiter\n\n\nclass LimiterFeedbackTest(unittest.TestCase):\n    def test_error_extends_immediate_next_admission(self):\n        for status in (429, 503):\n            with self.subTest(status=status):\n                clock = [0.0]\n                with patch("limiter.time.monotonic", side_effect=lambda: clock[0]), \\\n                     patch("limiter.time.sleep") as sleep, \\\n                     patch("limiter.random.uniform", return_value=1.0):\n                    limiter = Limiter(rate=0.5, burst=1)\n                    self.assertTrue(limiter.acquire(1))\n                    self.assertEqual(limiter.next, 2.0)\n                    clock[0] = 0.2\n                    limiter.observe(100, status)\n                    self.assertAlmostEqual(limiter.next, 8.2)\n                    self.assertFalse(limiter.acquire(8.19))\n                    clock[0] = 8.2\n                    self.assertTrue(limiter.acquire(8.2))\n                    sleep.assert_not_called()\n')]

def _embedded_tests():
    import unittest
    suite = unittest.TestSuite()
    for filename, source in _EMBEDDED_TESTS:
        namespace = {"__name__": "embedded_lab7_tests", "__file__": str(ROOT / "tests" / filename)}
        exec(compile(source, filename, "exec"), namespace)
        for name in ("Suite", "LimiterFeedbackTest"):
            if name in namespace:
                suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(namespace[name]))
    return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1


def _isolated(command):
    with tempfile.TemporaryDirectory(prefix="lab7_check_") as tmp:
        base = Path(tmp)
        (base / "src").mkdir(); (base / "state").mkdir(); (base / "logs" / "incidents").mkdir(parents=True)
        for name in ("collect.py", "limiter.py", "retry.py", "breaker.py", "detector.py", "observability.py"):
            shutil.copy2(ROOT / "src" / name, base / "src" / name)
        for name in ("etags.json", "watermark.json"):
            shutil.copy2(ROOT / "state" / name, base / "state" / name)
        return subprocess.call([sys.executable, "-B", "-X", "utf8", str(base / "src" / "collect.py"), "_" + command])


def compare():
    reports = [load(ROOT / "reports" / f"run_report_{mode}.json", {}) for mode in "ABC"]
    for mode, report in zip("ABC", reports):
        print(json.dumps({"mode": mode, **{k: v for k, v in report.items() if k != "records"}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "B"
    if action in ("self-test", "fixture", "benchmark"):
        sys.exit(_isolated(action))
    if action == "_self-test": sys.exit(_embedded_tests())
    if action == "_fixture": fixture_local(); sys.exit(0)
    if action == "_benchmark": benchmark_local(); sys.exit(0)
    if action == "compare": sys.exit(compare())
    if action in ("B", "C"): sys.exit(run(action))
    if action == "A": sys.exit("A is available only in the local benchmark")
    sys.exit("Usage: collect.py {B|C|compare|self-test|fixture|benchmark}")
