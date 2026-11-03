"""Strict recipient, focus, window and daily-cap gate for legacy live letters."""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

from .focus import in_focus
from .schedule import SendWindow, country_tz


def plan_legacy_live(rows: list[dict], log_path: Path, *,
                     daily_cap: int, limit: int, window_spec: str,
                     focus_keywords: str = "", now: datetime | None = None,
                     history_rows: list[dict] | None = None):
    if not window_spec or window_spec.lower() in {"off", "any", "none"}:
        raise ValueError("Legacy live mail requires recipient-local hours (e.g. 9-17)")
    window = SendWindow(window_spec)
    now = now or datetime.now(timezone.utc)
    today = now.astimezone().date().isoformat()
    already_sent, today_sent = set(), set()
    if log_path.is_file():
        with log_path.open(newline="", encoding="utf-8") as handle:
            for record in csv.DictReader(handle):
                mode = record.get("mode")
                if mode not in {"legacy", "resend"} or record.get("status") != "sent":
                    continue
                address = record.get("email", "").lower().strip()
                if address:
                    if mode == "legacy":
                        already_sent.add(address)
                    if record.get("time", "").startswith(today):
                        today_sent.add((mode, address))
    for row in history_rows if history_rows is not None else rows:
        if str(row.get("Send Status", "")).lower() == "sent":
            address = str(row.get("Email", "")).lower().strip()
            already_sent.add(address)
            if str(row.get("Sent At", "")).startswith(today):
                today_sent.add(("legacy", address))
    room = max(0, min(daily_cap, 40) - len(today_sent))
    eligible, held, selected = [], [], set()
    for row in rows:
        email = str(row.get("Email", "")).lower().strip()
        country = row.get("Country") or (email.rsplit(".", 1)[-1].upper()
                                         if len(email.rsplit(".", 1)[-1]) == 2 else "")
        focus_row = {
            "research_area": f"{row.get('Known for', '')} {row.get('Recent work', '')}",
            "institution": row.get("Institution", ""),
        }
        why = ""
        if not email or email in already_sent:
            why = "already delivered or missing address"
        elif email in selected:
            why = "duplicate recipient in this run"
        elif str(row.get("Email Status", "")).lower().strip() != "ok":
            why = "address not verified ok"
        elif not in_focus(focus_row, focus_keywords):
            why = "outside selected research focus"
        elif not country_tz(country):
            why = "recipient timezone unknown"
        elif not window.ready({"country": country}, now):
            why = "outside recipient's weekday local window"
        elif len(eligible) >= min(limit, room):
            why = "daily cap or run limit reached"
        if why:
            held.append((row, why))
        else:
            eligible.append(row)
            selected.add(email)
    return eligible, held, window, room
