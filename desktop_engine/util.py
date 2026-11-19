"""Small shared helpers: data dir, atomic writes, DPAPI, .env editing, HTTP."""
from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import re
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from .errors import EngineError


def data_dir() -> Path:
    override = os.getenv("AGNOSTOS_DATA_DIR")
    if override:
        path = Path(override)
    elif sys.platform == "darwin":
        path = Path.home() / "Library" / "Application Support" / "Agnostos"
    else:
        base = os.getenv("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        path = Path(base) / "Agnostos"
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.new")
    try:
        with pending.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        for attempt in range(20):
            try:
                os.replace(pending, path)
                return
            except PermissionError:
                if attempt == 19:
                    raise
                time.sleep(0.1)
    finally:
        pending.unlink(missing_ok=True)


def write_json(path: Path, value) -> None:
    atomic_write_bytes(path, json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8"))


def read_json(path: Path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return default
    except (OSError, ValueError) as exc:
        raise EngineError("internal", f"{Path(path).name} is unreadable: {exc}") from exc


# ---------- DPAPI (current-user scope) ----------

if os.name == "nt":
    from ctypes import wintypes

    class _Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    _crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    for _fn in (_crypt32.CryptProtectData, _crypt32.CryptUnprotectData):
        _fn.argtypes = [ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.POINTER(_Blob),
                        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob)]
        _fn.restype = wintypes.BOOL
    _kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    _kernel32.LocalFree.restype = ctypes.c_void_p

    def _dpapi(data: bytes, protect: bool) -> bytes:
        buffer = ctypes.create_string_buffer(data, len(data))
        blob_in = _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
        blob_out = _Blob()
        fn = _crypt32.CryptProtectData if protect else _crypt32.CryptUnprotectData
        if not fn(ctypes.byref(blob_in), None, None, None, None, 0x1, ctypes.byref(blob_out)):
            raise OSError(ctypes.get_last_error(), "DPAPI call failed")
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            _kernel32.LocalFree(blob_out.pbData)
elif sys.platform == "darwin":
    import base64
    import subprocess

    _KC_SERVICE = "Agnostos"
    _KC_PREFIX = b"keychain:"

    def _dpapi(data: bytes, protect: bool) -> bytes:
        # macOS: the secret itself lives in the login Keychain; the file holds only a handle.
        if protect:
            account = secrets.token_hex(16)
            subprocess.run(["security", "add-generic-password", "-U", "-s", _KC_SERVICE,
                            "-a", account, "-w", base64.b64encode(data).decode("ascii")],
                           check=True, capture_output=True)
            return _KC_PREFIX + account.encode("ascii")
        if not data.startswith(_KC_PREFIX):
            raise OSError("Not a Keychain handle")
        account = data[len(_KC_PREFIX):].decode("ascii")
        out = subprocess.run(["security", "find-generic-password", "-s", _KC_SERVICE,
                              "-a", account, "-w"], capture_output=True, text=True)
        if out.returncode != 0:
            raise OSError("Keychain item not found")
        return base64.b64decode(out.stdout.strip())
else:  # pragma: no cover
    def _dpapi(data: bytes, protect: bool) -> bytes:
        raise OSError("Secure token storage requires Windows or macOS")


def protect(data: bytes) -> bytes:
    return _dpapi(data, True)


def unprotect(data: bytes) -> bytes:
    return _dpapi(data, False)


# ---------- .env files ----------

KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_LINE_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")


def read_env(path: Path) -> dict[str, str]:
    path = Path(path)
    if not path.is_file():
        return {}
    from dotenv import dotenv_values
    return {k: (v or "") for k, v in dotenv_values(path, interpolate=False).items()}


def _quote(value: str) -> str:
    if value == "" or (value == value.strip() and not re.search(r"\s#|^#|^['\"]", value)):
        return value
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def update_env(path: Path, changes: dict[str, str | None]) -> None:
    """Rewrite only the changed keys; comments and other lines stay intact."""
    path = Path(path)
    for key, value in changes.items():
        if not KEY_RE.fullmatch(key):
            raise EngineError("bad_request", f"Invalid setting name: {key}")
        if value is not None and (not isinstance(value, str) or re.search(r"[\r\n\x00]", value)):
            raise EngineError("bad_request", f"Invalid value for {key}")
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines() if path.is_file() else []
    except OSError as exc:
        raise EngineError("unavailable", f"Cannot read {path}: {exc}") from exc
    pending = dict(changes)
    out = []
    for line in lines:
        match = _LINE_RE.match(line)
        key = match.group(1) if match else None
        if key in changes:
            if key in pending and pending[key] is not None:
                out.append(f"{key}={_quote(pending[key])}")
            pending.pop(key, None)
            continue
        out.append(line)
    for key, value in pending.items():
        if value is not None:
            out.append(f"{key}={_quote(value)}")
    atomic_write_bytes(path, ("\n".join(out) + "\n").encode("utf-8"))


# ---------- HTTP ----------

def http_json(url: str, data: dict | None = None, headers: dict | None = None,
              timeout: float = 30) -> tuple[int, dict]:
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    request = urllib.request.Request(url, data=body, method="POST" if body else "GET",
                                     headers={"Accept": "application/json",
                                              "User-Agent": "Agnostos-Desktop",
                                              **(headers or {})})
    if body:
        request.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        if url.startswith("https:"):
            from outreach.tls import urlopen
            response = urlopen(request, timeout=timeout)
        else:
            response = urllib.request.urlopen(request, timeout=timeout)
        with response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read()
    except (urllib.error.URLError, OSError) as exc:
        raise EngineError("unavailable", f"Network error contacting {urllib.parse.urlsplit(url).netloc}: "
                          f"{getattr(exc, 'reason', exc)}") from exc
    try:
        payload = json.loads(raw.decode("utf-8") or "{}")
    except ValueError:
        payload = {}
    return status, payload if isinstance(payload, dict) else {"value": payload}


def log(message: str) -> None:
    print(f"[engine] {message}", file=sys.stderr, flush=True)
