import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from collect import SOURCES, browser_source


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/fail":
            self.send_response(503)
            self.send_header("Content-Type", "application/json")
            self.send_header("Retry-After", "1")
            self.end_headers()
            self.wfile.write(b'{"error":"deliberate failure for workflow error-branch test"}')
            return
        if parsed.path != "/render":
            self.send_error(404)
            return
        query = parse_qs(parsed.query)
        source = query.get("source", [""])[0]
        try:
            limit = int(query.get("limit", ["30"])[0])
            if source not in SOURCES or not 1 <= limit <= 100:
                raise ValueError("Unknown source or invalid limit")
            _, _, metrics, html = browser_source(
                source, limit=limit, block_media=True, max_iterations=20,
                capture=False, benchmark=False,
                artifacts=Path(__file__).resolve().parent / "artifacts/render_errors",
            )
            body = json.dumps({"html": html, "metrics": metrics}, ensure_ascii=False).encode("utf-8")
        except Exception as error:
            body = json.dumps({"error": str(error)}, ensure_ascii=False).encode("utf-8")
            self.send_response(500)
        else:
            self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, message, *args):
        print(message % args, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Локальный API рендеринга для workflow лабораторной 4.')
    parser.add_argument("--port", type=int, default=8789)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Rendering API: http://127.0.0.1:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
