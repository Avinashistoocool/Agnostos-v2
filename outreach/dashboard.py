"""Live console dashboard: what each send job is doing, refreshed every few seconds.

    python -m outreach.dashboard
"""
from __future__ import annotations

import csv
import os
import re
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

from .config import settings

LOGS = [("RESEND (Gmail)", "resend_run.log"), ("DAILY SEND (IITD)", "daily_send.log"),
        ("REPLIES", "replies_run.log")]


def _running() -> list[str]:
    try:
        import subprocess
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
             "% { $_.CommandLine }"],
            capture_output=True, text=True, timeout=15).stdout
    except Exception:
        return []
    return [re.sub(r".*outreach\.cli\s+", "", l).strip()
            for l in out.splitlines() if "outreach.cli" in l]


def _tail(path: Path, n: int = 6) -> list[str]:
    if not path.exists():
        return ["(no log yet)"]
    raw = path.read_bytes()
    # PowerShell 5 redirection writes UTF-16; python writes UTF-8.
    enc = "utf-16" if raw[:2] in (b"\xff\xfe", b"\xfe\xff") or raw[1:2] == b"\x00" else "utf-8"
    text = raw.decode(enc, errors="replace")
    lines = [l.rstrip() for l in re.split(r"[\r\n]+", text) if l.strip()]
    return lines[-n:]


def render() -> str:
    out_dir = settings.output_dir
    today = f"{datetime.now():%Y-%m-%d}"
    by_mode, today_mode, recent = Counter(), Counter(), []
    log = out_dir / "send_log.csv"
    if log.exists():
        with log.open(newline="", encoding="utf-8") as fh:
            for rec in csv.DictReader(fh):
                if rec.get("status") != "sent":
                    continue
                by_mode[rec["mode"]] += 1
                if rec.get("time", "").startswith(today):
                    today_mode[rec["mode"]] += 1
                    recent.append(rec)
    # send_log.csv only exists from 19 Oct; the workbook is the full record.
    wb_sent = wb_total = 0
    try:
        from .excel_io import load_for_sending
        rows = load_for_sending(settings.target_xlsx)
        wb_total = len(rows)
        wb_sent = sum(1 for r in rows if r["send_status"].lower() == "sent")
    except Exception:
        pass
    if wb_sent:
        by_mode["live"] = max(by_mode["live"], wb_sent)
    lines = [f" AGNOSTOS DASHBOARD   {datetime.now():%d %b %H:%M:%S}   (Ctrl+C to close)",
             "=" * 78,
             f" Sent today:  first emails {today_mode['live']:>3}   |   "
             f"resends {today_mode['resend']:>3}/{settings.resend_daily_cap}",
             f" All time:    first emails {by_mode['live']:>3}   |   resends {by_mode['resend']:>3}"
             f"   |   drafted, not yet sent {max(0, wb_total - wb_sent):>3}",
             "", " Running jobs:"]
    jobs = _running()
    lines += [f"   * {j[:72]}" for j in jobs] or ["   (none)"]
    for title, name in LOGS:
        p = out_dir / name
        if not p.exists():
            continue
        lines += ["", f" --- {title}  ({name}) " + "-" * max(0, 50 - len(title) - len(name))]
        lines += ["   " + l[:74] for l in _tail(p)]
    lines += ["", " Last 8 delivered today:"]
    for rec in recent[-8:]:
        lines.append(f"   {rec['time'][11:16]}  {rec['mode']:<7} {rec['email'][:36]:<36} "
                     f"{rec.get('name', '')[:20]}")
    if not recent:
        lines.append("   (none yet)")
    return "\n".join(lines)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    interval = float(sys.argv[1]) if len(sys.argv) > 1 else 5
    try:
        while True:
            frame = render()
            os.system("cls" if os.name == "nt" else "clear")
            print(frame, flush=True)
            time.sleep(interval)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
