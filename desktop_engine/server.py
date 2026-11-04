"""Newline-delimited JSON over stdio: request dispatch and event emission."""
from __future__ import annotations

import io
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import threading
import traceback

from . import __version__
from .errors import EngineError

_out_lock = threading.Lock()
_protocol_out = None  # real stdout; sys.stdout is redirected to stderr


def write_message(message: dict) -> None:
    line = json.dumps(message, ensure_ascii=False, separators=(",", ":"), default=str)
    with _out_lock:
        _protocol_out.write(line + "\n")
        _protocol_out.flush()


def emit(event: str, data) -> None:
    write_message({"event": event, "data": data})


def _probe(accounts, kind: str, timeout: float = 90) -> dict:
    from .jobs import child_environment, worker_command, _popen_flags
    workspace = accounts.workspace()
    env = child_environment(workspace)
    try:
        done = subprocess.run(worker_command("--probe", kind), cwd=workspace.path, env=env,
                              stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout,
                              creationflags=_popen_flags())
    except subprocess.TimeoutExpired:
        return {"ok": False, "detail": f"Timed out after {int(timeout)} s"}
    except OSError as exc:
        raise EngineError("unavailable", f"Could not start the connection test: {exc}") from exc
    text = done.stdout.decode("utf-8", errors="replace")
    marker = text.rfind("@@PROBE@@")
    if marker < 0:
        tail = (text + done.stderr.decode("utf-8", errors="replace")).strip().splitlines()[-3:]
        return {"ok": False, "detail": "Test failed: " + (" ".join(tail) or f"exit {done.returncode}")}
    try:
        return json.loads(text[marker + 9:].strip().splitlines()[0])
    except (ValueError, IndexError):
        return {"ok": False, "detail": "Test returned an unreadable result"}


class Engine:
    def __init__(self, root: Path | None = None, open_browser=None, emit_fn=None):
        from .accounts import Accounts
        from .jobs import JobManager
        from .oauth import GitHubFlow
        self.accounts = Accounts(root)
        self.emit = emit_fn or emit
        self.jobs = JobManager(self.accounts, self.emit)
        self.github = GitHubFlow()
        self.open_browser = open_browser
        self.methods = {
            "app.info": self.app_info,
            "ping": lambda p: {"ok": True, "engine_version": __version__},
            "auth.status": lambda p: {"user": self.accounts.public(self.accounts.current())},
            "auth.guest": lambda p: self._user(self.accounts.guest(p.get("name"))),
            "auth.register": lambda p: self._user(self.accounts.register(
                p.get("name"), p.get("email"), p.get("password"))),
            "auth.login": lambda p: self._user(self.accounts.login(p.get("email"), p.get("password"))),
            "auth.google": self.auth_google,
            "auth.github.start": lambda p: self.github.start(self.accounts.root),
            "auth.github.poll": lambda p: self.github.poll(self.accounts, p.get("device_code")),
            "auth.logout": self.logout,
            "onboarding.get": lambda p: self._signed(self.accounts.onboarding),
            "onboarding.complete": lambda p: self.accounts.complete_step(p.get("step")),
            "resume.import": lambda p: {"profile": self.accounts.import_resume(p.get("path"))},
            "profile.get": lambda p: {"profile": self.accounts.profile()},
            "profile.update": lambda p: {"profile": self.accounts.save_profile(p.get("profile"))},
            "settings.get": self.settings_get,
            "settings.update": lambda p: {"settings": self.accounts.update_settings(p.get("values"))},
            "email.test": self.email_test,
            "llm.test": self.llm_test,
            "stats.get": self.stats,
            "professors.list": self.professors,
            "drafts.update": self.drafts_update,
            "replies.list": self.replies_list,
            "replies.update": self.replies_update,
            "conversations.get": self.conversations,
            "commands.list": self.commands,
            "jobs.start": lambda p: {"job": self.jobs.start(p.get("command"), p.get("options"),
                                                            p.get("confirmation"))},
            "jobs.list": lambda p: {"jobs": self.jobs.list()},
            "jobs.log": lambda p: self.jobs.log(p.get("job_id"), p.get("offset")),
            "jobs.answer": lambda p: self.jobs.answer(p.get("job_id"), p.get("answer")),
            "jobs.cancel": lambda p: self.jobs.cancel(p.get("job_id")),
            "dialog.none": lambda p: {},
        }

    # ---------- helpers ----------
    def _user(self, record) -> dict:
        return {"user": self.accounts.public(record)}

    def _signed(self, fn):
        self.accounts.require()
        return fn()

    # ---------- methods ----------
    def app_info(self, _p) -> dict:
        from outreach import __version__ as cli_version
        return {"version": cli_version, "engine_version": __version__,
                "data_dir": str(self.accounts.root),
                "user": self.accounts.public(self.accounts.current()),
                "onboarding": self.accounts.onboarding()}

    def auth_google(self, p) -> dict:
        from .oauth import google_sign_in
        connect = p.get("connect_gmail", False)
        if not isinstance(connect, bool):
            raise EngineError("bad_request", "connect_gmail must be true or false")
        kwargs = {"open_browser": self.open_browser} if self.open_browser else {}
        return self._user(google_sign_in(self.accounts, connect, self.emit, **kwargs))

    def logout(self, _p) -> dict:
        self.accounts.logout()
        return {"ok": True}

    def settings_get(self, _p) -> dict:
        self.accounts.require()
        return {"settings": self.accounts.settings(), "secrets": self.accounts.secret_keys()}

    def email_test(self, p) -> dict:
        self.accounts.require()
        kind = p.get("kind")
        if kind not in ("smtp", "imap"):
            raise EngineError("bad_request", 'kind must be "smtp" or "imap"')
        return _probe(self.accounts, kind)

    def llm_test(self, _p) -> dict:
        self.accounts.require()
        return _probe(self.accounts, "llm")

    def stats(self, _p) -> dict:
        from .data import stats
        self.accounts.require()
        return stats(self.accounts)

    def professors(self, p) -> dict:
        from .data import list_professors
        self.accounts.require()
        return list_professors(self.accounts, p.get("query"), p.get("status"),
                               p.get("offset"), p.get("limit"))

    def drafts_update(self, p) -> dict:
        from .data import update_draft
        self.accounts.require()
        return {"professor": update_draft(self.accounts, p.get("sheet"), p.get("row"),
                                          p.get("version"), p.get("draft"), p.get("subject"))}

    def replies_list(self, _p) -> dict:
        from .data import replies
        self.accounts.require()
        return replies(self.accounts)

    def replies_update(self, p) -> dict:
        from .data import update_reply
        self.accounts.require()
        return update_reply(self.accounts, p.get("index"), p.get("version"),
                            p.get("body"), p.get("approved"))

    def conversations(self, _p) -> dict:
        from .data import conversations
        self.accounts.require()
        return conversations(self.accounts)

    def commands(self, _p) -> dict:
        from .catalog import command_specs
        self.accounts.require()
        return {"commands": command_specs()}

    # ---------- dispatch ----------
    def handle(self, message) -> dict | None:
        """Process one decoded request; returns the response object (or None for no id)."""
        if not isinstance(message, dict):
            return {"id": None, "error": {"code": "bad_request", "message": "Request must be an object"}}
        request_id = message.get("id")
        method = message.get("method")
        params = message.get("params")
        if params is None:
            params = {}
        try:
            if not isinstance(method, str) or method not in self.methods:
                raise EngineError("bad_request", f"Unknown method: {method}")
            if not isinstance(params, dict):
                raise EngineError("bad_request", "params must be an object")
            result = self.methods[method](params)
            return {"id": request_id, "result": result if result is not None else {}}
        except EngineError as exc:
            return {"id": request_id, "error": exc.to_json()}
        except Exception as exc:  # never let one request kill the engine
            traceback.print_exc(file=sys.stderr)
            return {"id": request_id, "error": {"code": "internal",
                                                "message": f"{type(exc).__name__}: {exc}"}}

    def handle_line(self, line: str) -> dict | None:
        line = line.strip().lstrip("\ufeff")
        if not line:
            return None
        try:
            message = json.loads(line)
        except ValueError:
            return {"id": None, "error": {"code": "bad_request", "message": "Invalid JSON"}}
        return self.handle(message)


SLOW = {"auth.google", "auth.github.poll", "auth.github.start", "email.test", "llm.test",
        "resume.import", "stats.get", "professors.list", "drafts.update"}


def serve() -> int:
    global _protocol_out
    # Only protocol JSON may reach stdout: everything else (prints, logging,
    # library warnings) is diverted to stderr, which the shell logs.
    raw = sys.stdout.buffer if hasattr(sys.stdout, "buffer") else None
    if raw is None:
        raw = os.fdopen(os.dup(1), "wb")
    _protocol_out = io.TextIOWrapper(raw, encoding="utf-8", newline="\n", write_through=True)
    sys.stdout = sys.stderr
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace", newline=None) \
        if hasattr(sys.stdin, "buffer") else sys.stdin
    try:
        engine = Engine()
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        engine = None
        startup_error = f"{type(exc).__name__}: {exc}"
    print(f"[engine] agnostos-engine {__version__} ready (pid {os.getpid()})", file=sys.stderr, flush=True)

    def run(line: str):
        if engine is None:
            try:
                rid = json.loads(line).get("id")
            except (ValueError, AttributeError):
                rid = None
            write_message({"id": rid, "error": {"code": "internal",
                                                "message": "Engine failed to start: " + startup_error}})
            return
        response = engine.handle_line(line)
        if response is not None and (response.get("id") is not None or "error" in response):
            write_message(response)

    for line in stdin:
        method = ""
        try:
            method = json.loads(line).get("method", "")
        except (ValueError, AttributeError):
            pass
        if method in SLOW:
            threading.Thread(target=run, args=(line,), daemon=True).start()
        else:
            run(line)
    if engine is not None:
        engine.jobs.shutdown()
    return 0
