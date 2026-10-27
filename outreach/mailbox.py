"""Mailbox helpers: put copies of what we sent into the IMAP Sent folder.

Mail sent straight over SMTP never appears in Sent, so a mail app shows the
professor's answer without the email it answers. Appending a copy (same
Message-ID and Date) makes every thread complete in Outlook/Thunderbird/web.
"""
from __future__ import annotations

import imaplib
import re
from datetime import datetime
from email.message import EmailMessage

from .config import Settings


def _is_gmail(host: str) -> bool:
    return "gmail" in (host or "").lower() or "googlemail" in (host or "").lower()


def find_folder(conn: imaplib.IMAP4, flag: str, fallback: str) -> str:
    """Folder name carrying an IMAP special-use flag (\\Sent, \\Junk), e.g. "[Gmail]/Sent Mail"."""
    typ, data = conn.list()
    for raw in data or []:
        line = raw.decode(errors="replace")
        if flag.lower() in line.lower():
            m = re.search(r'"(?:[^"\\]|\\.)*"\s+"?(.+?)"?$', line)
            if m:
                return m.group(1)
    return fallback


class SentArchiver:
    """APPEND sent messages to the account's Sent folder, skipping duplicates."""

    def __init__(self, settings: Settings):
        self.s = settings
        self.host = settings.imap_host or re.sub(r"^smtp\.", "imap.", settings.smtp_host)
        self.user = settings.imap_user or settings.smtp_user
        self.password = settings.imap_password or settings.smtp_password
        self.conn: imaplib.IMAP4 | None = None
        self.folder = "Sent"

    def __enter__(self):
        from .tls import context
        self.conn = imaplib.IMAP4_SSL(self.host, self.s.imap_port, ssl_context=context(),
                                      timeout=60)
        self.conn.login(self.user, self.password)
        self.folder = find_folder(self.conn, "\\Sent", "Sent")
        self.conn.select(f'"{self.folder}"', readonly=True)
        return self

    def __exit__(self, *_exc):
        if self.conn:
            try:
                self.conn.logout()
            except Exception:
                pass

    def has(self, message_id: str) -> bool:
        if not message_id:
            return False
        typ, data = self.conn.search(None, "HEADER", "Message-ID", f'"{message_id.strip("<>")}"')
        return typ == "OK" and bool(data and data[0])

    def append(self, msg: EmailMessage, when: datetime | None = None) -> bool:
        """True if appended, False if it was already there."""
        if self.has(msg.get("Message-ID", "")):
            return False
        stamp = imaplib.Time2Internaldate((when or datetime.now()).timestamp())
        typ, data = self.conn.append(f'"{self.folder}"', "(\\Seen)", stamp, msg.as_bytes())
        if typ != "OK":
            raise RuntimeError(f"IMAP APPEND failed: {data!r}")
        return True


def save_copy(settings: Settings, msg: EmailMessage) -> None:
    """Best-effort: copy one just-sent message into Sent. Gmail does this itself."""
    if not settings.save_to_sent or _is_gmail(settings.smtp_host):
        return
    with SentArchiver(settings) as arc:
        arc.append(msg)
