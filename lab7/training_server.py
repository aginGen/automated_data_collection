import argparse
import gzip
import hashlib
import json
import threading
import time
from collections import Counter
from email.utils import formatdate
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parent
COUNTS = Counter()
COUNT_LOCK = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlsplit(self.path).path
        kind = self.server.source_kind
        with COUNT_LOCK:
            COUNTS[(kind, path)] += 1
            number = COUNTS[(kind, path)]
        time.sleep(0.025)
        headers = {}
        status = 200
        content_type = 'application/json; charset=utf-8'
        if path == '/robots.txt':
            content_type = 'text/plain; charset=utf-8'
            body = ('User-agent: *\nAllow: /\nDisallow: /private/\nCrawl-delay: 0\n'
                    'Sitemap: ' + self.server.base_url + '/manifest\n').encode()
        elif path == '/manifest':
            body = json.dumps({'version': 1, 'resources': [
                dict(path=f'/page/{p}', version='1') for p in (1, 2, 3)
            ]}).encode()
        elif path.startswith('/page/') and path[-1:] in ('1', '2', '3'):
            extension = 'html' if kind == 'html' else 'json'
            body = (ROOT / 'fixtures' / f'{kind}_page_{path[-1]}.{extension}').read_bytes()
            if kind == 'html':
                content_type = 'text/html; charset=utf-8'
        elif path == '/fault-500' and kind == 'html' and number <= 2:
            status, body = 500, b'{"error":"prepared source failure"}'
        elif path == '/fault-500' and kind == 'html':
            content_type = 'text/html; charset=utf-8'
            body = (ROOT / 'fixtures' / 'html_page_1.html').read_bytes()
        elif path.startswith('/missing'):
            status, body = 404, b'{"error":"prepared missing URL"}'
        elif path.startswith('/blocked'):
            content_type = 'text/html; charset=utf-8'
            body = b'<html><body>Access denied. Verify you are human. CAPTCHA.</body></html>'
        elif path.startswith('/rate-') and number == 1:
            status, body = 429, b'{"error":"prepared rate limit"}'
            if path == '/rate-seconds':
                headers['Retry-After'] = '1'
            elif path == '/rate-date':
                headers['Retry-After'] = formatdate(time.time()+2, usegmt=True)
        elif path == '/empty':
            body = b'{"records":[]}'
        else:
            body = (ROOT / 'fixtures' / 'api_page_1.json').read_bytes()
        etag = 'W/"' + hashlib.sha256(body).hexdigest()[:24] + '"'
        modified = 'Wed, 01 Jan 2025 00:00:00 GMT'
        headers.update(ETag=etag, **{'Last-Modified': modified, 'X-Training-Fixture': 'true', 'Vary': 'Accept-Encoding'})
        if status == 200 and (self.headers.get('If-None-Match') == etag or
                              (not self.headers.get('If-None-Match') and
                               self.headers.get('If-Modified-Since') == modified)):
            status, body = 304, b''
        elif status == 200 and 'gzip' in self.headers.get('Accept-Encoding', ''):
            body = gzip.compress(body)
            headers['Content-Encoding'] = 'gzip'
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        for key, value in headers.items():
            self.send_header(key, value)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def log_message(self, *args):
        return


def start_servers(html_port=8797, api_port=8798):
    servers = []
    for kind, host, port in [('html', '127.0.0.1', html_port), ('api', '127.0.0.2', api_port)]:
        server = ThreadingHTTPServer((host, port), Handler)
        server.source_kind, server.base_url = kind, f'http://{host}:{port}'
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
    return servers


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--html-port', type=int, default=8797)
    parser.add_argument('--api-port', type=int, default=8798)
    args = parser.parse_args()
    servers = start_servers(args.html_port, args.api_port)
    print('Training HTTP sources:', ', '.join(s.base_url for s in servers), flush=True)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        for server in servers:
            server.shutdown()
            server.server_close()
