"""Reply tracking over IMAP: who answered, who auto-replied, which addresses bounced."""
from __future__ import annotations

import email
import imaplib
import re
import ssl
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.header import decode_header, make_header
from email.utils import parseaddr, parsedate_to_datetime

from .config import Settings

AUTO_RE = re.compile(
    r"out of (the )?office|automatic reply|auto[- ]?reply|autoreply|abwesenheit|"
    r"absence|on leave|vacation|away from|r[ée]ponse automatique|"
    r"risposta automatica|respuesta autom[áa]tica|afwezig|frånvaro", re.I)
BOUNCE_FROM_RE = re.compile(r"mailer-daemon|postmaster|mail delivery", re.I)

# Strongest first: a later, weaker match never overwrites a stronger one.
RANK = {"": 0, "bounced": 1, "auto-reply": 2, "replied": 3}


@dataclass
class Reply:
    kind: str           # replied | auto-reply | bounced
    when: datetime | None
    subject: str
    snippet: str

    def status(self) -> str:
        stamp = self.when.strftime("%Y-%m-%d %H:%M") if self.when else ""
        return f"{self.kind} {stamp}".strip()


def _decode(value) -> str:
    try:
        return str(make_header(decode_header(value or "")))
    except Exception:
        return str(value or "")


def _text(msg: email.message.Message, limit: int = 4000) -> str:
    parts = msg.walk() if msg.is_multipart() else [msg]
    for part in parts:
        if part.get_content_type() == "text/plain" and not part.get_filename():
            try:
                raw = part.get_payload(decode=True) or b""
                return raw.decode(part.get_content_charset() or "utf-8", "replace")[:limit]
            except Exception:
                continue
    return ""


def _snippet(body: str) -> str:
    lines = []
    for line in body.splitlines():
        s = line.strip()
        if s.startswith(">") or re.match(r"^(On .+ wrote:|-----Original|From: )", s):
            break
        if s:
            lines.append(s)
    return " ".join(lines)[:300]


def classify(msg: email.message.Message) -> str:
    sender = parseaddr(msg.get("From", ""))[1]
    subject = _decode(msg.get("Subject"))
    if BOUNCE_FROM_RE.search(sender) or BOUNCE_FROM_RE.search(msg.get("From", "")) \
            or re.search(r"undeliver|delivery status notification|returned mail|"
                         r"delivery (has )?failed|failure notice", subject, re.I):
        return "bounced"
    auto = (msg.get("Auto-Submitted", "no").lower() not in {"", "no"}
            or msg.get("X-Autoreply") or msg.get("X-Autorespond")
            or (msg.get("Precedence", "").lower() in {"auto_reply", "bulk", "junk"}))
    if auto or AUTO_RE.search(subject):
        return "auto-reply"
    return "replied"


class ReplyChecker:
    def __init__(self, settings: Settings):
        self.s = settings
        self.host = settings.imap_host or re.sub(r"^smtp\.", "imap.", settings.smtp_host)
        self.user = settings.imap_user or settings.smtp_user
        self.password = settings.imap_password or settings.smtp_password
        self.conn: imaplib.IMAP4 | None = None
        self.folders: list[str] = []

    def __enter__(self):
        from .tls import context
        ctx = context()
        self.conn = imaplib.IMAP4_SSL(self.host, self.s.imap_port, ssl_context=ctx,
                                      timeout=60)
        self.conn.login(self.user, self.password)
        typ, data = self.conn.list()
        existing = set()
        for raw in data or []:
            line = raw.decode(errors="replace")
            m = re.search(r'"[^"]*"\s+"?([^"]+)"?$', line) or re.search(r"\s(\S+)$", line)
            if m:
                existing.add(m.group(1))
        wanted = [f.strip() for f in self.s.imap_folders.split(";") if f.strip()]
        self.folders = [f for f in wanted if f in existing] or ["INBOX"]
        return self

    def __exit__(self, *_exc):
        if self.conn:
            try:
                self.conn.logout()
            except Exception:
                pass

    def _search(self, *criteria: str) -> list[bytes]:
        typ, data = self.conn.search(None, *criteria)
        return data[0].split() if typ == "OK" and data and data[0] else []

    def _fetch(self, num: bytes) -> email.message.Message | None:
        typ, data = self.conn.fetch(num, "(BODY.PEEK[])")
        for item in data or []:
            if isinstance(item, tuple):
                return email.message_from_bytes(item[1])
        return None

    def check(self, rows: list[dict], progress=None) -> dict[tuple, Reply]:
        """Best reply per (sheet, row) for rows that were actually sent."""
        found: dict[tuple, Reply] = {}
        if not rows:
            return found
        earliest = min((_sent_date(r) for r in rows), default=None) or \
            datetime.now() - timedelta(days=60)
        since = (earliest - timedelta(days=1)).strftime("%d-%b-%Y")
        by_addr = {r["email"].lower(): r for r in rows}

        def offer(row, reply):
            key = (row["sheet"], row["row"])
            if RANK[reply.kind] > RANK[found[key].kind if key in found else ""]:
                found[key] = reply

        for folder in self.folders:
            typ, _ = self.conn.select(f'"{folder}"', readonly=True)
            if typ != "OK":
                continue
            for n, row in enumerate(rows, 1):
                if progress:
                    progress(folder, n, len(rows), row)
                nums = set(self._search("SINCE", since, "FROM", f'"{row["email"]}"'))
                if row.get("message_id"):
                    for hdr in ("In-Reply-To", "References"):
                        nums |= set(self._search("SINCE", since, "HEADER", hdr,
                                                 f'"{row["message_id"]}"'))
                for num in nums:
                    msg = self._fetch(num)
                    if msg is None:
                        continue
                    offer(row, _reply(msg, classify(msg)))
            # Bounces come from the server, not the professor: match on the
            # failed address quoted inside the notice.
            for num in self._search("SINCE", since, "OR", "FROM", '"mailer-daemon"',
                                    "FROM", '"postmaster"'):
                msg = self._fetch(num)
                if msg is None:
                    continue
                try:
                    blob = msg.as_string().lower()
                except Exception:
                    blob = str(msg.get_payload()).lower()
                for addr, row in by_addr.items():
                    if addr in blob:
                        offer(row, _reply(msg, "bounced"))
        return found


def _reply(msg, kind: str) -> Reply:
    try:
        when = parsedate_to_datetime(msg.get("Date")).astimezone().replace(tzinfo=None)
    except Exception:
        when = None
    return Reply(kind=kind, when=when, subject=_decode(msg.get("Subject"))[:200],
                 snippet=_snippet(_text(msg)) if kind != "bounced" else "")


def _sent_date(row: dict) -> datetime | None:
    try:
        return datetime.strptime(row.get("sent_at", "")[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
