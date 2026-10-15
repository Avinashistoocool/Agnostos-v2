"""Read each professor's full conversation over IMAP and draft a follow-up reply."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path

from .humanize import deslop
from .replies import ReplyChecker, _decode, _sent_date, _snippet, _text, classify

REPLY_SYSTEM = """You help an undergraduate student continue email conversations with professors they cold-emailed about a {position}.

APPLICANT PROFILE
{profile}

Availability: {availability}

You get the whole thread, oldest first. Decide what the student should do next:
- "reply": the professor asked something, showed interest, suggested someone else, asked for a CV/transcript/call, or left a door open. Draft the reply.
- "thank": a polite decline. Draft a SHORT (40-70 words) gracious thank-you that asks one light question only if natural (e.g. whether they know a colleague or programme that takes summer students, or whether to write again next year). Never argue or plead.
- "none": nothing worth sending (auto-reply, bounce, or the student already replied last and is waiting).

RULES
- Answer every direct question in the latest professor message. Do not invent facts, grades, dates, or results not in the profile; if something is unknown, write [FILL: what is needed].
- Same honest, modest voice as a real second-year student: plain words, contractions fine, no em dashes, no markdown, no bullet lists, no "I am writing to", "delve", "leverage", "thrilled", "invaluable".
- Start with a salutation using how the professor signed off or "Dear Professor <Surname>". End with a short sign-off and the student's first name; the signature is added automatically.
- Keep replies under 150 words.

Return only JSON: {{"action": "reply|thank|none", "summary": "<one line on where the conversation stands>", "body": "<email body or empty>"}}"""


@dataclass
class Message:
    when: datetime | None
    sender: str            # "student" | "professor" | "system"
    subject: str
    text: str
    message_id: str = ""
    kind: str = ""


@dataclass
class Thread:
    row: dict
    messages: list[Message] = field(default_factory=list)

    @property
    def last_incoming(self) -> Message | None:
        return next((m for m in reversed(self.messages) if m.sender == "professor"), None)

    def awaiting_us(self) -> bool:
        """True if the professor wrote last."""
        return bool(self.messages) and self.messages[-1].sender == "professor"

    def render(self, limit: int = 6000) -> str:
        out = []
        for m in self.messages:
            stamp = f"{m.when:%d %b %Y %H:%M}" if m.when else ""
            who = "STUDENT" if m.sender == "student" else "PROFESSOR"
            out.append(f"--- {who} {stamp} | {m.subject}\n{m.text.strip()}")
        text = "\n\n".join(out)
        return text[-limit:]


def _when(msg) -> datetime | None:
    try:
        return parsedate_to_datetime(msg.get("Date")).astimezone().replace(tzinfo=None)
    except Exception:
        return None


def _body(msg, quoted: bool) -> str:
    raw = _text(msg, limit=8000)
    if quoted:
        return raw
    # Strip quoted history; it's already in the thread as earlier messages.
    lines = []
    for line in raw.splitlines():
        s = line.strip()
        if s.startswith(">") or s.startswith("-----Original") or \
                (s.startswith("On ") and s.endswith("wrote:")) or \
                (s.startswith("Le ") and s.endswith("a écrit :")):
            break
        lines.append(line)
    return "\n".join(lines).strip() or _snippet(raw)


class ThreadReader(ReplyChecker):
    """Pull every message to/from each professor, including our own Sent copies."""

    def _all_folders(self) -> list[tuple[str, str]]:
        typ, data = self.conn.list()
        found = []
        for raw in data or []:
            line = raw.decode(errors="replace")
            name = line.rsplit(" ", 1)[-1].strip('"')
            if "\\Sent" in line:
                found.append((name, "sent"))
            elif "\\Trash" in line or "\\Drafts" in line:
                continue
            elif name in self.folders:
                found.append((name, "in"))
        return found

    def threads(self, rows: list[dict], progress=None) -> list[Thread]:
        earliest = min((d for d in (_sent_date(r) for r in rows) if d), default=None) \
            or datetime.now() - timedelta(days=60)
        since = (earliest - timedelta(days=1)).strftime("%d-%b-%Y")
        threads = {(r["sheet"], r["row"]): Thread(r) for r in rows}
        seen: set[str] = set()
        for folder, kind in self._all_folders():
            if self.conn.select(f'"{folder}"', readonly=True)[0] != "OK":
                continue
            for n, row in enumerate(rows, 1):
                if progress:
                    progress(folder, n, len(rows), row)
                crit = ("TO" if kind == "sent" else "FROM")
                nums = set(self._search("SINCE", since, crit, f'"{row["email"]}"'))
                if row.get("message_id"):
                    nums |= set(self._search("SINCE", since, "HEADER", "References",
                                             f'"{row["message_id"]}"'))
                for num in nums:
                    msg = self._fetch(num)
                    if msg is None:
                        continue
                    mid = (msg.get("Message-ID") or "").strip()
                    if mid and mid in seen:
                        continue
                    seen.add(mid)
                    frm = parseaddr(msg.get("From", ""))[1].lower()
                    mine = frm == (self.s.smtp_from or self.user).lower()
                    k = "" if mine else classify(msg)
                    threads[(row["sheet"], row["row"])].messages.append(Message(
                        when=_when(msg), sender="student" if mine else
                        ("system" if k == "bounced" else "professor"),
                        subject=_decode(msg.get("Subject"))[:200],
                        text=_body(msg, quoted=False), message_id=mid, kind=k))
        out = []
        for t in threads.values():
            # The workbook knows the original outreach even if Sent has no copy.
            if not any(m.sender == "student" for m in t.messages):
                t.messages.append(Message(when=_sent_date(t.row), sender="student",
                                          subject=t.row.get("subject", ""),
                                          text=t.row.get("body", ""),
                                          message_id=t.row.get("message_id", "")))
            t.messages.sort(key=lambda m: m.when or datetime.min)
            out.append(t)
        return out


def draft_reply(evaluator, thread: Thread, settings, profile) -> dict:
    system = REPLY_SYSTEM.format(position=settings.position, profile=profile.summary_block(),
                                 availability=settings.availability)
    row = thread.row
    user = (f"Professor: {row.get('name')} <{row['email']}>, {row.get('institution', '')}\n\n"
            f"THREAD (oldest first):\n{thread.render()}")
    data = evaluator.chat_json(system, user)
    action = str(data.get("action", "none")).lower()
    body = deslop(str(data.get("body", "")).strip()) if action != "none" else ""
    return {"action": action if action in {"reply", "thank", "none"} else "none",
            "summary": str(data.get("summary", "")).strip()[:300], "body": body}


def save_queue(path: Path, items: list[dict]) -> None:
    path.write_text(json.dumps(items, indent=2, default=str, ensure_ascii=False),
                    encoding="utf-8")


def load_queue(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))
