"""Gmail over OAuth 2.0 (XOAUTH2) instead of an app password.

The desktop app's "Sign in with Google + connect Gmail" flow writes a token
file (GOOGLE_OAUTH_TOKEN_FILE) holding a long-lived refresh token:

    {"client_id": "...", "client_secret": "...", "refresh_token": "...",
     "token_uri": "https://oauth2.googleapis.com/token"}   # token_uri optional

Here we trade that refresh token for short-lived access tokens, cache them in
memory until shortly before expiry, and build the SASL XOAUTH2 string that
Gmail's SMTP and IMAP servers accept.
"""
from __future__ import annotations

import base64
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import tls
from .config import ConfigError

DEFAULT_TOKEN_URI = "https://oauth2.googleapis.com/token"
# Refresh this many seconds before Google says the token expires.
EXPIRY_MARGIN = 60
RECONNECT_HINT = "Open the Agnostos app and reconnect Gmail (Settings > Sign in with Google)."

_lock = threading.Lock()
# (token file path, refresh token) -> (access_token, monotonic expiry). Keying on
# the refresh token means reconnecting Gmail in the app invalidates the cache.
_cache: dict[tuple[str, str], tuple[str, float]] = {}


def uses_xoauth2(settings) -> bool:
    return str(getattr(settings, "smtp_auth", "password") or "password").strip().lower() == "xoauth2"


def load_token_file(path) -> dict:
    if not str(path or "").strip():
        raise ConfigError(
            "SMTP_AUTH=xoauth2 but GOOGLE_OAUTH_TOKEN_FILE is not set.\n   " + RECONNECT_HINT)
    p = Path(path).expanduser()
    if not p.is_file():
        raise ConfigError(f"GOOGLE_OAUTH_TOKEN_FILE does not exist: {p}\n   " + RECONNECT_HINT)
    try:
        data = json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise ConfigError(
            f"GOOGLE_OAUTH_TOKEN_FILE is not valid JSON ({p}): {exc}\n   " + RECONNECT_HINT) from exc
    if not isinstance(data, dict):
        raise ConfigError(f"GOOGLE_OAUTH_TOKEN_FILE must hold a JSON object: {p}")
    missing = [k for k in ("client_id", "client_secret", "refresh_token")
               if not str(data.get(k) or "").strip()]
    if missing:
        raise ConfigError(
            f"GOOGLE_OAUTH_TOKEN_FILE ({p}) is missing: {', '.join(missing)}\n   " + RECONNECT_HINT)
    return data


def _request_token(data: dict, timeout: float) -> tuple[str, float]:
    uri = str(data.get("token_uri") or DEFAULT_TOKEN_URI)
    body = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "client_id": data["client_id"],
        "client_secret": data["client_secret"],
        "refresh_token": data["refresh_token"],
    }).encode()
    req = urllib.request.Request(uri, data=body, method="POST", headers={
        "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
    try:
        if uri.startswith("https:"):
            resp = tls.urlopen(req, timeout=timeout)
        else:
            resp = urllib.request.urlopen(req, timeout=timeout)
        with resp:
            payload = json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        try:
            err = json.loads(exc.read().decode("utf-8") or "{}")
        except ValueError:
            err = {}
        code = str(err.get("error") or "")
        detail = str(err.get("error_description") or "")
        if code == "invalid_grant":
            raise ConfigError(
                "Google rejected the saved Gmail connection (invalid_grant: the token was "
                "revoked or expired).\n   " + RECONNECT_HINT) from exc
        if code in {"invalid_client", "unauthorized_client"}:
            raise ConfigError(
                f"Google rejected the OAuth client ({code}: {detail}).\n   " + RECONNECT_HINT) from exc
        raise RuntimeError(
            f"Google token refresh failed: HTTP {exc.code} {code} {detail}".strip()) from exc
    except ValueError as exc:
        raise RuntimeError(f"Google token endpoint returned invalid JSON: {exc}") from exc
    token = str(payload.get("access_token") or "")
    if not token:
        raise RuntimeError(f"Google token endpoint returned no access_token: {payload!r}")
    try:
        lifetime = float(payload.get("expires_in") or 3600)
    except (TypeError, ValueError):
        lifetime = 3600.0
    return token, time.monotonic() + lifetime


def access_token(token_file, force: bool = False, timeout: float = 30) -> str:
    """A valid access token, refreshed only when missing or near expiry."""
    data = load_token_file(token_file)
    key = _key(token_file, data)
    with _lock:
        cached = _cache.get(key)
        if cached and not force and time.monotonic() < cached[1] - EXPIRY_MARGIN:
            return cached[0]
        token, expires = _request_token(data, timeout)
        _cache[key] = (token, expires)
        return token


def _key(token_file, data: dict) -> tuple[str, str]:
    return str(Path(str(token_file)).expanduser()), str(data.get("refresh_token") or "")


def forget(token_file) -> None:
    """Drop cached tokens for this file so the next call refreshes."""
    path = str(Path(str(token_file or "")).expanduser())
    with _lock:
        for key in [k for k in _cache if k[0] == path]:
            _cache.pop(key, None)


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def xoauth2_bytes(user: str, token: str) -> bytes:
    return f"user={user}\x01auth=Bearer {token}\x01\x01".encode()


def xoauth2_b64(user: str, token: str) -> str:
    return base64.b64encode(xoauth2_bytes(user, token)).decode("ascii")


def smtp_authenticate(server, user: str, token_file, timeout: float = 30) -> None:
    """AUTH XOAUTH2 on an already-secured smtplib connection."""
    import smtplib
    token = access_token(token_file, timeout=timeout)
    code, resp = server.docmd("AUTH", "XOAUTH2 " + xoauth2_b64(user, token))
    if code == 334:
        # Gmail sends a base64 JSON error as a challenge; an empty line ends it.
        try:
            detail = base64.b64decode(resp).decode("utf-8", "replace")
        except Exception:
            detail = resp.decode("utf-8", "replace") if isinstance(resp, bytes) else str(resp)
        code, resp = server.docmd("")
        resp = (resp.decode("utf-8", "replace") if isinstance(resp, bytes) else str(resp))
        resp = f"{resp} {detail}".strip()
    if code != 235:
        # Drop the cached token so the next attempt fetches a fresh one.
        forget(token_file)
        raise smtplib.SMTPAuthenticationError(
            code, f"XOAUTH2 login for {user} failed: {resp!r}. " + RECONNECT_HINT)


def imap_authenticate(conn, user: str, token_file, timeout: float = 30):
    """AUTHENTICATE XOAUTH2 on an imaplib connection."""
    import imaplib
    raw = xoauth2_bytes(user, access_token(token_file, timeout=timeout))
    sent = []

    def respond(_challenge):
        # A second challenge carries Gmail's error JSON; an empty reply ends it.
        if sent:
            return b""
        sent.append(True)
        return raw

    try:
        return conn.authenticate("XOAUTH2", respond)
    except imaplib.IMAP4.error as exc:
        forget(token_file)
        raise imaplib.IMAP4.error(
            f"IMAP XOAUTH2 login for {user} failed: {exc}. " + RECONNECT_HINT) from exc
