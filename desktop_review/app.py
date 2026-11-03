"""Loopback HTTP surface: no CLI imports, mail access, or send endpoints."""
from __future__ import annotations

import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import sys
import threading
from urllib.parse import urlsplit

from .storage import ReviewError, Workspace, read_queue, statistics, update_queue

ASSETS = {"app.js": "text/javascript; charset=utf-8",
          "app.css": "text/css; charset=utf-8"}
CONTENT_SECURITY = ("default-src 'none'; script-src 'self' 'unsafe-inline'; "
                    "style-src 'self' 'unsafe-inline'; connect-src 'self'; "
                    "img-src data:; frame-src 'self'; base-uri 'none'; form-action 'none'")


def assets_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "desktop_review" / "web"
    return Path(__file__).resolve().parent / "web"


def suggestion() -> str | None:
    candidates = (Path.cwd(), Path(sys.executable).resolve().parent,
                  Path(__file__).resolve().parents[1])
    for candidate in candidates:
        for path in (candidate, *candidate.parents):
            try:
                return str(Workspace.validate(str(path)))
            except ReviewError:
                pass
    return None


def start(workspace: Workspace):
    token = secrets.token_urlsafe(32)
    root = assets_root()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def response(self, status: int, body: bytes, kind: str = "application/json"):
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", CONTENT_SECURITY)
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                pass

        def json(self, status: int, value):
            self.response(status, json.dumps(value, ensure_ascii=False).encode("utf-8"),
                          "application/json; charset=utf-8")

        def authorized(self):
            received = self.headers.get("X-Desktop-Token", "")
            return hmac.compare_digest(received, token)

        def route(self):
            if self.headers.get("Host", "") != f"127.0.0.1:{self.server.server_port}":
                raise ReviewError(403, "Local host only")
            path = urlsplit(self.path).path
            if self.command == "GET" and path in ("/", "/app.js", "/app.css", "/health"):
                if path == "/health":
                    return self.json(200, {"ok": True})
                filename = "index.html" if path == "/" else path[1:]
                kind = ASSETS.get(filename, "text/html; charset=utf-8")
                return self.response(200, (root / filename).read_bytes(), kind)
            if not self.authorized():
                raise ReviewError(403, "Desktop token required")
            origin = self.headers.get("Origin")
            if origin and origin != f"http://127.0.0.1:{self.server.server_port}":
                raise ReviewError(403, "Cross-origin requests are not allowed")
            if self.command == "GET":
                if path == "/api/status":
                    return self.json(200, {"workspace": str(workspace.path) if workspace.path else None,
                                           "suggested": suggestion() if not workspace.path else None,
                                           "review_supported": workspace.coordinated_cli()})
                if path == "/api/stats":
                    return self.json(200, statistics(workspace))
                if path == "/api/queue":
                    return self.json(200, {**read_queue(workspace),
                                           "review_supported": workspace.coordinated_cli()})
                if path == "/api/conversations":
                    file = workspace.file("conversations.html")
                    if not file.is_file():
                        raise ReviewError(404, "No output/conversations.html yet")
                    if file.stat().st_size > 20 * 1024 * 1024:
                        raise ReviewError(413, "Conversation HTML is too large to display")
                    return self.json(200, {"html": file.read_text(encoding="utf-8"),
                                           "modified": file.stat().st_mtime})
            if self.command == "POST":
                if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                    raise ReviewError(415, "JSON required")
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 50000:
                    raise ReviewError(413, "Invalid request size")
                try:
                    body = json.loads(self.rfile.read(size))
                    if not isinstance(body, dict):
                        raise ValueError("JSON object required")
                except (ValueError, UnicodeDecodeError):
                    raise ReviewError(400, "Invalid JSON request") from None
                if path == "/api/workspace":
                    if set(body) != {"path"}:
                        raise ReviewError(400, "Workspace path required")
                    return self.json(200, {"workspace": str(workspace.select(body["path"]))})
                if path.startswith("/api/queue/") and path[11:].isdigit():
                    if set(body) != {"version", "body", "approved"}:
                        raise ReviewError(400, "Only body and approval may be changed")
                    return self.json(200, update_queue(
                        workspace, int(path[11:]), body["version"], body["body"], body["approved"]))
            raise ReviewError(404, "Not found")

        def do_GET(self):
            self.handle_request()

        def do_POST(self):
            self.handle_request()

        def handle_request(self):
            try:
                self.route()
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                return
            except ReviewError as exc:
                self.json(exc.status, {"error": str(exc)})
            except (OSError, ValueError) as exc:
                self.json(503, {"error": f"Local file unavailable: {type(exc).__name__}"})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, token, f"http://127.0.0.1:{server.server_port}"
