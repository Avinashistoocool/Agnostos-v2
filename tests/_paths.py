"""Resolve test inputs.

Prefer the operator's real resume/workbook when `.env` points at files that
exist, otherwise fall back to the synthetic fixtures so a fresh clone can run
the suites without any configuration.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures"
FIXTURE_RESUME = FIXTURES / "sample_resume.pdf"
FIXTURE_XLSX = FIXTURES / "sample_targets.xlsx"


def _ensure_fixtures() -> None:
    if FIXTURE_RESUME.exists() and FIXTURE_XLSX.exists():
        return
    subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parent / "make_fixtures.py")],
        check=True,
    )


def _pick(configured: Path | None, fallback: Path) -> Path:
    if configured is not None and str(configured) not in ("", ".") and Path(configured).is_file():
        return Path(configured)
    _ensure_fixtures()
    return fallback


def resume_path(settings) -> Path:
    return _pick(settings.resume_path, FIXTURE_RESUME)


def target_xlsx(settings) -> Path:
    return _pick(settings.target_xlsx, FIXTURE_XLSX)


def using_fixtures(settings) -> bool:
    return target_xlsx(settings) == FIXTURE_XLSX
