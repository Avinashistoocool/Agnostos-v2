"""Unconfigured resume paths must not be mistaken for an unsupported format."""
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from outreach.config import ConfigError, _require_file
from outreach.resume_parser import parse_resume

for empty in ("", Path(".")):
    try:
        _require_file(empty, "RESUME_PATH", "resume PDF or DOCX")
    except ConfigError as exc:
        assert "not set" in str(exc)
    else:
        raise AssertionError("Blank RESUME_PATH accepted as the current directory")

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
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
