"""Strictly workspace-scoped reads and one-field-at-a-time reply review."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import time
import zipfile

from openpyxl import load_workbook
from outreach.queue_store import (
    QueueBusy, QueueChanged, live_replies_running, queue_operation, write_queue,
)


class ReviewError(Exception):
    def __init__(self, status: int, message: str):
        self.status = status
        super().__init__(message)


class Workspace:
    def __init__(self, config_dir: Path):
        self.config_dir = config_dir
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.path: Path | None = None
        config = self.config_dir / "workspace.json"
        if config.exists():
            try:
                self.path = self.validate(json.loads(config.read_text(encoding="utf-8"))["path"])
            except (OSError, ValueError, KeyError, TypeError, ReviewError):
                pass

    @staticmethod
    def validate(value: str) -> Path:
        if not isinstance(value, str) or not value.strip():
            raise ReviewError(400, "Choose an existing Agnostos-v2 repository folder")
        path = Path(value).expanduser().resolve()
        if not (path.is_dir() and (path / "outreach" / "cli.py").is_file()
                and (path / "output").is_dir()):
            raise ReviewError(400, "Folder must contain outreach/cli.py and output/")
        output = (path / "output").resolve()
        if not output.is_relative_to(path):
            raise ReviewError(400, "Output must remain inside the selected workspace")
        return path

    def select(self, value: str) -> Path:
        path = self.validate(value)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        target = self.config_dir / "workspace.json"
        pending = self.config_dir / "workspace.json.new"
        pending.write_text(json.dumps({"path": str(path)}), encoding="utf-8")
        os.replace(pending, target)
        with self._lock:
            self.path = path
        return path

    def file(self, filename: str) -> Path:
        with self._lock:
            if self.path is None:
                raise ReviewError(409, "Select a workspace first")
            workspace = self.validate(str(self.path))
            output = (workspace / "output").resolve()
            path = (output / filename).resolve()
            if not path.is_relative_to(output) or not path.is_relative_to(workspace):
                raise ReviewError(403, "Workspace file escapes output/")
            return path

    def coordinated_cli(self) -> bool:
        with self._lock:
            if self.path is None:
                return False
            sources = self.path / "outreach"
            try:
                return ((sources / "queue_store.py").is_file()
                        and "queue_operation(settings.output_dir" in
                        (sources / "cli.py").read_text(encoding="utf-8")
                        and "write_queue(path," in
                        (sources / "replier.py").read_text(encoding="utf-8"))
            except OSError:
                return False


def statistics(workspace: Workspace) -> dict:
    path = workspace.file("professors.xlsx")
    if not path.is_file():
        raise ReviewError(404, "No output/professors.xlsx in this workspace")
    pending = {}
    sidecar = workspace.file("professors.xlsx.pending-status.json")
    if sidecar.exists():
        try:
            pending = {(item["sheet"], item["row"]): item["status"]
                       for item in json.loads(sidecar.read_text(encoding="utf-8"))}
        except (OSError, ValueError, TypeError, KeyError):
            pending = {}
    try:
        for attempt in range(3):
            try:
                book = load_workbook(path, read_only=True, data_only=True)
                break
            except (zipfile.BadZipFile, EOFError, KeyError, PermissionError):
                if attempt == 2:
                    raise
                time.sleep(0.25)
        counts = Counter()
        statuses = Counter()
        try:
            for sheet in book:
                rows = sheet.iter_rows(values_only=True)
                header = None
                for number, row in enumerate(rows, 1):
                    labels = {str(cell or "").strip().lower(): i for i, cell in enumerate(row)}
                    if "custom email draft" in labels and (
                        "professor name" in labels or "name" in labels
                    ):
                        header = labels
                        break
                    if number >= 20:
                        break
                if header is None:
                    continue
                for row_index, row in enumerate(rows, number + 1):
                    def cell(*names):
                        for name in names:
                            index = header.get(name)
                            if index is not None and index < len(row):
                                return str(row[index] or "").strip()
                        return ""
                    if not (cell("professor name", "name") or cell("email address", "email")):
                        continue
                    counts["total"] += 1
                    if cell("email address", "email"):
                        counts["with_email"] += 1
                    if cell("custom email draft"):
                        counts["drafted"] += 1
                    status = str(pending.get((sheet.title, row_index))
                                 or cell("send status")).strip().lower()
                    if status:
                        statuses[status] += 1
        finally:
            book.close()
    except (OSError, ValueError, KeyError, EOFError, zipfile.BadZipFile) as exc:
        raise ReviewError(503, f"Workbook unavailable: {type(exc).__name__}") from exc
    return {"counts": {key: counts[key] for key in ("total", "with_email", "drafted")},
            "sent": statuses["sent"], "review_sent": statuses["review-sent"],
            "send_statuses": dict(statuses), "modified": path.stat().st_mtime}


def _queue(workspace: Workspace) -> tuple[Path, bytes, list[dict]]:
    path = workspace.file("reply_queue.json")
    try:
        raw = path.read_bytes()
        items = json.loads(raw)
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            raise ValueError("Invalid reply queue")
        return path, raw, items
    except FileNotFoundError:
        return path, b"[]", []
    except (OSError, ValueError) as exc:
        raise ReviewError(503, f"Reply queue unavailable: {type(exc).__name__}") from exc


def read_queue(workspace: Workspace) -> dict:
    with workspace._lock:
        _, raw, items = _queue(workspace)
    return {"version": hashlib.sha256(raw).hexdigest(),
            "items": [{key: value for key, value in item.items()
                       if key in {"name", "email", "subject", "their_message", "summary",
                                  "action", "body", "approved", "drafted_at", "sent_at"}}
                      for item in items]}


def update_queue(workspace: Workspace, index: int, version: str, body: str,
                 approved: bool) -> dict:
    if (not isinstance(index, int) or index < 0 or not isinstance(version, str)
            or not re.fullmatch(r"[a-f0-9]{64}", version)
            or not isinstance(body, str) or not isinstance(approved, bool)):
        raise ReviewError(400, "Invalid review request")
    if not body.strip() or len(body) > 20000:
        raise ReviewError(400, "Draft body must be 1–20000 characters")
    with workspace._lock:
        if not workspace.coordinated_cli():
            raise ReviewError(409, "Update this workspace's v2 CLI before editing reply drafts")
        try:
            path = workspace.file("reply_queue.json")
            with queue_operation(path.parent):
                if live_replies_running(path.parent):
                    raise ReviewError(409, "Reply sending is active; reload after it finishes")
                _, raw, items = _queue(workspace)
                if hashlib.sha256(raw).hexdigest() != version:
                    raise ReviewError(409, "Queue changed on disk; reload before saving")
                if index >= len(items):
                    raise ReviewError(404, "Reply draft not found")
                item = items[index]
                if item.get("sent_at"):
                    raise ReviewError(409, "Sent replies cannot be changed")
                if approved and item.get("action") in ("none", None, ""):
                    raise ReviewError(400, "This draft has no sendable action")
                item["body"] = body
                item["approved"] = approved
                fresh = json.dumps(items, ensure_ascii=False, indent=2).encode("utf-8")
                return {"version": write_queue(path, fresh, expected=version)}
        except (QueueBusy, QueueChanged) as exc:
            raise ReviewError(409, str(exc)) from exc
        except OSError as exc:
            raise ReviewError(409, f"Cannot save queue: {type(exc).__name__}") from exc
