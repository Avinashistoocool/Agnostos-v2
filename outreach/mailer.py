"""Email dispatch: SMTP with attachments, throttling, dry-run, and resume safety."""
from __future__ import annotations

import mimetypes
import random
import re
import smtplib
import ssl
import time
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from pathlib import Path

from .config import Settings
from .resume_parser import ResumeProfile

SIGNATURE = """
--
{name}
{degree}
{institution}
{email}{phone}"""


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
        context = ssl.create_default_context()
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

    # ---------- message ----------
    def build_message(self, to_email: str, to_name: str, subject: str,
                      body: str) -> EmailMessage:
        msg = EmailMessage()
        from_name = self.s.smtp_from_name or (self.profile.name if self.profile else "")
        msg["From"] = formataddr((from_name, self.s.smtp_from)) if from_name else self.s.smtp_from
        msg["To"] = formataddr((to_name, to_email)) if to_name else to_email
        msg["Subject"] = subject
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid()
        if self.s.reply_to:
            msg["Reply-To"] = self.s.reply_to
        full_body = body.rstrip() + "\n" + self.signature
        msg.set_content(full_body)

        for raw_path in self.s.attachments:
            path = Path(raw_path)
            if not path.exists():
                continue
            ctype, encoding = mimetypes.guess_type(str(path))
            maintype, _, subtype = (ctype or "application/octet-stream").partition("/")
            msg.add_attachment(path.read_bytes(), maintype=maintype,
                               subtype=subtype, filename=path.name)
        return msg

    # ---------- sending ----------
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
            self._server.send_message(msg)
            self.sent_count += 1
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
                   resend: bool = False, top: int | None = None) -> list[dict]:
        updates = []
        # A dry run must never block a later real send, so only genuine
        # deliveries count as already-handled.
        done = {"sent", "review-sent"}
        pending = [
            r for r in rows
            if (resend or r.get("send_status", "").lower() not in done)
            and r.get("probability", 0) >= self.s.send_min_probability
        ]
        if top:
            # Mail the N strongest matches, not the first N in sheet order.
            pending = sorted(pending, key=lambda r: -r.get("probability", 0))[:top]
        for i, row in enumerate(pending, 1):
            if self.sent_count >= self.s.daily_send_cap and not self.dry_run:
                updates.append({**row, "status": "skipped: daily cap reached"})
                continue
            result = self.send_one(row)
            update = {
                "sheet": row["sheet"], "row": row["row"],
                "status": result["status"],
                "sent_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                if result["status"] in {"sent", "review-sent", "dry-run"} else "",
            }
            updates.append(update)
            if progress:
                progress(i, len(pending), row, result)
            if i < len(pending) and result["status"] in {"sent", "review-sent"}:
                delay = random.uniform(self.s.send_delay_min, self.s.send_delay_max)
                time.sleep(delay)
        return updates
