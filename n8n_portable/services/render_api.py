"""Локальный JS rendering API для n8n. Разрешена только учебная страница варианта 3."""
import json
import os
import sys
import time
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from collect import (ROOT, URL, ITEM, MemoryMeter, collect_page, make_context,
                     robots_check, route_page, save_failure, save_json, utc, browser_proxy,
                     write_csv, LOG_FIELDS)
from playwright.sync_api import sync_playwright


render_lock = threading.Lock()

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path not in ("/", "/health"):
            self.send_error(404); return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"status": "ready", "service": "lab4-renderer", "pid": os.getpid(), "workspace": str(Path(__file__).resolve().parent.parent)}).encode())

    def do_POST(self):
        if not render_lock.acquire(blocking=False):
            self.send_error(429, "Renderer is busy")
            return
        try:
            self.render_request()
        finally:
            render_lock.release()

    def render_request(self):
        if self.path != "/render":
            self.send_error(404)
            return
        try:
            args = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
            if args.get("url") != URL or args.get("render_js") is not True or args.get("wait_for") != ITEM:
                raise ValueError("Разрешён только URL и селектор лабораторной, render_js=true")
            limit = int(args.get("max_items", 200))
            if not 20 <= limit <= 200:
                raise ValueError("max_items должен быть 20..200")
            out = ROOT
            out.mkdir(parents=True, exist_ok=True)
            rules = robots_check(out)
            log, errors, network = [], [], []
            stats = {"blocked": 0}
            start = time.perf_counter()
            with MemoryMeter() as memory, sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True, **browser_proxy())
                context = make_context(browser)
                try:
                    page = context.new_page()
                    route_page(page, True, rules, stats)
                    def finished(req):
                        try:
                            network.append({"url": req.url, "body_bytes": req.sizes()["responseBodySize"],
                                            "resource_type": req.resource_type})
                        except Exception as e:
                            errors.append({"network": req.url, "error": str(e)})
                    page.on("requestfinished", finished)
                    rows, reason = collect_page(page, 1, limit, 24, 1.0, log, errors, out)
                    page.wait_for_selector(ITEM)
                    html = page.content()
                except Exception as e:
                    save_failure(page, out, "render_failure", str(e))
                    raise
                finally:
                    context.close()
                    browser.close()
            metrics = {"render_api_calls": 1, "render_js": True, "wait_for": ITEM,
                       "requested_records": limit, "rows": len(rows), "stop_reason": reason,
                       "seconds": time.perf_counter() - start, "site_requests": len(network),
                       "site_body_bytes": sum(n["body_bytes"] for n in network),
                       "renderer_peak_rss_mb": memory.peak / 1_000_000, "timestamp": utc()}
            save_json(out / "render_metrics.json", metrics)
            save_json(out / "network.json", network)
            write_csv(out / "render_collection_log.csv", log, LOG_FIELDS)
            (out / "rendered.html").write_text(html, encoding="utf-8")
            body = json.dumps({"html": html, "metrics": metrics}, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            body = json.dumps({"error": str(e)}).encode()
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)


if __name__ == "__main__":
    print("Local rendering API: http://127.0.0.1:8894/render", flush=True)
    ThreadingHTTPServer(("127.0.0.1", 8894), Handler).serve_forever()
