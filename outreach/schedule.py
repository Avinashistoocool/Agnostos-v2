"""Send-time scheduling: a fixed start time, and each professor's local working hours."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Countries spanning several zones, where the first zone.tab entry is a poor
# stand-in for where most universities are.
TZ_OVERRIDES = {
    "US": "America/New_York", "CA": "America/Toronto", "AU": "Australia/Sydney",
    "BR": "America/Sao_Paulo", "RU": "Europe/Moscow", "MX": "America/Mexico_City",
    "CN": "Asia/Shanghai", "ES": "Europe/Madrid", "PT": "Europe/Lisbon",
    "ID": "Asia/Jakarta", "KZ": "Asia/Almaty", "AR": "America/Argentina/Buenos_Aires",
    "CL": "America/Santiago", "NZ": "Pacific/Auckland", "DE": "Europe/Berlin",
}
NAME_ALIASES = {"uk": "GB", "united kingdom": "GB", "england": "GB", "scotland": "GB",
                "wales": "GB", "usa": "US", "united states": "US", "czech republic": "CZ",
                "czechia": "CZ", "russia": "RU", "south korea": "KR", "korea": "KR",
                "the netherlands": "NL", "netherlands": "NL", "switzerland": "CH"}


def _tzdata_dir() -> Path | None:
    try:
        import tzdata
        return Path(tzdata.__file__).parent / "zoneinfo"
    except ImportError:
        for root in ("/usr/share/zoneinfo", "/usr/lib/zoneinfo"):
            if Path(root, "zone.tab").exists():
                return Path(root)
    return None


def _load_tables() -> tuple[dict[str, str], dict[str, str]]:
    zones: dict[str, str] = {}
    names: dict[str, str] = {}
    base = _tzdata_dir()
    if base is None:
        return zones, names
    zone_tab = base / "zone.tab"
    if zone_tab.exists():
        for line in zone_tab.read_text(encoding="utf-8").splitlines():
            if line.startswith("#") or not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) >= 3:
                zones.setdefault(parts[0].upper(), parts[2])
    iso_tab = base / "iso3166.tab"
    if iso_tab.exists():
        for line in iso_tab.read_text(encoding="utf-8").splitlines():
            if line.startswith("#") or "\t" not in line:
                continue
            code, name = line.split("\t", 1)
            names[name.strip().lower()] = code.strip().upper()
    return zones, names


_ZONES, _NAMES = _load_tables()


def country_tz(country) -> ZoneInfo | None:
    """Timezone for an ISO code or country name, or None if unknown."""
    raw = str(country or "").strip()
    if not raw:
        return None
    key = raw.upper() if len(raw) == 2 else (
        NAME_ALIASES.get(raw.lower()) or _NAMES.get(raw.lower(), ""))
    name = TZ_OVERRIDES.get(key) or _ZONES.get(key)
    if not name:
        return None
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return None


def _parse_hhmm(text: str) -> int:
    m = re.fullmatch(r"\s*(\d{1,2})(?::(\d{2}))?\s*", text)
    if not m or int(m.group(1)) > 24 or int(m.group(2) or 0) > 59:
        raise ValueError(f"not a time: {text!r}")
    return int(m.group(1)) * 60 + int(m.group(2) or 0)


class SendWindow:
    """Only let an email go out on a weekday, between `start` and `end` in the
    recipient's local time (from the Country column)."""

    def __init__(self, spec: str, weekends: bool = False):
        try:
            start, end = spec.split("-", 1)
            self.start, self.end = _parse_hhmm(start), _parse_hhmm(end)
        except ValueError as exc:
            raise ValueError(f"--local-window wants e.g. 9-11 or 09:30-11:00, got {spec!r}") from exc
        if self.end <= self.start:
            raise ValueError(f"--local-window end must be after start: {spec!r}")
        self.spec = spec
        self.weekends = weekends

    def tz(self, row: dict) -> ZoneInfo | None:
        return country_tz(row.get("country"))

    def _open(self, local: datetime) -> bool:
        if not self.weekends and local.weekday() >= 5:
            return False
        minute = local.hour * 60 + local.minute
        return self.start <= minute < self.end

    def seconds_until(self, row: dict, now: datetime | None = None) -> float:
        """0 if the row may be sent now, else seconds until its window opens.
        Rows with no usable country are never held back."""
        tz = self.tz(row)
        if tz is None:
            return 0.0
        now = now or datetime.now(timezone.utc)
        local = now.astimezone(tz)
        if self._open(local):
            return 0.0
        for d in range(0, 8):
            day = (local + timedelta(days=d)).date()
            opening = datetime(day.year, day.month, day.day, self.start // 60,
                               self.start % 60, tzinfo=tz)
            if opening > local and (self.weekends or opening.weekday() < 5):
                return (opening - local).total_seconds()
        return 0.0

    def ready(self, row: dict, now: datetime | None = None) -> bool:
        return self.seconds_until(row, now) == 0.0


def parse_at(text: str, now: datetime | None = None) -> datetime:
    """`HH:MM` (today, or tomorrow if already past) or `YYYY-MM-DD HH:MM`, local time."""
    now = now or datetime.now()
    text = text.strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%d-%m-%Y %H:%M"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    minutes = _parse_hhmm(text)
    target = now.replace(hour=minutes // 60 % 24, minute=minutes % 60,
                         second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


def fmt_duration(seconds: float) -> str:
    s = max(0, int(seconds))
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
