"""Local single-command server: the review portal + the same API the Lambda exposes.

  python3 -m claimsense serve --port 8080     (or: make up / docker run -p 8080:8080 ...)

GET  /            -> frontend/index.html (and its static files)
GET  /health      -> {"ok": true, "release", "brain"}
POST /recommend   -> service.handle(body)
Stdlib only. Binds to 127.0.0.1 by default; the container binds 0.0.0.0.
"""
from __future__ import annotations

import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .service import handle, pipeline

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(FRONTEND), **kw)

    def _json(self, status: int, body) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.rstrip("/") == "/health":
            p = pipeline()
            return self._json(200, {"ok": True, "release": p.release.version, "brain": p.brain.name})
        if self.path.endswith(".py"):
            return self._json(404, {"error": "not_found"})
        return super().do_GET()

    def do_POST(self):
        if self.path.rstrip("/") != "/recommend":
            return self._json(404, {"error": "not_found"})
        try:
            n = int(self.headers.get("content-length", "0"))
            if n > 64_000:
                return self._json(413, {"error": "too_large"})
            body = json.loads(self.rfile.read(n) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return self._json(400, {"error": "bad_request", "message": "body must be JSON"})
        out = handle(body if isinstance(body, dict) else {})
        self._json(out["status"], out["body"])

    def log_message(self, fmt, *args):          # EMF lines from service.handle are the request log
        pass


def serve(host: str = "127.0.0.1", port: int = 8080) -> None:
    srv = ThreadingHTTPServer((host, port), Handler)
    print(f"ClaimSense on http://{host}:{port}  (portal + /recommend, brain={pipeline().brain.name})", flush=True)
    srv.serve_forever()
