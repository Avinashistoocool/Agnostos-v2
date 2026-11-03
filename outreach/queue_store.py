"""Coordinated reply-queue updates shared by the CLI and desktop reviewer."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import secrets
import threading
import time

from .locks import AlreadyRunning, InstanceLock


class QueueBusy(RuntimeError):
    pass


class QueueChanged(RuntimeError):
    pass


@contextmanager
def _lock(path: Path, timeout: float):
    deadline = time.monotonic() + timeout
    while True:
        lock = InstanceLock(path)
        try:
            lock.__enter__()
            break
        except AlreadyRunning:
            if time.monotonic() >= deadline:
                raise QueueBusy("Reply queue is in use; retry after it finishes") from None
            time.sleep(0.05)
    try:
        yield
    finally:
        lock.__exit__(None, None, None)


def queue_operation(output_dir: Path, timeout: float = 0):
    """Keep edits out of a CLI replies job from its initial read through its last save."""
    return _lock(Path(output_dir) / ".reply_queue.operation.lock", timeout)


def workbook_operation(output_dir: Path, timeout: float = 0):
    """Serialize CLI workbook jobs with native per-row draft edits."""
    return _lock(Path(output_dir) / ".desktop_workbook.operation.lock", timeout)


def lock_held(path: Path) -> bool:
    """Non-mutating probe for an OS-level InstanceLock owned by another process."""
    path = Path(path)
    if not path.exists():
        return False
    with path.open("r+b") as handle:
        acquired = False
        try:
            if os.name == "nt":
                import msvcrt
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except OSError:
            return True
        finally:
            if acquired:
                if os.name == "nt":
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    return False


def live_replies_running(output_dir: Path) -> bool:
    return lock_held(Path(output_dir) / ".replies.lock")


def write_queue(path: Path, data: bytes, expected: str | None = None) -> str:
    """Atomically replace a queue under a cross-process lock; optionally compare revision."""
    path = Path(path)
    with _lock(path.with_name(".reply_queue.write.lock"), timeout=10):
        try:
            before = path.read_bytes()
        except FileNotFoundError:
            before = b"[]"
        if expected is not None and hashlib.sha256(before).hexdigest() != expected:
            raise QueueChanged("Queue changed on disk; reload before saving")
        pending = path.with_name(
            f".reply_queue.{os.getpid()}.{threading.get_ident()}.{secrets.token_hex(4)}.new")
        try:
            with pending.open("xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            for attempt in range(10):
                try:
                    os.replace(pending, path)
                    break
                except PermissionError:
                    if attempt == 9:
                        raise
                    time.sleep(0.1)
        finally:
            pending.unlink(missing_ok=True)
    return hashlib.sha256(data).hexdigest()
