"""`coordinators`: one personalised email per internship-programme coordinator.

Reads output/programs/coordinator_outreach.xlsx (sheet "Outreach") and sends only
rows whose `approved` cell is yes, from the main SMTP_* account, each with its
own CV in `attachment path` (never the default ATTACHMENTS). Dry run unless
--send --live; records sent_at and message_id back into the workbook.
"""
from __future__ import annotations

import random
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from .config import settings
from .excel_io import is_writable, load_workbook, save_workbook
from .mailer import Mailer
from .schedule import SendWindow, fmt_duration

SHEET = "Outreach"
COLUMNS = ["id", "programme", "contact name", "role", "email", "source_url", "subject",
           "body", "attachment path", "approved", "sent_at", "notes", "country", "message_id"]
YES = {"yes", "y", "true", "1", "x", "approved"}
DEFAULT_WINDOW = "9-17"


def default_xlsx() -> Path:
    return settings.output_dir / "programs" / "coordinator_outreach.xlsx"


def load_rows(path: str | Path, sheet: str = SHEET) -> list[dict]:
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb[sheet]
        values = list(ws.iter_rows(values_only=True))
    finally:
        wb.close()
    if not values:
        return []
    header = [str(h or "").strip().lower() for h in values[0]]
    missing = [c for c in ("id", "email", "subject", "body", "attachment path", "approved")
               if c not in header]
    if missing:
        raise ValueError(f"{path} [{sheet}] lacks column(s): {', '.join(missing)}")
    rows = []
    for n, raw in enumerate(values[1:], start=2):
        row = {h: ("" if v is None else v) for h, v in zip(header, raw) if h}
        if not any(str(v).strip() for v in row.values()):
            continue
        row["_row"] = n
        rows.append(row)
    return rows


def is_approved(row: dict) -> bool:
    return str(row.get("approved", "")).strip().lower() in YES


def select(rows: list[dict]) -> list[dict]:
    """Approved, not yet sent, and complete enough to send."""
    return [r for r in rows
            if is_approved(r) and not str(r.get("sent_at", "")).strip()
            and str(r.get("email", "")).strip() and str(r.get("body", "")).strip()]


def build(mailer: Mailer, row: dict):
    """The message for one row, carrying only that row's CV."""
    att = Path(str(row.get("attachment path", "")).strip())
    if not str(att).strip() or str(att) == "." or not att.is_file():
        raise FileNotFoundError(f"attachment not found: {att}")
    base = mailer.s
    mailer.s = replace(base, attachments=[str(att)])
    try:
        return mailer.build_message(str(row["email"]).strip(), str(row.get("contact name", "")).strip(),
                                    str(row["subject"]).strip(), str(row["body"]))
    finally:
        mailer.s = base


def record(path: str | Path, row: dict, sent_at: str, message_id: str, sheet: str = SHEET) -> None:
    wb = load_workbook(path)
    ws = wb[sheet]
    header = [str(c.value or "").strip().lower() for c in ws[1]]
    for col in ("sent_at", "message_id"):
        if col not in header:
            header.append(col)
            ws.cell(row=1, column=len(header), value=col)
    ws.cell(row=row["_row"], column=header.index("sent_at") + 1, value=sent_at)
    ws.cell(row=row["_row"], column=header.index("message_id") + 1, value=message_id)
    save_workbook(wb, path)


def run(path: str | Path, *, send: bool = False, live: bool = False, yes: bool = False,
        window: SendWindow | None = None, wait: bool = False, only: set[str] | None = None,
        s=None, now=None, out=print, ask=input, sleep=None) -> list[dict]:
    """Preview (default), dry-run send (--send) or real send (--send --live)."""
    s = s or settings
    path = Path(path)
    rows = load_rows(path)
    todo = select(rows)
    if only:
        todo = [r for r in todo if str(r.get("id", "")) in only]
    pending = [r for r in rows if not is_approved(r) and str(r.get("email", "")).strip()]
    sent = [r for r in rows if str(r.get("sent_at", "")).strip()]
    out(f" {path.name}: {len(rows)} rows, {len(todo)} approved and unsent, "
        f"{len(sent)} already sent, {len(pending)} awaiting approval (approved=yes)")
    for r in pending:
        out(f"   - not approved: {r.get('id')} -> {r.get('email')}")
    if not todo:
        return []

    dry = not (send and live)
    if send and live:
        if not is_writable(path):
            out(" Workbook is open in another program (Excel?); close it so sent_at can be recorded.")
            return []
        if not yes and ask(f" Send {len(todo)} REAL email(s) to programme coordinators from "
                           f"{s.smtp_from}? [Y/N]: ").strip().lower() not in {"y", "yes"}:
            out(" Cancelled; nothing sent.")
            return []

    # Mailer(profile=None): the body carries its own sign-off, so no second signature.
    mailer = Mailer(replace(s, attachments=[]), dry_run=dry)
    results = []
    try:
        for i, row in enumerate(todo):
            rid = row.get("id")
            try:
                msg = build(mailer, row)
                mailer._guard(msg)
            except FileNotFoundError as exc:
                out(f"   SKIP {rid}: {exc}")
                results.append({"id": rid, "status": "skipped: missing attachment"})
                continue
            except ValueError as exc:
                out(f"   SKIP {rid}: {exc}")
                results.append({"id": rid, "status": "skipped: self-funding offer"})
                continue
            names = [p.get_filename() for p in msg.iter_attachments()]
            target = {"country": row.get("country", "")}
            wait_s = window.seconds_until(target, now) if window else 0.0
            if wait_s:
                if dry or not wait:
                    out(f"   {'WOULD WAIT' if dry else 'LATER'} {rid}: recipient window "
                        f"({window.spec} local, weekdays) opens in {fmt_duration(wait_s)}")
                    if not dry:
                        results.append({"id": rid, "status": "outside window"})
                        continue
                else:
                    mailer.close()
                    (sleep or mailer._countdown)(wait_s)
            if dry:
                out(f"   DRY-RUN {rid} -> {row['email']} | {row['subject']} | {', '.join(names)}")
                results.append({"id": rid, "status": "dry-run", "message": msg})
                continue
            try:
                mailer.deliver(msg)
            except Exception as exc:
                out(f"   FAILED {rid}: {type(exc).__name__}: {str(exc)[:160]}")
                results.append({"id": rid, "status": f"failed: {type(exc).__name__}"})
                continue
            stamp = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S%z")
            record(path, row, stamp, msg["Message-ID"])
            out(f"   SENT {rid} -> {row['email']} ({', '.join(names)})")
            results.append({"id": rid, "status": "sent", "message": msg})
            if i < len(todo) - 1 and s.send_delay_max:
                (sleep or mailer._countdown)(random.uniform(s.send_delay_min, s.send_delay_max))
    finally:
        mailer.close()
    n = sum(r["status"] == ("dry-run" if dry else "sent") for r in results)
    skipped = len(results) - n
    out(f" {'Dry run: ' + str(n) + ' message(s) built, nothing sent' if dry else 'Sent ' + str(n) + ' email(s)'}"
        f"{f'; {skipped} skipped/held' if skipped else ''}.")
    return results


def cmd_coordinators(args) -> int:
    settings.ensure_dirs()
    path = Path(args.xlsx) if args.xlsx else default_xlsx()
    if not path.exists():
        print(f" No workbook at {path}")
        return 1
    if args.live and not args.send:
        print(" --live only makes sense with --send; previewing instead.")
    spec = args.local_window or DEFAULT_WINDOW
    window = None if spec.strip().lower() in {"", "any", "off", "none"} else SendWindow(spec, args.weekends)
    results = run(path, send=args.send, live=args.live and args.send, yes=args.yes,
                  window=window, wait=args.wait, only=set(args.only or []) or None)
    return 1 if any(r["status"].startswith("failed") for r in results) else 0
