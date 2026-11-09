"""Unconfigured resume paths must not be mistaken for an unsupported format."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _isolate  # noqa: F401,E402  (must precede outreach imports)

from outreach.config import ConfigError, _require_file
from outreach.resume_parser import parse_resume

for empty in ("", Path(".")):
    try:
        _require_file(empty, "RESUME_PATH", "resume PDF or DOCX")
    except ConfigError as exc:
        assert "missing or still a placeholder" in str(exc)
    else:
        raise AssertionError("Blank RESUME_PATH accepted as the current directory")

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    (root / ".env").write_text("RESUME_PATH=resume.pdf\n", encoding="utf-8")
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    missing_dependency = subprocess.run(
        [sys.executable, "-S", "-c", "import outreach.config"], cwd=root, env=env,
        capture_output=True, text=True)
    assert missing_dependency.returncode != 0
    assert "python-dotenv is required to read .env" in missing_dependency.stderr
    try:
        _require_file(root, "RESUME_PATH", "resume PDF or DOCX")
    except ConfigError as exc:
        assert "not a folder" in str(exc)
    else:
        raise AssertionError("Folder accepted as a resume")
    resume = root / "resume.rtf"
    resume.write_text("Test resume", encoding="utf-8")
    try:
        parse_resume(resume)
    except ValueError as exc:
        assert ".rtf" in str(exc) and "RESUME_PATH" in str(exc)
    else:
        raise AssertionError("Unsupported extension accepted")
print("Resume path error tests passed")
