"""Persisted, strictly scoped CLI jobs; GUI never imports the pipeline engine."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import threading

from .commands import build_argv
from .settings import SettingsStore
from .storage import ReviewError, Workspace
from outreach.queue_store import lock_held


def _alive(pid: int) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        api = ctypes.WinDLL("kernel32", use_last_error=True)
        api.OpenProcess.argtypes = (ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong)
        api.OpenProcess.restype = ctypes.c_void_p
        api.GetExitCodeProcess.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong))
        api.CloseHandle.argtypes = (ctypes.c_void_p,)
        handle = api.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            return bool(api.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
        finally:
            api.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


class Jobs:
    def __init__(self, workspace: Workspace):
        self.workspace = workspace
        self.settings = SettingsStore(workspace)
        self._lock = threading.RLock()
        self.process: subprocess.Popen | None = None
        self.active_id: str | None = None

    def _dir(self) -> Path:
        path = self.settings._dir() / "jobs"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _file(self, job_id: str, suffix: str) -> Path:
        if len(job_id) != 24 or any(ch not in "0123456789abcdef" for ch in job_id):
            raise ReviewError(400, "Invalid job ID")
        return self._dir() / (job_id + suffix)

    def _record(self, job_id: str) -> dict:
        try:
            item = json.loads(self._file(job_id, ".json").read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise ReviewError(404, "Job not found") from None
        if item.get("status") == "running" and (self.active_id != job_id or
                                                 self.process is None):
            result = self._file(job_id, ".result.json")
            if result.exists():
                item.update(json.loads(result.read_text(encoding="utf-8")))
            elif _alive(item.get("pid")):
                item["status"] = "detached"
            else:
                item["status"] = "interrupted"
        elif item.get("status") == "detached" and not _alive(item.get("pid")):
            result = self._file(job_id, ".result.json")
            item.update(json.loads(result.read_text(encoding="utf-8"))
                        if result.exists() else {"status": "interrupted"})
        return item

    def _write(self, job_id: str, item: dict) -> None:
        target = self._file(job_id, ".json")
        pending = target.with_suffix(".json.new")
        pending.write_text(json.dumps(item, ensure_ascii=False), encoding="utf-8")
        os.replace(pending, target)

    def list(self) -> list[dict]:
        with self._lock:
            items = [self._record(path.stem) for path in self._dir().glob("*.json")
                     if len(path.stem) == 24]
            return sorted(items, key=lambda row: row["started"], reverse=True)[:50]

    def get(self, job_id: str) -> dict:
        with self._lock:
            return self._record(job_id)

    def log(self, job_id: str) -> str:
        path = self._file(job_id, ".log")
        self._record(job_id)
        if not path.exists():
            return ""
        with path.open("rb") as stream:
            stream.seek(max(0, path.stat().st_size - 24000))
            return stream.read().decode("utf-8", errors="replace")

    def start(self, command: str, options: dict, confirmation: str | None) -> dict:
        with self._lock:
            argv, live = build_argv(self.workspace, command, options, confirmation)
            if self.process is not None and self.process.poll() is None:
                raise ReviewError(409, "Wait for the current desktop job to finish")
            if any(row["status"] == "detached" for row in self.list()):
                raise ReviewError(409, "An earlier desktop job is still running; wait for it to finish")
            root = self.workspace.path
            if command not in {"stats", "profile", "models", "tls-check"} and any(
                lock_held(root / "output" / filename)
                for filename in (".send.lock", ".resend.lock", ".replies.lock")
            ):
                raise ReviewError(409, "A scheduled live mail job is active; retry when it finishes")
            if lock_held(root / "output" / ".desktop_cli.lock"):
                raise ReviewError(409, "Another desktop CLI job is active in this workspace")
            job_id = secrets.token_hex(12)
            environment = self.settings.job_environment()
            if live and options.get("limit") is not None:
                configured_cap = int(environment[
                    "RESEND_DAILY_CAP" if command in {"resend", "legacy", "legacy-researchers"}
                    else "DAILY_SEND_CAP"])
                if options["limit"] > configured_cap:
                    raise ReviewError(400, f"Live limit cannot exceed configured cap of {configured_cap}")
            environment["AGNOSTOS_ENV_FILE"] = str(root / ".env")
            environment["AGNOSTOS_DESKTOP_WORKSPACE"] = str(root)
            environment["AGNOSTOS_DESKTOP_JOB_RESULT"] = str(self._file(job_id, ".result.json"))
            environment["AGNOSTOS_DESKTOP_CONFIG_DIR"] = str(self.workspace.config_dir)
            nonce = secrets.token_urlsafe(24)
            environment["AGNOSTOS_DESKTOP_JOB_NONCE"] = nonce
            environment["AGNOSTOS_DESKTOP_JOB_SPEC"] = json.dumps({
                "command": command, "options": options, "confirmation": confirmation,
            }, separators=(",", ":"), ensure_ascii=False)
            if not getattr(sys, "frozen", False):
                environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
            command_line = ([sys.executable, "--cli", *argv] if getattr(sys, "frozen", False)
                            else [sys.executable, "-m", "desktop_review.launcher", "--cli", *argv])
            record = {"id": job_id, "command": command, "options": options,
                      "confirmation": confirmation, "argv": argv,
                      "nonce_hash": hashlib.sha256(nonce.encode()).hexdigest(),
                      "workspace": str(root), "live": live, "status": "running",
                      "started": datetime.now(timezone.utc).isoformat(),
                      "pid": None, "exit_code": None}
            self._write(job_id, record)
            log_handle = self._file(job_id, ".log").open("w", encoding="utf-8")
            try:
                self.process = subprocess.Popen(
                    command_line, cwd=root, env=environment,
                    stdin=subprocess.PIPE, stdout=log_handle, stderr=subprocess.STDOUT,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            except OSError as exc:
                log_handle.close()
                record["status"] = "failed"
                self._write(job_id, record)
                raise ReviewError(503, f"Could not start CLI: {type(exc).__name__}") from exc
            self.active_id = job_id
            record["pid"] = self.process.pid
            self._write(job_id, record)

            def reap(process: subprocess.Popen, id_: str):
                code = process.wait()
                if process.stdin:
                    process.stdin.close()
                log_handle.close()
                with self._lock:
                    item = self._record(id_)
                    item.update(status="cancelled" if item.get("cancel_requested") else
                                "done" if code == 0 else "failed",
                                exit_code=code, finished=datetime.now(timezone.utc).isoformat())
                    self._write(id_, item)
                    if self.active_id == id_:
                        self.active_id = None
                        self.process = None

            threading.Thread(target=reap, args=(self.process, job_id), daemon=True).start()
            return record

    def input(self, job_id: str, choice: str) -> dict:
        if choice not in ("yes", "no"):
            raise ReviewError(400, "Only yes or no may be entered at a CLI prompt")
        with self._lock:
            if self.active_id != job_id or self.process is None or self.process.poll() is not None:
                raise ReviewError(409, "Job is not awaiting input in this session")
            item = self._record(job_id)
            path = self._file(job_id, ".log")
            with path.open("rb") as stream:
                stream.seek(max(0, path.stat().st_size - 4000))
                offset = stream.tell()
                prompt = stream.read().rfind(b"[Y/N]:")
            if prompt < 0 or offset + prompt <= item.get("last_prompt_offset", -1):
                raise ReviewError(409, "Wait until the CLI prints a new [Y/N] prompt")
            try:
                self.process.stdin.write(("y\n" if choice == "yes" else "n\n").encode())
                self.process.stdin.flush()
            except OSError:
                raise ReviewError(409, "Job has closed its input") from None
            item["last_prompt_offset"] = offset + prompt
            self._write(job_id, item)
            return {"ok": True}

    def cancel(self, job_id: str) -> dict:
        with self._lock:
            item = self._record(job_id)
            if item.get("live"):
                raise ReviewError(409, "Live mail jobs cannot be cancelled mid-delivery")
            if self.active_id != job_id or self.process is None or self.process.poll() is not None:
                raise ReviewError(409, "Job is no longer active in this session")
            item["cancel_requested"] = True
            self._write(job_id, item)
            self.process.terminate()
            return {"ok": True}
