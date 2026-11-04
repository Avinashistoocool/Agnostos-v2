"""Child-process entry points: validated CLI job worker and connection probes."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import sys

NONCE_MIN = 24


def _utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        except (AttributeError, ValueError):
            pass


def validate_job(args: list[str]) -> tuple[Path, Path] | None:
    """Return (workspace, job file) only if this exact argv was approved by the engine."""
    from desktop_review.commands import build_argv
    from desktop_review.storage import ReviewError
    from .accounts import EngineWorkspace
    from .errors import EngineError

    nonce = os.environ.get("AGNOSTOS_ENGINE_JOB_NONCE", "")
    job_file = Path(os.environ.get("AGNOSTOS_ENGINE_JOB_FILE", "") or ".").resolve()
    user_dir = Path(os.environ.get("AGNOSTOS_ENGINE_USER_DIR", "") or ".").resolve()
    if len(nonce) < NONCE_MIN or not job_file.is_file() \
            or job_file.parent != (user_dir / "jobs") or job_file.suffix != ".json":
        return None
    job_id = job_file.stem
    if len(job_id) != 24 or any(ch not in "0123456789abcdef" for ch in job_id):
        return None
    try:
        record = json.loads(job_file.read_text(encoding="utf-8"))
        if not hmac.compare_digest(record["nonce_hash"], hashlib.sha256(nonce.encode()).hexdigest()):
            return None
        if record.get("id") != job_id or record.get("status") != "running" \
                or job_file.with_name(job_id + ".result.json").exists():
            return None
        workspace = EngineWorkspace(Path(record["workspace"]), user_dir)
        if Path.cwd().resolve() != workspace.path:
            return None
        argv, _live = build_argv(workspace, record["command"], record["options"],
                                 record.get("confirmation"))
        if argv != record["argv"] or args != argv:
            return None
    except (KeyError, ValueError, OSError, TypeError, ReviewError, EngineError):
        return None
    return workspace.path, job_file


def ensure_default_workbook(args: list[str]) -> Path | None:
    """With no --xlsx given, start a fresh empty professor workbook if none exists yet."""
    if "--xlsx" in args or not args or args[0] == "discover":
        return None
    target = os.environ.get("TARGET_XLSX", "").strip()
    if not target:
        return None
    path = Path(target)
    if path.exists():
        return None
    from outreach.excel_io import write_new_workbook
    write_new_workbook(path, [])
    print(f" Created a new, empty professor workbook: {path.name}")
    if args[0] == "run" and "scrape" not in args:
        print(" It has no professors yet. Run \"Find professors\" (Discover) first to fill it.")
    return path


def run_worker(args: list[str]) -> int:
    _utf8_stdio()
    checked = validate_job(args)
    if checked is None:
        print("Refusing to run: this job was not approved by the Agnostos engine.")
        return 3
    workspace, job_file = checked
    if getattr(sys, "frozen", False) and "--mode" in args \
            and args[args.index("--mode") + 1:args.index("--mode") + 2] == ["scrape"]:
        print("Scrape mode needs a browser (Playwright + Chromium), which the desktop app does "
              "not bundle. Use list mode with a workbook, or run `agnostos run --mode scrape` "
              "from a source checkout.")
        return 2
    from outreach.locks import AlreadyRunning, InstanceLock
    from outreach.cli import main as cli_main
    try:
        with InstanceLock(workspace / "output" / ".desktop_cli.lock"):
            ensure_default_workbook(args)
            code = cli_main(args)
    except AlreadyRunning:
        print("Another desktop CLI job is already running in this workspace.")
        code = 3
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
    result = job_file.with_name(job_file.stem + ".result.json")
    result.write_text(json.dumps({
        "status": "done" if code == 0 else "failed", "exit_code": code,
        "finished": datetime.now(timezone.utc).isoformat(timespec="seconds")}), encoding="utf-8")
    return code


def _probe(kind: str) -> dict:
    from outreach.config import settings
    if kind == "smtp":
        from outreach.mailer import Mailer
        if not settings.smtp_host:
            return {"ok": False, "detail": "SMTP host is not set"}
        mailer = Mailer(settings, dry_run=False)
        try:
            mailer.connect()  # connects and logs in only; nothing is sent
        finally:
            mailer.close()
        how = "Gmail (XOAUTH2)" if settings.smtp_auth == "xoauth2" else settings.smtp_host
        return {"ok": True, "detail": f"SMTP login OK via {how} as {settings.smtp_user}"}
    if kind == "imap":
        from outreach.replies import ReplyChecker
        checker = ReplyChecker(settings)
        if not checker.host:
            return {"ok": False, "detail": "IMAP host is not set"}
        with checker:
            folders = ", ".join(checker.folders)
        return {"ok": True, "detail": f"IMAP login OK at {checker.host} ({folders})"}
    if kind == "llm":
        from outreach.llm import list_models
        models = list_models(settings)
        return {"ok": True, "detail": f"Connected to {settings.provider} ({len(models)} models)",
                "models": models[:200]}
    raise ValueError(kind)


def run_probe(args: list[str]) -> int:
    _utf8_stdio()
    if len(args) != 1 or args[0] not in ("smtp", "imap", "llm"):
        return 2
    try:
        result = _probe(args[0])
    except Exception as exc:  # report every failure as a probe result
        detail = str(exc).strip() or type(exc).__name__
        result = {"ok": False, "detail": f"{type(exc).__name__}: {detail}"[:1000]}
    print("\n@@PROBE@@" + json.dumps(result, ensure_ascii=False))
    return 0
