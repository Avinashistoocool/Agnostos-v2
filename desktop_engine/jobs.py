"""Engine-side CLI jobs: vetted argv, subprocess worker, streamed output, [Y/N] relay."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import threading

from desktop_review.commands import build_argv
from desktop_review.jobs import _alive
from desktop_review.settings import SettingsStore
from desktop_review.storage import ReviewError
from outreach.queue_store import lock_held

from .catalog import MIN_ONE, allowed_options, confirmation_for
from .errors import EngineError, from_review

JOB_ID = re.compile(r"^[0-9a-f]{24}$")
PROMPT_RE = re.compile(r"\[Y/N\]:\s*$")
READ_ONLY = {"stats", "profile", "models", "tls-check"}
FINAL = {"done", "failed", "cancelled", "interrupted"}
ENFORCED = {"OUTPUT_DIR", "TARGET_XLSX", "FOCUS", "RESPECT_ROBOTS", "SCRAPE_HEADLESS",
            "DAILY_SEND_CAP", "RESEND_DAILY_CAP", "SEND_DELAY_MIN", "SEND_DELAY_MAX",
            "SEND_LOCAL_WINDOW"}
CONFIG_KEYS = set("""
ATTACHMENTS AVAILABILITY BUDGET_USD CAN_SELF_FUND DISCOVER_ALSO_UNIVERSITIES DISCOVER_BATCHES
DISCOVER_COUNT DISCOVER_COUNTRIES DISCOVER_MAX_PAGES DISCOVER_PRESTIGE_WEIGHT DISCOVER_QUERIES
DISCOVER_SINCE DISCOVER_TOP_UNIVERSITIES DISCOVER_INCLUDE_COMPANIES FUNDING_WEIGHT DRAFT_MODEL FOCUS_KEYWORDS FOLLOWUP_GAP_DAYS
FUNDING_FOLLOWUPS GEOGRAPHY GROQ_API_KEY GROQ_BASE_URL HUMANIZE_REWRITE HUMANIZE_THRESHOLD
LLM_PROVIDER MAX_OUTPUT_TOKENS MAX_PROFESSORS MEET_LEAD_DAYS MEET_LINK MEET_MINUTES MEET_MY_HOURS
MEET_MY_TZ MEET_THEIR_HOURS MIN_LOCAL_SCORE MY_EMAIL_ALIASES OPENAI_API_KEY OPENAI_BASE_URL
OPENALEX_API_KEY OPENALEX_MAILTO OPENALEX_WORKS POSITION PROXY_PASSWORD PROXY_SERVER
PROXY_USERNAME REPLY_TO RESUME_PATH SAVE_TO_SENT SCORE_MODEL SCRAPE_DELAY_MAX SCRAPE_DELAY_MIN
SELF_FUND_NOTE SEND_MIN_PROBABILITY USE_OPENALEX VERIFY_WORKERS AGNOSTOS_DESKTOP_JOB_NONCE
AGNOSTOS_DESKTOP_JOB_SPEC AGNOSTOS_DESKTOP_JOB_RESULT AGNOSTOS_DESKTOP_WORKSPACE
AGNOSTOS_DESKTOP_CONFIG_DIR
""".split())


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def worker_command(*args: str) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, *args]
    return [sys.executable, "-m", "desktop_engine", *args]


def child_environment(workspace) -> dict:
    """Same hardened environment the desktop_review GUI gives CLI jobs.

    Inherited outreach settings are dropped so a job only ever sees this
    workspace's .env (plus the GUI's enforced safety values).
    """
    from .util import read_env
    env = SettingsStore(workspace).job_environment()
    root = workspace.path
    own = read_env(root / ".env")
    for key in list(env):
        if (key in CONFIG_KEYS or key.startswith(("SMTP_", "IMAP_", "RESEND_", "GOOGLE_"))) \
                and key not in own and key not in ENFORCED:
            env.pop(key)
    env["AGNOSTOS_ENV_FILE"] = str(root / ".env")
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    if not getattr(sys, "frozen", False):
        repo = str(Path(__file__).resolve().parents[1])
        env["PYTHONPATH"] = repo + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    return env


def _popen_flags() -> int:
    return subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def validate_options(command: str, options) -> dict:
    if not isinstance(command, str) or not allowed_options(command):
        if command not in ("calendar-auth", "tls-check"):
            raise EngineError("bad_request", f"Unknown command: {command}")
    if options is None:
        options = {}
    if not isinstance(options, dict):
        raise EngineError("bad_request", "options must be an object")
    for key, value in options.items():
        if key in MIN_ONE and isinstance(value, int) and not isinstance(value, bool) and value <= 0:
            raise EngineError("bad_request", f"{key} must be at least 1")
    return options


class JobManager:
    def __init__(self, accounts, emit):
        self.accounts = accounts
        self.emit = emit
        self._lock = threading.RLock()
        self.active: dict[str, dict] = {}

    # ---------- storage ----------
    def _dir(self) -> Path:
        path = self.accounts.user_dir() / "jobs"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _file(self, job_id, suffix: str) -> Path:
        if not isinstance(job_id, str) or not JOB_ID.fullmatch(job_id):
            raise EngineError("bad_request", "Invalid job id")
        return self._dir() / (job_id + suffix)

    def _write(self, record: dict) -> None:
        from .util import write_json
        write_json(self._file(record["id"], ".json"), record)

    def _load(self, job_id: str) -> dict:
        path = self._file(job_id, ".json")
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise EngineError("not_found", "Job not found") from None
        except (OSError, ValueError) as exc:
            raise EngineError("internal", f"Job record unreadable: {exc}") from exc
        if record.get("status") not in FINAL and job_id not in self.active:
            result = self._file(job_id, ".result.json")
            if result.exists():
                try:
                    record.update(json.loads(result.read_text(encoding="utf-8")))
                except (OSError, ValueError):
                    record["status"] = "interrupted"
            elif not _alive(record.get("pid")):
                record["status"] = "interrupted"
                record["finished"] = record.get("finished") or now()
            else:
                record["status"] = "running"
                record["detached"] = True
        return record

    @staticmethod
    def public(record: dict) -> dict:
        return {"id": record["id"], "command": record["command"],
                "options": record.get("options") or {}, "status": record["status"],
                "started": record["started"], "finished": record.get("finished"),
                "exit_code": record.get("exit_code"), "live": bool(record.get("live")),
                "prompt": record.get("prompt") if record["status"] == "waiting_input" else None}

    def list(self) -> list[dict]:
        self.accounts.require()
        with self._lock:
            records = []
            for path in self._dir().glob("*.json"):
                if JOB_ID.fullmatch(path.stem):
                    try:
                        records.append(self._load(path.stem))
                    except EngineError:
                        continue
            records.sort(key=lambda r: r.get("started", ""), reverse=True)
            return [self.public(r) for r in records[:100]]

    def log(self, job_id, offset=0) -> dict:
        self.accounts.require()
        if offset is None:
            offset = 0
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise EngineError("bad_request", "offset must be a non-negative integer")
        self._load(job_id)
        path = self._file(job_id, ".log")
        with self._lock:
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except FileNotFoundError:
                lines = []
        return {"lines": lines[offset:], "offset": len(lines)}

    # ---------- start ----------
    def start(self, command, options, confirmation=None) -> dict:
        self.accounts.require()
        options = validate_options(command, options)
        if confirmation is not None and not isinstance(confirmation, str):
            raise EngineError("bad_request", "confirmation must be text")
        confirmation = confirmation or None
        workspace = self.accounts.workspace()
        try:
            argv, live = build_argv(workspace, command, options, confirmation)
        except ReviewError as exc:
            if exc.status == 403:
                expected = confirmation_for(command) or "SEND"
                raise EngineError("confirmation_required",
                                  f'Type "{expected}" to confirm this live mail action') from exc
            raise from_review(exc) from exc
        with self._lock:
            if any(r["status"] in ("running", "waiting_input") for r in self.list()):
                raise EngineError("conflict", "Another job is already running; wait for it to finish")
            root = workspace.path
            output = root / "output"
            if command not in READ_ONLY and any(
                    lock_held(output / name) for name in (".send.lock", ".resend.lock",
                                                          ".replies.lock", ".legacy.lock")):
                raise EngineError("conflict", "A scheduled live mail job is active; retry when it finishes")
            if lock_held(output / ".desktop_cli.lock"):
                raise EngineError("conflict", "Another desktop CLI job is active in this workspace")
            env = child_environment(workspace)
            if not env.get("DISCOVER_QUERIES"):
                interests = [i for i in self.accounts.profile().get("research_interests", [])
                             if 3 < len(i) < 70 and not re.search(r"projects?$", i, re.I)]
                if interests:
                    env["DISCOVER_QUERIES"] = "; ".join(interests[:8])
            if live and options.get("limit") is not None:
                cap_key = "RESEND_DAILY_CAP" if command in {"resend", "legacy", "legacy-researchers"} \
                    else "DAILY_SEND_CAP"
                if options["limit"] > int(env[cap_key]):
                    raise EngineError("bad_request",
                                      f"Live limit cannot exceed the configured cap of {env[cap_key]}")
            job_id = secrets.token_hex(12)
            nonce = secrets.token_urlsafe(32)
            record = {"id": job_id, "command": command, "options": options,
                      "confirmation": confirmation, "argv": argv, "live": live,
                      "workspace": str(root),
                      "nonce_hash": hashlib.sha256(nonce.encode()).hexdigest(),
                      "status": "running", "started": now(), "finished": None,
                      "exit_code": None, "prompt": None, "pid": None}
            self._write(record)
            env["AGNOSTOS_ENGINE_JOB_FILE"] = str(self._file(job_id, ".json"))
            env["AGNOSTOS_ENGINE_JOB_NONCE"] = nonce
            env["AGNOSTOS_ENGINE_USER_DIR"] = str(self.accounts.user_dir())
            self._file(job_id, ".log").write_text("", encoding="utf-8")
            try:
                process = subprocess.Popen(
                    worker_command("--worker", *argv), cwd=root, env=env,
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    creationflags=_popen_flags())
            except OSError as exc:
                record.update(status="failed", finished=now())
                self._write(record)
                raise EngineError("unavailable", f"Could not start the job: {exc}") from exc
            record["pid"] = process.pid
            self._write(record)
            self.active[job_id] = {"process": process, "record": record}
            threading.Thread(target=self._pump, args=(job_id,), daemon=True).start()
        self.emit("job.status", {"job": self.public(record)})
        return self.public(record)

    # ---------- streaming ----------
    def _append(self, job_id: str, line: str) -> None:
        with self._lock:
            with self._file(job_id, ".log").open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        self.emit("job.log", {"job_id": job_id, "line": line})

    def _pump(self, job_id: str) -> None:
        entry = self.active[job_id]
        process: subprocess.Popen = entry["process"]
        record = entry["record"]
        stream = process.stdout
        buffer = ""
        decoder = __import__("codecs").getincrementaldecoder("utf-8")(errors="replace")
        while True:
            chunk = stream.read1(4096) if hasattr(stream, "read1") else stream.read(1)
            if not chunk:
                break
            buffer += decoder.decode(chunk)
            parts = re.split(r"\r\n|\n|\r", buffer)
            buffer = parts.pop()
            for part in parts:
                if part.strip():
                    self._append(job_id, part.rstrip())
            if PROMPT_RE.search(buffer):
                text = buffer.rstrip()
                buffer = ""
                self._append(job_id, text)
                with self._lock:
                    record.update(status="waiting_input", prompt=text.strip())
                    self._write(record)
                self.emit("job.prompt", {"job_id": job_id, "text": text.strip()})
                self.emit("job.status", {"job": self.public(record)})
        tail = buffer + decoder.decode(b"", final=True)
        if tail.strip():
            self._append(job_id, tail.rstrip())
        stream.close()
        code = process.wait()
        try:
            if process.stdin:
                process.stdin.close()
        except OSError:
            pass
        with self._lock:
            if record.get("cancel_requested"):
                status = "cancelled"
            else:
                status = "done" if code == 0 else "failed"
            record.update(status=status, exit_code=code, finished=now(), prompt=None)
            self._write(record)
            self.active.pop(job_id, None)
        self.emit("job.status", {"job": self.public(record)})

    # ---------- interaction ----------
    def answer(self, job_id, answer) -> dict:
        self.accounts.require()
        if answer not in ("y", "n"):
            raise EngineError("bad_request", 'answer must be "y" or "n"')
        with self._lock:
            entry = self.active.get(job_id)
            if entry is None:
                self._load(job_id)
                raise EngineError("conflict", "Job is not running in this session")
            record = entry["record"]
            if record["status"] != "waiting_input":
                raise EngineError("conflict", "Job is not waiting for an answer")
            try:
                entry["process"].stdin.write((answer + "\n").encode())
                entry["process"].stdin.flush()
            except OSError:
                raise EngineError("conflict", "Job has closed its input") from None
            record.update(status="running", prompt=None)
            self._write(record)
        self._append(job_id, "> " + answer.upper())
        self.emit("job.status", {"job": self.public(record)})
        return {"ok": True}

    def cancel(self, job_id) -> dict:
        self.accounts.require()
        with self._lock:
            entry = self.active.get(job_id)
            if entry is None:
                record = self._load(job_id)
                if record["status"] in FINAL:
                    return {"ok": True}
                raise EngineError("conflict", "Job is not running in this session")
            record = entry["record"]
            process: subprocess.Popen = entry["process"]
            if record.get("live"):
                if record["status"] != "waiting_input":
                    raise EngineError("conflict", "Live mail jobs cannot be cancelled mid-delivery")
                # Before delivery starts, declining the CLI's own prompt is the safe stop.
                record["cancel_requested"] = True
                self._write(record)
                try:
                    process.stdin.write(b"n\n")
                    process.stdin.flush()
                except OSError:
                    pass
                return {"ok": True}
            record["cancel_requested"] = True
            self._write(record)
            process.terminate()
        return {"ok": True}

    def shutdown(self) -> None:
        with self._lock:
            for entry in self.active.values():
                if not entry["record"].get("live"):
                    try:
                        entry["process"].terminate()
                    except OSError:
                        pass
