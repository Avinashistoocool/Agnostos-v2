"""Single-instance locks for commands that send mail.

A scheduled task, a looping launcher and a hand-typed command can all start
`send` at once. Two senders reading the same workbook would mail the same
rows twice, so each sending command takes an OS-level lock on a file in the
output directory. The OS releases it when the process exits, even on a crash,
so a stale lock can never block future runs.
"""
from __future__ import annotations

import os
from pathlib import Path


class AlreadyRunning(RuntimeError):
    pass


class InstanceLock:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._fh = None

    def __enter__(self) -> "InstanceLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self.path, "a+")
        try:
            if os.name == "nt":
                import msvcrt
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            try:
                fh.seek(0)
                holder = fh.read().strip()
            except OSError:  # Windows refuses to read a region another process locked
                holder = ""
            fh.close()
            raise AlreadyRunning(holder or "another process") from None
        fh.seek(0)
        fh.truncate()
        fh.write(f"pid {os.getpid()}")
        fh.flush()
        self._fh = fh
        return self

    def __exit__(self, *exc) -> None:
        if self._fh:
            try:
                if os.name == "nt":
                    import msvcrt
                    self._fh.seek(0)
                    msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
            self._fh.close()
            self._fh = None
