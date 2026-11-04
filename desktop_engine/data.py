"""Workbook-backed reads/edits: stats, professor list, per-row draft edits, replies."""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import time
import zipfile

from desktop_review.storage import ReviewError, read_queue, update_queue
from outreach.queue_store import QueueBusy, lock_held, workbook_operation

from .errors import EngineError, from_review

SENT = {"sent", "review-sent"}
LOCKS = (".send.lock", ".resend.lock", ".replies.lock", ".legacy.lock", ".desktop_cli.lock")
_edit_lock = threading.RLock()


def workbook_path(accounts) -> Path:
    root = accounts.workspace_path()
    configured = accounts.raw_settings().get("TARGET_XLSX", "").strip()
    if configured:
        path = Path(configured).expanduser()
        if not path.is_absolute():
            path = root / path
        return path.resolve()
    return (root / "output" / "professors.xlsx").resolve()


def _open(path: Path, read_only: bool = True):
    from openpyxl import load_workbook
    for attempt in range(4):
        try:
            return load_workbook(path, read_only=read_only, data_only=read_only)
        except (zipfile.BadZipFile, EOFError, KeyError, PermissionError):
            if attempt == 3:
                raise
            time.sleep(0.3)


def _headers(ws) -> tuple[int, dict[str, int]] | None:
    """(header row, lowercased header -> 0-based index) for a professor sheet."""
    for number, row in enumerate(ws.iter_rows(min_row=1, max_row=20, values_only=True), 1):
        labels = {str(c or "").strip().lower(): i for i, c in enumerate(row) if c is not None}
        if ("professor name" in labels or "name" in labels) and (
                "email address" in labels or "email" in labels or "custom email draft" in labels):
            return number, labels
    return None


def _cell(row, headers, *names) -> str:
    for name in names:
        index = headers.get(name)
        if index is not None and index < len(row) and row[index] is not None:
            return str(row[index]).strip()
    return ""


def _probability(row, headers) -> float:
    raw = _cell(row, headers, "probability of acceptance").rstrip("%").strip()
    try:
        value = float(raw) / 100
    except ValueError:
        try:
            value = float(_cell(row, headers, "local match score") or 0)
        except ValueError:
            value = 0.0
    return max(0.0, min(1.0, value))


def _version(sheet: str, number: int, item: dict) -> str:
    blob = json.dumps([sheet, number, item["name"], item["email"], item["subject"],
                       item["draft"], item["send_status"], item.get("_sent_at", "")],
                      ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


def _pending(path: Path) -> dict:
    from outreach.excel_io import sidecar_path
    side = sidecar_path(path)
    try:
        return {(p["sheet"], p["row"]): p["status"]
                for p in json.loads(side.read_text(encoding="utf-8"))}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def _row_item(sheet: str, number: int, row, headers, pending: dict) -> dict:
    item = {
        "row": number, "sheet": sheet,
        "name": _cell(row, headers, "professor name", "name"),
        "email": _cell(row, headers, "email address", "email"),
        "institution": _cell(row, headers, "institution", "university"),
        "country": _cell(row, headers, "country"),
        "probability": _probability(row, headers),
        "send_status": str(pending.get((sheet, number)) or _cell(row, headers, "send status")),
        "reply_status": _cell(row, headers, "reply status"),
        "subject": _cell(row, headers, "email subject"),
        "draft": _cell(row, headers, "custom email draft"),
        "_sent_at": _cell(row, headers, "sent at"),
        "_resent": _cell(row, headers, "resent at"),
    }
    item["version"] = _version(sheet, number, item)
    return item


def read_rows(accounts) -> list[dict]:
    path = workbook_path(accounts)
    if not path.is_file():
        return []
    pending = _pending(path)
    try:
        book = _open(path)
    except (OSError, ValueError, KeyError, EOFError, zipfile.BadZipFile) as exc:
        raise EngineError("unavailable", f"Workbook unavailable: {type(exc).__name__}") from exc
    rows = []
    try:
        for ws in book.worksheets:
            found = _headers(ws)
            if not found:
                continue
            header_row, headers = found
            for number, row in enumerate(ws.iter_rows(min_row=header_row + 1, values_only=True),
                                         header_row + 1):
                item = _row_item(ws.title, number, row, headers, pending)
                if item["name"] or item["email"]:
                    rows.append(item)
    finally:
        book.close()
    return rows


def public(item: dict) -> dict:
    return {k: v for k, v in item.items() if not k.startswith("_")}


def stats(accounts) -> dict:
    rows = read_rows(accounts)
    per_day = Counter()
    for item in rows:
        if item["send_status"].lower() == "sent" and item["_sent_at"][:10]:
            per_day[item["_sent_at"][:10]] += 1
    today = date.today()
    days = [(today - timedelta(days=offset)).isoformat() for offset in range(29, -1, -1)]
    return {
        "total": len(rows),
        "with_email": sum(1 for r in rows if r["email"]),
        "drafted": sum(1 for r in rows if r["draft"]),
        "sent": sum(1 for r in rows if r["send_status"].lower() in SENT),
        "replied": sum(1 for r in rows if r["reply_status"].lower().startswith("replied")),
        "bounced": sum(1 for r in rows if r["reply_status"].lower().startswith("bounced")),
        "resends": sum(1 for r in rows if r["_resent"]),
        "sent_per_day": [{"date": d, "count": per_day.get(d, 0)} for d in days],
    }


def _matches_status(item: dict, status: str) -> bool:
    send = item["send_status"].lower()
    reply = item["reply_status"].lower()
    if status == "unsent":
        return send not in SENT
    if status == "sent":
        return send in SENT
    if status == "replied":
        return reply.startswith("replied")
    if status == "failed":
        return send.startswith("failed") or reply.startswith("bounced")
    return True


def list_professors(accounts, query=None, status=None, offset=None, limit=None) -> dict:
    query = "" if query is None else query
    status = "" if status is None else status
    offset = 0 if offset is None else offset
    limit = 200 if limit is None else limit
    if not isinstance(query, str) or len(query) > 200 or not isinstance(status, str):
        raise EngineError("bad_request", "Invalid query")
    if status not in ("", "all", "unsent", "sent", "replied", "failed"):
        raise EngineError("bad_request", "status must be unsent, sent, replied or failed")
    for name, value in (("offset", offset), ("limit", limit)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise EngineError("bad_request", f"{name} must be a non-negative integer")
    limit = min(limit, 1000)
    needle = query.strip().lower()
    items = [r for r in read_rows(accounts) if _matches_status(r, status) and (
        not needle or any(needle in r[k].lower() for k in ("name", "email", "institution", "country")))]
    items.sort(key=lambda r: -r["probability"])
    return {"items": [public(r) for r in items[offset:offset + limit]], "total": len(items)}


def update_draft(accounts, sheet, row, version, draft, subject=None) -> dict:
    if (not isinstance(sheet, str) or not sheet or len(sheet) > 31
            or isinstance(row, bool) or not isinstance(row, int) or row < 2
            or not isinstance(version, str) or not version
            or not isinstance(draft, str) or not draft.strip() or len(draft) > 30000
            or (subject is not None and (not isinstance(subject, str) or len(subject) > 300
                                         or re.search(r"[\r\n]", subject)))):
        raise EngineError("bad_request", "Invalid draft edit")
    path = workbook_path(accounts)
    if not path.is_file():
        raise EngineError("not_found", "No professors workbook in this workspace yet")
    workspace = accounts.workspace()
    if not workspace.coordinated_workbook():
        raise EngineError("conflict", "Update this workspace's CLI before editing drafts")
    output = workspace.path / "output"
    try:
        with _edit_lock, workbook_operation(output):
            if any(lock_held(output / name) for name in LOCKS):
                raise EngineError("conflict", "A CLI job is active; retry after it finishes")
            pending = _pending(path)
            before = hashlib.sha256(path.read_bytes()).digest()
            book = _open(path, read_only=False)
            try:
                if sheet not in book.sheetnames:
                    raise EngineError("not_found", "Sheet not found")
                ws = book[sheet]
                found = _headers(ws)
                if not found or row <= found[0] or row > ws.max_row:
                    raise EngineError("not_found", "Row not found")
                header_row, headers = found
                values = [c.value for c in ws[row]]
                item = _row_item(sheet, row, values, headers, pending)
                if item["send_status"].lower() in SENT or item["_sent_at"]:
                    raise EngineError("conflict", "This email was already sent; it can't be edited")
                if item["version"] != version:
                    raise EngineError("conflict", "The sheet changed since you opened this draft; reload")
                if "custom email draft" not in headers:
                    raise EngineError("conflict", "This sheet has no Custom Email Draft column")
                ws.cell(row, headers["custom email draft"] + 1, draft)
                if subject is not None:
                    if "email subject" not in headers:
                        raise EngineError("conflict", "This sheet has no Email Subject column")
                    ws.cell(row, headers["email subject"] + 1, subject)
                temp = path.with_name(f"~{path.stem}.engine-{os.getpid()}.tmp.xlsx")
                try:
                    book.save(temp)
                    if hashlib.sha256(path.read_bytes()).digest() != before:
                        raise EngineError("conflict", "Workbook changed while saving; reload")
                    for attempt in range(10):
                        try:
                            os.replace(temp, path)
                            break
                        except PermissionError:
                            if attempt == 9:
                                raise EngineError("conflict", "Workbook is open in another program (Excel?)")
                            time.sleep(0.2)
                finally:
                    temp.unlink(missing_ok=True)
            finally:
                book.close()
    except QueueBusy as exc:
        raise EngineError("conflict", str(exc)) from exc
    except (OSError, zipfile.BadZipFile) as exc:
        raise EngineError("unavailable", f"Workbook unavailable: {type(exc).__name__}") from exc
    for item in read_rows(accounts):
        if item["sheet"] == sheet and item["row"] == row:
            return public(item)
    raise EngineError("not_found", "Row not found after saving")


# ---------- replies / conversations ----------

def replies(accounts) -> dict:
    try:
        data = read_queue(accounts.workspace())
    except ReviewError as exc:
        raise from_review(exc) from exc
    items = []
    for index, item in enumerate(data["items"]):
        items.append({"index": index, "name": str(item.get("name") or ""),
                      "email": str(item.get("email") or ""),
                      "subject": str(item.get("subject") or ""),
                      "their_message": str(item.get("their_message") or ""),
                      "summary": str(item.get("summary") or ""),
                      "action": str(item.get("action") or ""),
                      "body": str(item.get("body") or ""),
                      "approved": bool(item.get("approved")),
                      "sent_at": item.get("sent_at") or None})
    return {"items": items, "version": data["version"]}


def update_reply(accounts, index, version, body, approved) -> dict:
    if isinstance(index, bool):
        raise EngineError("bad_request", "Invalid reply index")
    try:
        return update_queue(accounts.workspace(), index, version, body, approved)
    except ReviewError as exc:
        raise from_review(exc) from exc


def conversations(accounts) -> dict:
    path = accounts.workspace_path() / "output" / "conversations.html"
    try:
        html = path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return {"html": "", "modified": None}
    modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")
    return {"html": html, "modified": modified}
