"""Exercise the frozen CLI against an isolated workbook, never live mail."""
from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys

from openpyxl import Workbook
from desktop_review.commands import build_argv
from desktop_review.storage import Workspace

ROOT = Path(__file__).resolve().parents[1]


def main(executable: Path) -> None:
    scratch = ROOT / "build" / "packaged-cli-smoke"
    if scratch.exists():
        shutil.rmtree(scratch)
    workspace = scratch / "workspace"
    output = workspace / "output"
    output.mkdir(parents=True)
    (workspace / "outreach").mkdir()
    (workspace / "outreach" / "cli.py").write_text("# workspace marker", encoding="utf-8")
    book = Workbook()
    book.active.append(["Professor Name", "Email Address", "Custom Email Draft", "Send Status"])
    book.active.append(["Fixture", "fixture@example.org", "Draft", ""])
    book.save(output / "professors.xlsx")
    book.close()
    config = scratch / "appdata" / "Agnostos-v2-Review"
    config.mkdir(parents=True)
    chosen = Workspace(config)
    chosen.select(str(workspace))

    def run(command: str, options: dict, job_id: str) -> None:
        nonce = "test-only-nonce-for-offline-health"
        result = config / "jobs" / (job_id + ".result.json")
        result.parent.mkdir(parents=True, exist_ok=True)
        argv, live = build_argv(chosen, command, options)
        (result.parent / (job_id + ".json")).write_text(json.dumps({
            "id": job_id, "command": command, "options": options,
            "confirmation": None, "argv": argv, "workspace": str(workspace),
            "nonce_hash": hashlib.sha256(nonce.encode()).hexdigest(),
            "live": live,
        }), encoding="utf-8")
        env = dict(os.environ, LOCALAPPDATA=str(scratch / "appdata"),
                   AGNOSTOS_DESKTOP_CONFIG_DIR=str(config),
                   AGNOSTOS_DESKTOP_WORKSPACE=str(workspace),
                   AGNOSTOS_DESKTOP_JOB_RESULT=str(result),
                   AGNOSTOS_DESKTOP_JOB_NONCE=nonce,
                   AGNOSTOS_DESKTOP_JOB_SPEC=json.dumps({
                       "command": command, "options": options, "confirmation": None}),
                   AGNOSTOS_ENV_FILE=str(workspace / ".env"), OUTPUT_DIR=str(output),
                   TARGET_XLSX=str(output / "professors.xlsx"), PYTHONUNBUFFERED="1")
        env.pop("PYTHONPATH", None)
        completed = subprocess.run(
            [str(executable.resolve()), "--cli", *argv],
            cwd=workspace, env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, timeout=90)
        assert completed.returncode == 0, (command, completed.returncode, completed.stdout[-1000:])
        assert completed.stdout.strip(), f"Frozen {command} produced no job log output"
        assert result.exists() and json.loads(result.read_text(encoding="utf-8"))["status"] == "done"

    try:
        run("stats", {}, "a" * 24)
        resume = workspace / "resume.pdf"
        shutil.copyfile(ROOT / "tests" / "fixtures" / "sample_resume.pdf", resume)
        run("profile", {"resume": str(resume)}, "b" * 24)
        assert (output / "professors.xlsx").exists()
        assert not (workspace / ".env").exists()
        print("Frozen CLI stats and profile completed against isolated fixtures.")
    finally:
        shutil.rmtree(scratch)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
