"""Import FIRST in every test that touches `outreach`: the suites must never see the
operator's real .env (SMTP/IMAP logins, real workbook, real CV).

Before this existed, smoke_test [9d] drove `Mailer.send_one` against a fake SMTP
server, and `_archive()` then APPENDed the test message to the real IITD Sent
folder with the .env IMAP login. `python-dotenv` never overrides variables that
are already set, so pinning them here wins over any .env file.
"""
from __future__ import annotations

import os
from pathlib import Path

_EMPTY_ENV = Path(__file__).resolve().parent / "fixtures" / "isolated.env"

BLANK = (
    "SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM", "SMTP_FROM_NAME", "REPLY_TO",
    "IMAP_HOST", "IMAP_USER", "IMAP_PASSWORD",
    "RESEND_SMTP_USER", "RESEND_SMTP_PASSWORD", "RESEND_SMTP_FROM",
    "GOOGLE_OAUTH_TOKEN_FILE", "GOOGLE_CLIENT_SECRET",
    "OPENAI_API_KEY", "GROQ_API_KEY", "OPENAI_BASE_URL",
    "RESUME_PATH", "TARGET_XLSX", "ATTACHMENTS",
)

os.environ["AGNOSTOS_ENV_FILE"] = str(_EMPTY_ENV)
for _key in BLANK:
    os.environ[_key] = ""
os.environ["SAVE_TO_SENT"] = "false"
os.environ["SMTP_AUTH"] = "password"
os.environ["OUTPUT_DIR"] = str(Path(__file__).resolve().parent / "_tmp" / "output")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")


def assert_isolated(settings) -> None:
    assert not settings.save_to_sent, "tests must not copy mail into a real Sent folder"
    assert not settings.imap_password and not settings.smtp_password, "real credentials leaked"
