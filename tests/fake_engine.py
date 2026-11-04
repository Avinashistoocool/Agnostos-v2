"""Tiny stand-in for the Agnostos engine sidecar (newline-delimited JSON over stdio).

Used to test the Tauri shell without the real engine; see docs/engine-protocol.md.
Run: AGNOSTOS_ENGINE_CMD="python tests/fake_engine.py" npm run tauri dev
"""

from __future__ import annotations

import json
import sys
import time


def send(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def handle(req: dict) -> None:
    rid = req.get("id")
    method = req.get("method")
    params = req.get("params") or {}
    if method == "app.info":
        send({"id": rid, "result": {
            "version": "2.2.0", "engine_version": "fake-1", "data_dir": "",
            "user": None, "onboarding": {"completed": [], "done": False},
        }})
    elif method == "echo":
        send({"event": "fake.echo", "data": params})
        send({"id": rid, "result": params})
    elif method == "emit":
        send({"event": params.get("event", "job.log"), "data": params.get("data", {})})
        send({"id": rid, "result": {"ok": True}})
    elif method == "sleep":
        time.sleep(float(params.get("seconds", 1)))
        send({"id": rid, "result": {"ok": True}})
    elif method == "crash":
        sys.stderr.write("fake engine crashing on request\n")
        sys.stderr.flush()
        sys.exit(3)
    else:
        send({"id": rid, "error": {"code": "not_found", "message": f"Unknown method {method}"}})


def main() -> int:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    sys.stderr.write("fake engine ready\n")
    sys.stderr.flush()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            sys.stderr.write(f"bad json: {line}\n")
            continue
        handle(req)
    return 0


if __name__ == "__main__":
    sys.exit(main())
