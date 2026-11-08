"""Deadline reminders for internship / summer programmes (CERN, EPFL, ITER, ...).

Reads output/programs/internship_programs.json and, once a day:
  * emails the owner (only the two fixed addresses below) when a programme
    opens, when referees should be asked (21 days before the deadline if
    referees are needed), and 30/14/7/3/1 days before each deadline;
  * sends a weekly digest (Mondays, or the first run of a week) of everything
    due in the next 60 days, plus a one-off "tracker is live" digest;
  * with --calendar, mirrors every milestone into Google Calendar (all-day
    deadline events + 09:00 IST milestone events with popup/email reminders)
    so the phone's Calendar app notifies;
  * optionally texts the phone through Twilio when TWILIO_* is set.

State (idempotency) lives next to the data:
  reminders_sent.json   one entry per (programme, milestone) / digest
  calendar_events.json  Google Calendar event ids + content hashes
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import smtplib
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path
from typing import Callable, Iterable

from .config import settings

RECIPIENTS = ("avinashchandragupta206@gmail.com", "ph1251520@physics.iitd.ac.in")
PHONE = "+917023037566"
DEADLINE_OFFSETS = (30, 14, 7, 3, 1)
REFEREE_OFFSET = 21
DIGEST_HORIZON = 60
OPENS_STALE_DAYS = 14          # an "applications open" note older than this is not worth a mail
COMBINE_THRESHOLD = 3          # more due reminders than this in one run -> one combined email
TZ = "Asia/Kolkata"
EXTERNAL_CV_DIR = Path(r"C:\Users\Avinash\OneDrive\Desktop\Dynamic-CV\program_cvs")


def programs_dir() -> Path:
    return settings.output_dir / "programs"


# ---------------------------------------------------------------- data

def _date(v) -> date | None:
    if not v or not isinstance(v, str):
        return None
    try:
        return date.fromisoformat(v.strip()[:10])
    except ValueError:
        return None


def load_programs(path: Path | None = None, retries: int = 3) -> list[dict]:
    """Tolerates a file that another process is mid-way through writing."""
    path = path or programs_dir() / "internship_programs.json"
    last: Exception | None = None
    for attempt in range(retries):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data = data.get("programs", [])
            return [p for p in data if isinstance(p, dict) and p.get("id")]
        except json.JSONDecodeError as exc:
            last = exc
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"{path} is not valid JSON: {last}")


def _referees(p: dict) -> int:
    try:
        return int(p.get("referees_needed") or 0)
    except (TypeError, ValueError):
        return 0


@dataclass(frozen=True)
class Milestone:
    key: str        # e.g. "deadline-7", "opens", "referees-21"
    track: str      # opens | referees | deadline
    day: date
    offset: int     # days before the deadline (0 for opens)


def milestones(p: dict) -> list[Milestone]:
    out: list[Milestone] = []
    opens, deadline = _date(p.get("application_opens")), _date(p.get("deadline"))
    if opens and (not deadline or opens <= deadline):
        out.append(Milestone("opens", "opens", opens, 0))
    if deadline:
        if _referees(p) > 0:
            out.append(Milestone(f"referees-{REFEREE_OFFSET}", "referees",
                                 deadline - timedelta(days=REFEREE_OFFSET), REFEREE_OFFSET))
        for n in DEADLINE_OFFSETS:
            out.append(Milestone(f"deadline-{n}", "deadline", deadline - timedelta(days=n), n))
    return sorted(out, key=lambda m: m.day)


def cv_path(p: dict) -> Path | None:
    pid = str(p.get("id"))
    for c in (programs_dir() / "cvs" / f"{pid}.pdf", EXTERNAL_CV_DIR / f"CV_{pid}.pdf"):
        if c.exists():
            return c
    return None


# ---------------------------------------------------------------- state

def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    for attempt in range(10):           # OneDrive/AV can hold the file briefly
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 9:
                raise
            time.sleep(0.5 * (attempt + 1))


@dataclass
class Due:
    program: dict
    milestone: Milestone
    superseded: list[Milestone] = field(default_factory=list)


def due_reminders(programs: Iterable[dict], today: date, sent: dict) -> list[Due]:
    """The most recent reached-but-unsent milestone per (programme, track).
    Older unsent ones in the same track are superseded, never sent later."""
    out: list[Due] = []
    for p in programs:
        if p.get("eligible") is False:
            continue
        deadline = _date(p.get("deadline"))
        if deadline and deadline < today:
            continue
        by_track: dict[str, list[Milestone]] = {}
        for m in milestones(p):
            if m.day <= today:
                by_track.setdefault(m.track, []).append(m)
        for track, ms in by_track.items():
            latest = ms[-1]
            if f"{p['id']}|{latest.key}" in sent:
                continue
            if track == "opens" and (today - latest.day).days > OPENS_STALE_DAYS:
                continue
            older = [m for m in ms[:-1] if f"{p['id']}|{m.key}" not in sent]
            out.append(Due(p, latest, older))
    # A referee nudge and a deadline reminder due together: one email, not two.
    merged: list[Due] = []
    for d in out:
        twin = next((o for o in out if o.program is d.program and o is not d
                     and o.milestone.track == "deadline" and o.milestone.day >= d.milestone.day), None)
        if d.milestone.track == "referees" and twin is not None:
            twin.superseded.append(d.milestone)
            continue
        merged.append(d)
    out = merged
    return sorted(out, key=lambda d: (_date(d.program.get("deadline")) or date.max,
                                      d.program.get("name", "")))


# ---------------------------------------------------------------- text

def _label(p: dict) -> str:
    name = p.get("name") or p["id"]
    org = p.get("org") or ""
    return name if not org or org.lower() in name.lower() else f"{org} {name}"


def _days_phrase(n: int) -> str:
    return "TODAY" if n == 0 else "tomorrow" if n == 1 else f"in {n} days"


def headline(d: Due, today: date) -> str:
    p, m = d.program, d.milestone
    deadline = _date(p.get("deadline"))
    if m.track == "opens":
        tail = f" (deadline {deadline})" if deadline else ""
        return f"{_label(p)}: applications are open{tail}"
    left = (deadline - today).days
    if m.track == "referees":
        return f"{_label(p)}: ask your {_referees(p)} referee(s) now (deadline {_days_phrase(left)}, {deadline})"
    return f"{_label(p)}: deadline {_days_phrase(left)} ({deadline})"


def program_block(p: dict, today: date | None) -> str:
    deadline = _date(p.get("deadline"))
    lines = [f"{_label(p)}  [{p.get('country') or '?'}]"]
    if deadline:
        rel = f" ({_days_phrase((deadline - today).days)})" if today else ""
        lines.append(f"  Deadline: {deadline}{rel}"
                     f"{'  [' + p['deadline_status'] + ']' if p.get('deadline_status') else ''}")
    else:
        lines.append(f"  Deadline: not announced yet"
                     f"{'  [' + p['deadline_status'] + ']' if p.get('deadline_status') else ''}")
    if p.get("application_opens"):
        lines.append(f"  Applications open: {p['application_opens']}")
    for k, label in (("duration", "Duration"), ("stipend", "Stipend"),
                     ("eligibility", "Eligibility")):
        if p.get(k):
            lines.append(f"  {label}: {p[k]}")
    if p.get("eligible") is False:
        lines.append("  NOTE: marked as possibly NOT eligible - check before applying")
    docs = p.get("documents") or []
    if docs:
        lines.append("  Documents checklist:")
        lines += [f"    [ ] {doc}" for doc in docs]
    if _referees(p):
        lines.append(f"  Referees needed: {_referees(p)}")
    if p.get("url"):
        lines.append(f"  Apply: {p['url']}")
    if p.get("source_url") and p.get("source_url") != p.get("url"):
        lines.append(f"  Source: {p['source_url']}")
    cv = cv_path(p)
    lines.append(f"  Tailored CV: {cv}" if cv else "  Tailored CV: not generated yet")
    if p.get("cv_focus"):
        lines.append(f"  CV focus: {p['cv_focus']}")
    if p.get("notes"):
        lines.append(f"  Notes: {p['notes']}")
    return "\n".join(lines)


FOOTER = ("\n\n--\nAgnostos internship deadline tracker. Runs daily at 09:00; "
          "each reminder is sent once.\nData: output\\programs\\internship_programs.json")


def reminder_email(d: Due, today: date) -> tuple[str, str]:
    body = f"{headline(d, today)}\n\n{program_block(d.program, today)}"
    if d.milestone.track == "referees":
        body += ("\n\nReferees usually need 2-3 weeks. Email them today with the programme "
                 "link, the deadline, your CV and a short note on why you are applying.")
    elif _referees(d.program):
        body += (f"\n\nReferees: make sure your {_referees(d.program)} referee(s) have been asked "
                 "and have submitted their letters before the deadline.")
    return f"[Agnostos] {headline(d, today)}", body + FOOTER


def combined_email(dues: list[Due], today: date) -> tuple[str, str]:
    first = dues[0]
    subj = f"[Agnostos] {len(dues)} internship reminders - first: {headline(first, today)}"
    parts = [f"{i}. {headline(d, today)}" for i, d in enumerate(dues, 1)]
    blocks = [program_block(d.program, today) for d in dues]
    return subj, "\n".join(parts) + "\n\n" + "\n\n".join(blocks) + FOOTER


def _by_deadline(programs: Iterable[dict]) -> list[dict]:
    return sorted(programs, key=lambda p: (_date(p.get("deadline")) or date.max,
                                           p.get("name", "")))


def digest_email(programs: list[dict], today: date, welcome: bool) -> tuple[str, str]:
    if welcome:
        items = [p for p in _by_deadline(programs)
                 if not (_date(p.get("deadline")) and _date(p["deadline"]) < today)]
        subj = f"[Agnostos] Your internship deadline tracker is live ({len(items)} programmes)"
        intro = ("You will get an email when each programme opens, 21 days before the deadline "
                 "if referees are needed, and 30/14/7/3/1 days before every deadline, plus a "
                 "digest every Monday. Programmes sorted by deadline:")
    else:
        end = today + timedelta(days=DIGEST_HORIZON)
        items = [p for p in _by_deadline(programs)
                 if _date(p.get("deadline")) and today <= _date(p["deadline"]) <= end]
        subj = f"[Agnostos] Weekly digest: {len(items)} internship deadline(s) in the next {DIGEST_HORIZON} days"
        intro = f"Due between {today} and {end}:" if items else \
            f"Nothing is due in the next {DIGEST_HORIZON} days."
    skipped = [p for p in items if p.get("eligible") is False]
    items = [p for p in items if p.get("eligible") is not False]
    summary = []
    for p in items:
        dl = _date(p.get("deadline"))
        when = f"{dl} ({_days_phrase((dl - today).days)})" if dl else "TBA"
        summary.append(f"  {when:<26} {_label(p)}")
    blocks = [program_block(p, today) for p in items]
    body = intro + "\n\n" + "\n".join(summary)
    if blocks:
        body += "\n\n" + "=" * 60 + "\n\n" + "\n\n".join(blocks)
    if skipped:
        body += ("\n\nNot eligible this cycle (no reminders sent):\n"
                 + "\n".join(f"  {_label(p)}: {p.get('eligibility', '')}" for p in skipped))
    return subj, body + FOOTER


# ---------------------------------------------------------------- delivery

def _guard(to: Iterable[str]) -> list[str]:
    to = list(to)
    bad = [a for a in to if a not in RECIPIENTS]
    if bad:
        raise ValueError(f"refusing to email non-owner address(es): {bad}")
    return to


class GmailSender:
    """Sends from the personal Gmail account configured as RESEND_SMTP_*."""

    def __init__(self, s=settings):
        self.s = s
        self.server = None

    def _open(self):
        from .tls import context as tls_context
        s = self.s
        if not (s.resend_smtp_user and s.resend_smtp_password):
            raise RuntimeError("set RESEND_SMTP_USER and RESEND_SMTP_PASSWORD in .env")
        if s.resend_smtp_security.lower() == "ssl":
            srv = smtplib.SMTP_SSL(s.resend_smtp_host, s.resend_smtp_port,
                                   context=tls_context(), timeout=60)
        else:
            srv = smtplib.SMTP(s.resend_smtp_host, s.resend_smtp_port, timeout=60)
            srv.ehlo()
            if s.resend_smtp_security.lower() == "starttls":
                srv.starttls(context=tls_context())
                srv.ehlo()
        srv.login(s.resend_smtp_user, s.resend_smtp_password)
        self.server = srv

    def __call__(self, subject: str, body: str, to: Iterable[str] = RECIPIENTS) -> None:
        to = _guard(to)
        msg = EmailMessage()
        msg["From"] = self.s.resend_smtp_from or self.s.resend_smtp_user
        msg["To"] = ", ".join(to)
        msg["Subject"] = subject
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid(domain="agnostos.local")
        msg.set_content(body)
        for attempt in range(2):
            try:
                if self.server is None:
                    self._open()
                self.server.send_message(msg, to_addrs=to)
                return
            except (smtplib.SMTPServerDisconnected, OSError):
                self.server = None
                if attempt:
                    raise

    def close(self):
        if self.server is not None:
            try:
                self.server.quit()
            except Exception:
                pass
            self.server = None


def twilio_sms(text: str) -> bool:
    """Optional: text the phone when TWILIO_ACCOUNT_SID/AUTH_TOKEN/FROM are set."""
    sid, tok, frm = (os.getenv("TWILIO_ACCOUNT_SID", ""), os.getenv("TWILIO_AUTH_TOKEN", ""),
                     os.getenv("TWILIO_FROM", ""))
    if not (sid and tok and frm):
        return False
    from .tls import urlopen
    data = urllib.parse.urlencode({"To": PHONE, "From": frm, "Body": text[:1500]}).encode()
    req = urllib.request.Request(
        f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json", data=data,
        headers={"Authorization": "Basic " + base64.b64encode(f"{sid}:{tok}".encode()).decode()})
    with urlopen(req, timeout=30) as r:
        return 200 <= r.status < 300


def sms_configured() -> bool:
    return all(os.getenv(k) for k in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM"))


# ---------------------------------------------------------------- calendar

def calendar_bodies(programs: Iterable[dict], today: date) -> dict[str, dict]:
    """Every event the calendar should contain, keyed by a stable id."""
    out: dict[str, dict] = {}
    for p in programs:
        if p.get("eligible") is False:
            continue
        deadline = _date(p.get("deadline"))
        if not deadline or deadline < today:
            continue
        pid, label = str(p["id"]), _label(p)
        desc = program_block(p, None)
        out[f"{pid}|deadline"] = {
            "summary": f"DEADLINE: {label}",
            "description": desc,
            "start": {"date": deadline.isoformat()},
            "end": {"date": (deadline + timedelta(days=1)).isoformat()},
            "transparency": "transparent",
            "colorId": "11",
            "reminders": {"useDefault": False, "overrides": [
                {"method": "popup", "minutes": 7 * 1440},
                {"method": "popup", "minutes": 3 * 1440},
                {"method": "popup", "minutes": 900},        # 15:00 the day before
                {"method": "email", "minutes": 7 * 1440},
                {"method": "email", "minutes": 1440}]},
        }
        for m in milestones(p):
            if m.day < today:
                continue
            if m.track == "opens":
                title = f"Applications open: {label}"
            elif m.track == "referees":
                title = f"Ask referees now: {label} (deadline {deadline})"
            else:
                title = f"{label}: deadline in {m.offset} day{'s' if m.offset > 1 else ''} ({deadline})"
            out[f"{pid}|{m.key}"] = {
                "summary": title,
                "description": desc,
                "start": {"dateTime": f"{m.day.isoformat()}T09:00:00", "timeZone": TZ},
                "end": {"dateTime": f"{m.day.isoformat()}T09:15:00", "timeZone": TZ},
                "transparency": "transparent",
                "colorId": "6",
                "reminders": {"useDefault": False, "overrides": [
                    {"method": "popup", "minutes": 0},
                    {"method": "popup", "minutes": 720},     # 21:00 the evening before
                    {"method": "email", "minutes": 0}]},
            }
    for key, body in out.items():
        body["extendedProperties"] = {"private": {"agnostosKey": key}}
    return out


def _hash(body: dict) -> str:
    return hashlib.sha1(json.dumps(body, sort_keys=True).encode()).hexdigest()[:16]


def sync_calendar(svc, programs: list[dict], today: date, store_path: Path,
                  cal_id: str | None = None, log: Callable[[str], None] = print) -> dict:
    """Create/update events; returns counts. Idempotent via store_path."""
    cal_id = cal_id or settings.google_calendar_id
    store = _load_json(store_path)
    events = store.setdefault("events", {})
    counts = {"created": 0, "updated": 0, "unchanged": 0, "deleted": 0, "failed": 0}
    wanted = calendar_bodies(programs, today)
    ev_api = svc.events()
    for key, body in wanted.items():
        h = _hash(body)
        rec = events.get(key)
        try:
            if rec and rec.get("hash") == h:
                counts["unchanged"] += 1
                continue
            eid = rec.get("id") if rec else None
            if not eid:
                found = ev_api.list(calendarId=cal_id, maxResults=1, showDeleted=False,
                                    privateExtendedProperty=f"agnostosKey={key}").execute()
                items = found.get("items") or []
                eid = items[0]["id"] if items else None
            if eid:
                try:
                    ev_api.update(calendarId=cal_id, eventId=eid, body=body).execute()
                    counts["updated"] += 1
                except Exception as exc:
                    if getattr(getattr(exc, "resp", None), "status", None) not in (404, 410):
                        raise
                    eid = None
            if not eid:
                eid = ev_api.insert(calendarId=cal_id, body=body).execute()["id"]
                counts["created"] += 1
            events[key] = {"id": eid, "hash": h}
        except Exception as exc:
            counts["failed"] += 1
            log(f"   calendar: {key}: {type(exc).__name__}: {exc}")
        _save_json(store_path, store)
    # Events that are no longer wanted: keep the ones that are simply in the
    # past (history), delete ones whose programme/milestone disappeared.
    by_id = {str(p["id"]): p for p in programs}
    for key in list(events):
        if key in wanted:
            continue
        pid, mkey = key.split("|", 1)
        prog = by_id.get(pid)
        if prog is not None:
            dl = _date(prog.get("deadline"))
            days = {m.key: m.day for m in milestones(prog)}
            if dl:
                days["deadline"] = dl
            if mkey in days and days[mkey] < today:
                continue
        try:
            ev_api.delete(calendarId=cal_id, eventId=events[key]["id"]).execute()
        except Exception:
            pass
        events.pop(key)
        counts["deleted"] += 1
        _save_json(store_path, store)
    _save_json(store_path, store)
    return counts


def calendar_service(log: Callable[[str], None] = print):
    from . import gcal
    try:
        svc = gcal.service(interactive=False)
        return svc
    except Exception as exc:
        log(f" Google Calendar unavailable ({type(exc).__name__}: {exc}).")
        log("   Fix: run `python -m outreach.cli calendar-auth` (or output\\run_calauth.ps1). "
            "Continuing with email only.")
        return None


# ---------------------------------------------------------------- orchestration

def run(programs: list[dict], today: date, out_dir: Path | None = None, *,
        dry_run: bool = False, send: Callable[[str, str], None] | None = None,
        sms: Callable[[str], bool] | None = None, calendar_svc=None,
        log: Callable[[str], None] = print) -> dict:
    """One daily pass. Returns a summary dict (used by tests and the CLI)."""
    out_dir = out_dir or programs_dir()
    state_path = out_dir / "reminders_sent.json"
    state = _load_json(state_path)
    sent: dict = state.setdefault("sent", {})
    now = datetime.now().isoformat(timespec="seconds")
    summary = {"emails": [], "sms": 0, "calendar": None, "dry_run": dry_run}

    def deliver(subject: str, body: str, keys: list[str], superseded: list[str] = ()):
        summary["emails"].append(subject)
        log(f"  {'[dry-run] would email' if dry_run else 'email'}: {subject}")
        if dry_run:
            return
        send(subject, body)
        for k in keys:
            sent[k] = {"at": now, "how": "sent", "subject": subject}
        for k in superseded:
            sent.setdefault(k, {"at": now, "how": "superseded"})
        _save_json(state_path, state)

    def keys(ds):
        return [f"{d.program['id']}|{d.milestone.key}" for d in ds]

    def old(ds):
        return [f"{d.program['id']}|{m.key}" for d in ds for m in d.superseded]

    week = f"digest|{today.isocalendar()[0]}-W{today.isocalendar()[1]:02d}"
    dues = due_reminders(programs, today, sent)
    if "welcome" not in sent:
        # The welcome digest already lists everything; "opens" and 30/14-day
        # notices are folded into it, urgent ones still get their own email.
        covered = [d for d in dues if (d.milestone.track == "opens" or
                   (d.milestone.track == "deadline" and d.milestone.offset > 7))
                   and not any(m.track == "referees" for m in d.superseded)]
        dues = [d for d in dues if d not in covered]
        subj, body = digest_email(programs, today, welcome=True)
        nxt = today + timedelta(days=7 - today.weekday())
        skip = [f"digest|{nxt.isocalendar()[0]}-W{nxt.isocalendar()[1]:02d}"] \
            if today.weekday() >= 4 else []
        deliver(subj, body, ["welcome", week] + skip + keys(covered), old(covered))
    elif week not in sent:
        subj, body = digest_email(programs, today, welcome=False)
        deliver(subj, body, [week])

    if len(dues) > COMBINE_THRESHOLD:
        subj, body = combined_email(dues, today)
        deliver(subj, body, keys(dues), old(dues))
    else:
        for d in dues:
            subj, body = reminder_email(d, today)
            deliver(subj, body, keys([d]), old([d]))
    if dues and sms is not None:
        text = "Agnostos: " + "; ".join(headline(d, today) for d in dues)
        if dry_run:
            log(f"  [dry-run] would SMS {PHONE}: {text[:160]}")
        else:
            try:
                if sms(text):
                    summary["sms"] += 1
            except Exception as exc:
                log(f"  SMS failed: {type(exc).__name__}: {exc}")

    if calendar_svc is not None:
        if dry_run:
            n = len(calendar_bodies(programs, today))
            log(f"  [dry-run] calendar: {n} event(s) would be created/updated")
            summary["calendar"] = {"planned": n}
        else:
            summary["calendar"] = sync_calendar(calendar_svc, programs, today,
                                                out_dir / "calendar_events.json", log=log)
            log(f"  calendar: {summary['calendar']}")
    if not dry_run and state.get("sent"):
        _save_json(state_path, state)
    return summary


def cmd_program_reminders(args) -> int:
    today = date.fromisoformat(args.now) if args.now else date.today()
    path = Path(args.programs) if args.programs else programs_dir() / "internship_programs.json"
    print(f"== {datetime.now():%a %d %b %Y %H:%M} program-reminders (today={today}"
          f"{', dry-run' if args.dry_run else ''}) ==")
    if not path.exists():
        print(f" No programme list yet at {path}; nothing to do.")
        return 0
    programs = load_programs(path)
    print(f" {len(programs)} programme(s) loaded from {path}")
    svc = calendar_service() if args.calendar else None
    sender = None if args.dry_run else GmailSender()
    try:
        res = run(programs, today, path.parent, dry_run=args.dry_run, send=sender,
                  sms=twilio_sms if sms_configured() else None, calendar_svc=svc)
    finally:
        if sender is not None:
            sender.close()
    print(f" Done: {len(res['emails'])} email(s){' planned' if args.dry_run else ' sent'}"
          f" to {', '.join(RECIPIENTS)}; calendar={res['calendar']}; sms={res['sms']}")
    return 0
