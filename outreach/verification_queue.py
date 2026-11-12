"""Persist send-time verification holds; network verification is an explicit later job."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile

from .queue_store import _lock, legacy_operation, workbook_operation, QueueBusy


def _read(path):
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Invalid verification queue: {path}")
    return data


def _save(path, data):
    fd, name = tempfile.mkstemp(prefix=".verification-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, indent=2, ensure_ascii=False)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


@contextmanager
def store(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    with _lock(output / ".verification_queue.lock", timeout=10):
        path = output / "verification_queue.json"
        data = _read(path)
        yield data
        _save(path, data)


def defer_rows(output, workbook, rows, guard=None, allow_unverified=False):
    """Return sendable rows; enqueue holds once. No DNS, SMTP probes or web searches."""
    ready, held = [], []
    for row in rows:
        if str(row.get("send_status", "")).lower() in {"sent", "review-sent"}:
            ready.append(row)
            continue
        reason = ""
        if not str(row.get("email", "")).strip():
            reason = "missing email address"
        elif not allow_unverified and str(row.get("email_status", "")).strip().lower() != "ok":
            reason = "email status is not verified ok"
        elif guard is not None:
            problem = guard.permanent_reason(row, allow_unverified=allow_unverified)
            if problem.startswith("skipped: name/email mismatch"):
                reason = problem
        if reason:
            held.append((row, reason))
        else:
            ready.append(row)
    if held:
        with store(output) as queue:
            for row, reason in held:
                item = {key: row.get(key, "") for key in
                        ("sheet", "row", "name", "email", "institution", "country")}
                item["workbook"] = str(Path(workbook).resolve())
                identity = [item["workbook"], item["sheet"], str(item["name"]).casefold(),
                            str(item["email"]).strip().casefold()]
                key = hashlib.sha256(json.dumps(identity).encode()).hexdigest()
                if key not in queue:
                    queue[key] = {**item, "reason": reason, "status": "pending",
                                  "queued_at": datetime.now(timezone.utc).isoformat()}
        print(f" Deferred {len(held)} unverified recipient(s); continuing with verified rows. "
              "Saved in verification_queue.json (duplicates ignored).")
    return ready


def verify_deferred(output, verify, *, apply=False, dry_run=False, workbook=None,
                    sheet=None, top=None, retry=False):
    """Verify queued rows separately; never change a workbook owned by a sender."""
    from .excel_io import load_workbook, save_workbook, _find_header_row, _column_index
    from .models import Professor
    output = Path(output)
    queue_path = output / "verification_queue.json"
    with _lock(output / ".verification_worker.lock", timeout=0):
        snapshot = _read(queue_path)
        selected = [(key, item) for key, item in snapshot.items()
                    if item["status"] == "pending" or (retry and item["status"] == "needs_review")]
        if workbook:
            selected = [(k, i) for k, i in selected
                        if Path(i["workbook"]).resolve() == Path(workbook).resolve()]
        if sheet:
            selected = [(k, i) for k, i in selected if i["sheet"] == sheet]
        if top is not None:
            if top < 1:
                raise ValueError("--top must be at least 1")
            selected = selected[:top]
        if dry_run:
            print(f" Deferred verification preview: {len(selected)} recipient(s); no network or writes.")
            return 0
        groups = {}
        for key, item in selected:
            groups.setdefault(item["workbook"], []).append((key, item))
        busy = False
        for filename, items in groups.items():
            path = Path(filename)
            legacy = path.name.lower() == "legacy.xlsx"
            lock = legacy_operation if legacy else workbook_operation
            try:
                with lock(path.parent, timeout=0):
                    book = load_workbook(path)
                    try:
                        matched, results = [], {}
                        for key, item in items:
                            if item["sheet"] not in book.sheetnames:
                                results[key] = "stale"
                                continue
                            ws = book[item["sheet"]]
                            header = 1 if legacy else _find_header_row(ws)
                            columns = _column_index(ws, header)
                            name_col = columns.get("name" if legacy else "professor name") or columns.get("name")
                            email_col = columns.get("email" if legacy else "email address") or columns.get("email")
                            if not name_col or not email_col:
                                raise ValueError(f"Missing name/email columns in {filename}: {ws.title}")
                            matches = [r for r in range(header + 1, ws.max_row + 1)
                                       if str(ws.cell(r, name_col).value or "").casefold() == str(item["name"]).casefold()
                                       and str(ws.cell(r, email_col).value or "").strip().casefold()
                                       == str(item["email"]).strip().casefold()]
                            if len(matches) != 1:
                                results[key] = "stale"
                                continue
                            row = matches[0]
                            status_col = columns.get("send status")
                            if status_col and str(ws.cell(row, status_col).value or "").lower() in {"sent", "review-sent"}:
                                results[key] = "already_sent"
                                continue
                            prof = Professor(name=item["name"], email=item["email"],
                                             institution=item["institution"], country=item["country"])
                            matched.append((key, item, ws, row, header, email_col, prof))
                        if matched:
                            verify([m[-1] for m in matched])
                        for key, item, ws, row, header, email_col, prof in matched:
                            columns = _column_index(ws, header)
                            updates = {"Email Status": prof.email_status,
                                       "Email Confidence": prof.email_confidence,
                                       "Email Notes": prof.email_notes,
                                       "Suggested Email": prof.email_suggestion}
                            if apply and prof.email != item["email"]:
                                ws.cell(row, email_col, prof.email)
                                if "approved" in columns:
                                    ws.cell(row, columns["approved"], "")
                            for label, value in updates.items():
                                col = columns.get(label.lower())
                                if col is None:
                                    col = ws.max_column + 1
                                    ws.cell(header, col, label)
                                    columns[label.lower()] = col
                                ws.cell(row, col, value)
                            results[key] = "verified" if prof.email_status == "ok" else "needs_review"
                        if matched:
                            save_workbook(book, path)
                    finally:
                        book.close()
                    with store(output) as current:
                        for key, status in results.items():
                            current[key]["status"] = status
                            current[key]["checked_at"] = datetime.now(timezone.utc).isoformat()
                    print(f" Deferred verification: {path.name}: {len(matched)} checked; "
                          f"{sum(v == 'needs_review' for v in results.values())} need review.")
            except QueueBusy:
                print(f" Deferred verification postponed: {path.name} is in use by a sender.")
                busy = True
        if not selected:
            print(" No pending deferred verifications.")
        return 3 if busy else 0
