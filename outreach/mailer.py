"""Email dispatch: SMTP with attachments, throttling, dry-run, and resume safety."""
from __future__ import annotations

import mimetypes
import random
import re
import smtplib
import ssl
import sys
import time
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from pathlib import Path

from .config import Settings
from .resume_parser import ResumeProfile
from .schedule import fmt_duration as _fmt
from .tls import context as tls_context

SIGNATURE = """
--
{name}
{degree}
{institution}
{email}{phone}"""

# Mail servers that reject or drop this many messages in a row are throttling
# or refusing the account; continuing just marks every remaining row failed.
MAX_CONSECUTIVE_FAILURES = 3
CONNECT_ATTEMPTS = 3

_ATTACH_RE = re.compile(r"\battach(?:ed|ing|ment|ments)?\b|\benclos(?:ed|ing)\b|"
                        r"\bplease find my (?:cv|resume|transcript)", re.I)


def mentions_attachment(body: str) -> bool:
    return bool(_ATTACH_RE.search(body or ""))


def build_signature(profile: ResumeProfile) -> str:
    return SIGNATURE.format(
        name=profile.name,
        degree=profile.degree + (f" (expected {profile.graduation_year})" if profile.graduation_year else ""),
        institution=profile.institution,
        email=profile.email,
        phone=f"\n{profile.phone}" if profile.phone else "",
    )


class Mailer:
    def __init__(self, settings: Settings, profile: ResumeProfile | None = None,
                 dry_run: bool = True, redirect_to: str = ""):
        self.s = settings
        self.profile = profile
        self.dry_run = dry_run
        # When set, every message is delivered here instead of the professor.
        self.redirect_to = redirect_to
        self.signature = build_signature(profile) if profile else ""
        self._server: smtplib.SMTP | None = None
        self.sent_count = 0

    # ---------- connection ----------
    def connect(self):
        if self.dry_run:
            return
        missing = [k for k, v in {
            "SMTP_HOST": self.s.smtp_host,
            "SMTP_USER": self.s.smtp_user,
            "SMTP_PASSWORD": self.s.smtp_password,
            "SMTP_FROM": self.s.smtp_from,
        }.items() if not v or "your_" in str(v) or "your-university" in str(v)]
        if missing:
            raise RuntimeError(
                f"SMTP settings still at placeholder values in .env: {', '.join(missing)}")
        # A busy relay sometimes stalls the greeting/login; that is transient,
        # so retry with backoff instead of aborting the whole run.
        for attempt in range(1, CONNECT_ATTEMPTS + 1):
            try:
                self._open()
                return
            except (smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError,
                    TimeoutError, OSError):
                self.close()
                if attempt == CONNECT_ATTEMPTS:
                    raise
                time.sleep(15 * attempt)

    def _open(self):
        context = tls_context()
        timeout = self.s.smtp_timeout
        if self.s.smtp_security.lower() == "ssl":
            self._server = smtplib.SMTP_SSL(self.s.smtp_host, self.s.smtp_port,
                                            context=context, timeout=timeout)
        else:
            self._server = smtplib.SMTP(self.s.smtp_host, self.s.smtp_port, timeout=timeout)
            self._server.ehlo()
            if self.s.smtp_security.lower() == "starttls":
                self._server.starttls(context=context)
                self._server.ehlo()
        self._server.login(self.s.smtp_user, self.s.smtp_password)

    def close(self):
        if self._server:
            try:
                self._server.quit()
            except Exception:
                pass
            self._server = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *_exc):
        self.close()

    def build_reply(self, to_email: str, to_name: str, subject: str, body: str,
                    in_reply_to: str = "", references: str = "") -> EmailMessage:
        """A threaded follow-up: Re: subject, In-Reply-To/References. ATTACHMENTS
        (your CV) are added only when the body says something is attached."""
        # IMAP headers may arrive folded across lines; header values can't contain CR/LF.
        subject, in_reply_to, references, to_name = (
            " ".join(str(v or "").split()) for v in (subject, in_reply_to, references, to_name))
        msg = EmailMessage()
        from_name = self.s.smtp_from_name or (self.profile.name if self.profile else "")
        msg["From"] = formataddr((from_name, self.s.smtp_from)) if from_name else self.s.smtp_from
        msg["To"] = formataddr((to_name, to_email)) if to_name else to_email
        msg["Subject"] = subject if subject.lower().startswith("re:") else f"Re: {subject}"
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid(domain=self.s.smtp_from.rpartition("@")[2] or None)
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
            msg["References"] = " ".join(x for x in (references, in_reply_to) if x).strip()
        if self.s.reply_to:
            msg["Reply-To"] = self.s.reply_to
        msg.set_content(body.rstrip() + "\n" + self.signature)
        if mentions_attachment(body):
            # The draft promises an attachment, so it must actually be there.
            if not self._attach_files(msg):
                raise ValueError("reply says something is attached but no ATTACHMENTS "
                                 "file exists; fix ATTACHMENTS in .env or edit the body")
        return msg

    def _attach_files(self, msg: EmailMessage) -> int:
        n = 0
        for raw_path in self.s.attachments:
            path = Path(raw_path)
            if not path.exists():
                continue
            ctype, _ = mimetypes.guess_type(str(path))
            maintype, _, subtype = (ctype or "application/octet-stream").partition("/")
            msg.add_attachment(path.read_bytes(), maintype=maintype,
                               subtype=subtype, filename=path.name)
            n += 1
        return n

    def deliver(self, msg: EmailMessage) -> None:
        if self.dry_run:
            return
        self._deliver(msg)
        self.sent_count += 1
        self._archive(msg)

    def _archive(self, msg: EmailMessage) -> None:
        """Copy to the IMAP Sent folder so the thread is complete in mail apps."""
        try:
            from .mailbox import save_copy
            save_copy(self.s, msg)
        except Exception as exc:
            print(f"    (could not copy to Sent folder: {type(exc).__name__}: {exc})"[:160])

    # ---------- message ----------
    def build_message(self, to_email: str, to_name: str, subject: str,
                      body: str) -> EmailMessage:
        msg = EmailMessage()
        from_name = self.s.smtp_from_name or (self.profile.name if self.profile else "")
        msg["From"] = formataddr((from_name, self.s.smtp_from)) if from_name else self.s.smtp_from
        msg["To"] = formataddr((to_name, to_email)) if to_name else to_email
        msg["Subject"] = subject
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid(
            domain=self.s.smtp_from.rpartition("@")[2] or None)
        if self.s.reply_to:
            msg["Reply-To"] = self.s.reply_to
        full_body = body.rstrip() + "\n" + self.signature
        msg.set_content(full_body)
        self._attach_files(msg)
        return msg

    # ---------- sending ----------
    def _deliver(self, msg: EmailMessage) -> None:
        """Send one message, reconnecting once if the server dropped us.

        University relays routinely close the socket after a few messages or
        an idle gap. A dropped connection is transient, so rebuild it and try
        again rather than failing every remaining row against a dead socket.
        """
        try:
            if self._server is None:
                self.connect()
            self._server.send_message(msg)
            return
        except (smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError, OSError):
            self.close()
            self.connect()
            self._server.send_message(msg)

    def send_one(self, row: dict) -> dict:
        subject = row.get("subject") or "Summer research internship enquiry"
        to_email = row["email"]
        to_name = row.get("name", "")
        if self.redirect_to:
            # Review mode: deliver to yourself, but keep the real target visible.
            subject = f"[DRAFT -> {to_email}] {subject}"
            to_email, to_name = self.redirect_to, ""
        msg = self.build_message(to_email, to_name, subject, row["body"])
        if self.dry_run:
            return {"status": "dry-run", "detail": "not sent", "message": msg}
        try:
            self._deliver(msg)
            self.sent_count += 1
            if not self.redirect_to:
                self._archive(msg)
            status = "review-sent" if self.redirect_to else "sent"
            return {"status": status, "detail": "", "message": msg}
        except Exception as exc:
            return {"status": f"failed: {type(exc).__name__}", "detail": str(exc)[:200],
                    "message": msg}

    def save_eml(self, row: dict, directory: Path) -> Path:
        """Write a draft as a .eml file that any mail client can open."""
        directory.mkdir(parents=True, exist_ok=True)
        msg = self.build_message(row["email"], row.get("name", ""),
                                 row.get("subject") or "Summer research internship enquiry",
                                 row["body"])
        slug = re.sub(r"[^A-Za-z0-9]+", "_", row.get("name") or row["email"]).strip("_")[:50]
        path = directory / f"{row.get('probability', 0):03d}_{slug}.eml"
        path.write_bytes(msg.as_bytes())
        return path

    def send_batch(self, rows: list[dict], progress=None,
                   resend: bool = False, top: int | None = None,
                   allow_unverified: bool = False, window=None,
                   wait_for_window: bool = False, on_update=None) -> list[dict]:
        """Send pending rows. With `window` (a schedule.SendWindow), a row only
        goes out inside the recipient's local hours; rows outside it are left
        untouched, or waited for when `wait_for_window` is set."""
        updates = []
        # A dry run must never block a later real send, and neither may a
        # review copy sent to yourself: only real deliveries count when live.
        done = {"sent", "review-sent"} if self.redirect_to else {"sent"}
        pending = [
            r for r in rows
            if (resend or r.get("send_status", "").lower() not in done)
            and r.get("probability", 0) >= self.s.send_min_probability
        ]
        if top:
            # Mail the N strongest matches, not the first N in sheet order.
            pending = sorted(pending, key=lambda r: -r.get("probability", 0))[:top]
        total = len(pending)
        queue = list(enumerate(pending, 1))
        consecutive_failures = 0
        while queue:
            if self.sent_count >= self.s.daily_send_cap and not self.dry_run:
                # Leave the rest untouched for the next run instead of waiting
                # out their local windows just to mark them skipped.
                break
            if window is not None:
                pick = next((k for k, (_, r) in enumerate(queue) if window.ready(r)), None)
                if pick is None:
                    waits = [window.seconds_until(r) for _, r in queue]
                    if wait_for_window and not self.dry_run:
                        self.close()
                        self._countdown(min(waits), label="next local send window opens")
                        continue
                    for (i, row), w in zip(queue, waits):
                        if progress:
                            progress(i, total, row, {
                                "status": "held",
                                "detail": f"outside local window, opens in {_fmt(w)}",
                                "message": None})
                    break
                i, row = queue.pop(pick)
            else:
                i, row = queue.pop(0)
            if self.sent_count >= self.s.daily_send_cap and not self.dry_run:
                updates.append({**row, "status": "skipped: daily cap reached"})
                continue
            if row.get("email_status") == "invalid" and not allow_unverified:
                # `verify` proved this address is undeliverable; sending anyway
                # only generates bounces and hurts the sending domain.
                result = {"status": "skipped: invalid address",
                          "detail": "run `verify --repair`, or pass --allow-unverified",
                          "message": None}
                updates.append({"sheet": row["sheet"], "row": row["row"],
                                "status": result["status"],
                                "detail": result["detail"], "sent_at": ""})
                if progress:
                    progress(i, total, row, result)
                continue
            result = self.send_one(row)
            update = {
                "sheet": row["sheet"], "row": row["row"],
                "status": result["status"],
                "detail": result.get("detail", ""),
                "sent_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                if result["status"] in {"sent", "review-sent", "dry-run"} else "",
            }
            if result["status"] == "sent" and result.get("message") is not None:
                update["message_id"] = result["message"]["Message-ID"]
            updates.append(update)
            if on_update:
                on_update(update)
            if progress:
                progress(i, total, row, result)

            if result["status"].startswith("failed"):
                # A mail server that rejects or drops several in a row is
                # throttling or refusing the account. Hammering it burns the
                # sender reputation and marks every remaining row failed.
                consecutive_failures += 1
                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    if progress:
                        progress(i, total, row, {
                            "status": "aborted",
                            "detail": f"{consecutive_failures} consecutive SMTP failures; "
                                      "stopping so the rest stay sendable",
                            "message": None,
                        })
                    break
                if self.s.send_delay_max:
                    time.sleep(min(30.0, 5.0 * consecutive_failures))
                continue

            consecutive_failures = 0
            if queue and result["status"] in {"sent", "review-sent"}:
                delay = random.uniform(self.s.send_delay_min, self.s.send_delay_max)
                if delay > 30 and not self.dry_run:
                    # The relay drops idle sessions within minutes; reconnect
                    # fresh for the next message rather than reuse a dead socket.
                    self.close()
                self._countdown(delay)
        return updates

    @staticmethod
    def _countdown(delay: float, label: str = "next email") -> None:
        """Sleep for `delay` seconds while showing a live timer on the console.

        Uses the wall clock, not time.monotonic(): on macOS (and some Windows
        builds) the monotonic clock pauses while the laptop sleeps, so a lid
        close would silently stretch every wait by the time spent asleep.
        """
        start = time.time()
        deadline = start + delay
        total = _fmt(delay)
        while True:
            now = time.time()
            elapsed, left = now - start, deadline - now
            if left <= 0:
                break
            sys.stdout.write(f"\r    waiting {_fmt(elapsed)} / {total} "
                             f"({label} in {_fmt(left + 0.999)})  ")
            sys.stdout.flush()
            time.sleep(min(1.0, left))
        sys.stdout.write(f"\r    waited {total} ({label}){' ' * 40}\n")
        sys.stdout.flush()
