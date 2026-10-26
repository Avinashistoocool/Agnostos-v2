"""Google Calendar: find free slots and place holds for proposed meetings.

One-time setup (see README "Google Calendar"):
  1. console.cloud.google.com -> new project -> enable "Google Calendar API".
  2. OAuth consent screen: External, add your Gmail as a test user.
  3. Credentials -> Create OAuth client ID -> Desktop app -> download JSON,
     save it as GOOGLE_CLIENT_SECRET (default: credentials.json in the repo root).
  4. python -m outreach.cli calendar-auth   (opens a browser once; token is cached)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import ROOT, settings

SCOPES = ["https://www.googleapis.com/auth/calendar"]


def _paths() -> tuple[Path, Path]:
    secret = Path(settings.google_client_secret or ROOT / "credentials.json")
    if not secret.is_absolute():
        secret = ROOT / secret
    return secret, settings.output_dir / "gcal_token.json"


def available() -> bool:
    secret, token = _paths()
    return token.exists() or secret.exists()


def service(interactive: bool = False):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    secret, token = _paths()
    creds = Credentials.from_authorized_user_file(str(token), SCOPES) if token.exists() else None
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    if not creds or not creds.valid:
        if not interactive:
            raise RuntimeError("Google Calendar not authorised; run "
                               "`python -m outreach.cli calendar-auth`")
        if not secret.exists():
            raise RuntimeError(f"OAuth client file not found: {secret}")
        from google_auth_oauthlib.flow import InstalledAppFlow
        creds = InstalledAppFlow.from_client_secrets_file(str(secret), SCOPES) \
            .run_local_server(port=0)
    token.parent.mkdir(parents=True, exist_ok=True)
    token.write_text(creds.to_json(), encoding="utf-8")
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def _busy(svc, start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    cal = settings.google_calendar_id
    res = svc.freebusy().query(body={
        "timeMin": start.isoformat(), "timeMax": end.isoformat(),
        "items": [{"id": cal}]}).execute()
    out = []
    for b in res.get("calendars", {}).get(cal, {}).get("busy", []):
        out.append((datetime.fromisoformat(b["start"].replace("Z", "+00:00")),
                    datetime.fromisoformat(b["end"].replace("Z", "+00:00"))))
    return out


def _hours(spec: str) -> tuple[int, int]:
    a, b = spec.split("-", 1)
    return int(a), int(b)


def propose_slots(their_tz: ZoneInfo | None, n: int = 3, svc=None,
                  taken: list[tuple[datetime, datetime]] | None = None) -> list[datetime]:
    """`n` start times (UTC-aware) on different weekdays, inside the professor's
    local working hours AND my own hours, at least MEET_LEAD_DAYS ahead, and
    free on my calendar when the API is available."""
    mine = ZoneInfo(settings.meet_my_tz)
    their_tz = their_tz or ZoneInfo("Europe/Berlin")
    t0, t1 = _hours(settings.meet_their_hours)
    m0, m1 = _hours(settings.meet_my_hours)
    dur = timedelta(minutes=settings.meet_minutes)
    start = datetime.now(timezone.utc) + timedelta(days=settings.meet_lead_days)
    horizon = start + timedelta(days=14)
    busy = list(taken or [])
    if svc is not None:
        try:
            busy += _busy(svc, start, horizon)
        except Exception:
            pass
    slots: list[datetime] = []
    used_days = set()
    day = start.astimezone(their_tz).date()
    while len(slots) < n and datetime.combine(day, datetime.min.time(), their_tz) < horizon:
        if day.weekday() < 5 and day not in used_days:
            for hour in range(t0, t1):
                for minute in (0, 30):
                    s = datetime(day.year, day.month, day.day, hour, minute, tzinfo=their_tz)
                    e = s + dur
                    if s < start or e.astimezone(their_tz).hour * 60 + e.minute > t1 * 60:
                        continue
                    ms, me = s.astimezone(mine), e.astimezone(mine)
                    if not (m0 * 60 <= ms.hour * 60 + ms.minute
                            and me.hour * 60 + me.minute <= m1 * 60 and ms.date() == me.date()):
                        continue
                    if any(s < be and e > bs for bs, be in busy):
                        continue
                    slots.append(s.astimezone(timezone.utc))
                    used_days.add(day)
                    break
                if day in used_days:
                    break
        day += timedelta(days=1)
    return slots


def describe(slots: list[datetime], their_tz: ZoneInfo | None) -> list[str]:
    tz = their_tz or ZoneInfo("Europe/Berlin")
    mine = ZoneInfo(settings.meet_my_tz)
    out = []
    for s in slots:
        local = s.astimezone(tz)
        me = s.astimezone(mine)
        if local.utcoffset() == me.utcoffset():
            out.append(f"{local:%A %d %B, %H:%M} ({local.tzname() or 'IST'})")
            continue
        out.append(f"{local:%A %d %B, %H:%M} your time ({local.tzname()}; "
                   f"{me:%H:%M} {me.tzname() or 'IST'} for me)")
    return out


def create_holds(svc, slots: list[datetime], prof_name: str, prof_email: str,
                 institution: str = "") -> list[str]:
    """Tentative events for each proposed slot. Returns event ids."""
    ids = []
    dur = timedelta(minutes=settings.meet_minutes)
    for s in slots:
        body = {
            "summary": f"HOLD: call with {prof_name} ({institution})".strip(),
            "description": (f"Proposed to {prof_name} <{prof_email}> by Agnostos. "
                            "Tentative until they confirm; delete the other holds then."),
            "start": {"dateTime": s.isoformat()},
            "end": {"dateTime": (s + dur).isoformat()},
            "status": "tentative", "transparency": "opaque",
            "colorId": "5",
        }
        ev = svc.events().insert(calendarId=settings.google_calendar_id, body=body).execute()
        ids.append(ev.get("id", ""))
    return ids
