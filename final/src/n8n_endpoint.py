import argparse
import json
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .files import PROJECT


def serve(port, demo_failure):
    command = [sys.executable, "-m", "src.run_pipeline", "--mode", "incremental"]
    if demo_failure:
        command.append("--simulate-api-failure")

    class Handler(BaseHTTPRequestHandler):
        def reply(self, status, data):
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/health":
                self.reply(200, {"status": "ready", "demo_failure": demo_failure})
            else:
                self.send_error(404)

        def do_POST(self):
            if self.path != "/run":
                self.send_error(404)
                return
            if self.headers.get("X-Course-Runner") != "final-project" or self.headers.get("Origin") is not None:
                self.send_error(403)
                return
            try:
                job = subprocess.run(command, cwd=PROJECT, capture_output=True, encoding="utf-8", timeout=540)
                result = json.loads(job.stdout)
            except (OSError, subprocess.SubprocessError, UnicodeError, ValueError) as exc:
                self.reply(500, {"message": f"Не получен отчёт Python ({type(exc).__name__})"})
                return
            if result["exit_code"] != job.returncode:
                self.reply(500, {"message": "Код процесса расходится с отчётом Python"})
                return
            self.reply(200, result)

    with ThreadingHTTPServer(("127.0.0.1", port), Handler) as server:
        print(f"n8n runner ready: http://127.0.0.1:{port}/run", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8796)
    parser.add_argument("--demo-failure", action="store_true")
    arguments = parser.parse_args()
    serve(arguments.port, arguments.demo_failure)
