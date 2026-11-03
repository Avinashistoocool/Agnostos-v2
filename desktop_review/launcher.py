"""Native Qt Windows launcher; subprocess mode runs the existing v2 CLI."""
from __future__ import annotations

import os
from pathlib import Path
import sys
from datetime import datetime, timezone
import hashlib
import hmac
import json
from desktop_review.storage import ReviewError, Workspace


def config_dir() -> Path:
    base = os.getenv("LOCALAPPDATA")
    if not base:
        raise RuntimeError("LOCALAPPDATA is required for the Windows desktop app")
    return Path(base) / "Agnostos-v2-Review"


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args and args[0] == "--cli":
        if getattr(sys, "frozen", False):
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(
                Path(sys._MEIPASS) / "playwright-browsers")
        from outreach.locks import AlreadyRunning, InstanceLock
        root = os.getenv("AGNOSTOS_DESKTOP_WORKSPACE", "")
        nonce = os.getenv("AGNOSTOS_DESKTOP_JOB_NONCE", "")
        result = Path(os.getenv("AGNOSTOS_DESKTOP_JOB_RESULT", "")).resolve()
        config = Path(os.getenv("AGNOSTOS_DESKTOP_CONFIG_DIR", "")).resolve()
        if not nonce or len(nonce) < 20 or not result.is_relative_to(config) \
                or not result.name.endswith(".result.json"):
            return 3
        workspace = Workspace.validate(root)
        if Path.cwd().resolve() != workspace:
            return 3
        from desktop_review.commands import build_argv
        try:
            specification = json.loads(os.environ["AGNOSTOS_DESKTOP_JOB_SPEC"])
            if not isinstance(specification, dict) or set(specification) != {
                "command", "options", "confirmation"
            }:
                return 3
            job_id = result.name.removesuffix(".result.json")
            if len(job_id) != 24 or any(ch not in "0123456789abcdef" for ch in job_id):
                return 3
            record = json.loads((result.parent / f"{job_id}.json").read_text(encoding="utf-8"))
            if not hmac.compare_digest(
                record["nonce_hash"], hashlib.sha256(nonce.encode()).hexdigest()
            ) or record["workspace"] != str(workspace) or any(
                record[key] != specification[key] for key in specification
            ):
                return 3
            checked = Workspace(config)
            checked.path = workspace
            validated, _ = build_argv(checked, specification["command"],
                                      specification["options"], specification["confirmation"])
            if record["argv"] != validated or args[1:] != validated:
                return 3
        except (KeyError, ValueError, OSError, TypeError, ReviewError):
            return 3
        from outreach.cli import main as cli_main
        try:
            with InstanceLock(workspace / "output" / ".desktop_cli.lock"):
                code = cli_main(args[1:])
        except AlreadyRunning:
            print("A desktop CLI job is already running in this workspace.")
            code = 3
        result.write_text(json.dumps({
            "status": "done" if code == 0 else "failed", "exit_code": code,
            "finished": datetime.now(timezone.utc).isoformat()}), encoding="utf-8")
        return code
    if args not in ([], ["--health-check"]):
        raise ValueError("Only --health-check is supported")
    from desktop_review.native import DesktopWindow, launch
    workspace = Workspace(config_dir())
    if args:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        from PySide6.QtWidgets import QApplication
        app = QApplication([])
        window = DesktopWindow(workspace)
        window.close()
        return 0
    return launch(workspace)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        if os.name == "nt":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, str(exc), "Agnostos review could not start", 0x10)
        raise
