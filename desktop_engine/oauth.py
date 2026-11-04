"""Google (PKCE + loopback) and GitHub (device flow) sign-in."""
from __future__ import annotations

import base64
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import secrets
import threading
import time
import urllib.parse
import webbrowser

from .errors import EngineError
from .util import data_dir, http_json, read_json, update_env, write_json

GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO = "https://openidconnect.googleapis.com/v1/userinfo"
GMAIL_SCOPE = "https://mail.google.com/"
GITHUB_DEVICE = "https://github.com/login/device/code"
GITHUB_TOKEN = "https://github.com/login/oauth/access_token"
GITHUB_API = "https://api.github.com"
GOOGLE_TIMEOUT = 300
SETUP = ("{name} sign-in is not configured. Create %LOCALAPPDATA%\\Agnostos\\oauth.json with "
         '{{"{key}": {{"client_id": "..."{extra}}}}} (see docs/engine-protocol.md), then restart the app.')
TOKEN_FILE_NAME = "gmail_oauth_token.json"


def oauth_config(provider: str, root: Path | None = None) -> dict:
    config = read_json((Path(root) if root else data_dir()) / "oauth.json", {}) or {}
    entry = config.get(provider) if isinstance(config, dict) else None
    if not isinstance(entry, dict) or not str(entry.get("client_id") or "").strip():
        name, extra = ("Google", ', "client_secret": "..."') if provider == "google" else ("GitHub", "")
        raise EngineError("unavailable", SETUP.format(name=name, key=provider, extra=extra))
    return entry


_PAGE = ("<!doctype html><meta charset=utf-8><title>Agnostos</title>"
         "<body style='font-family:system-ui;background:#111;color:#eee;display:grid;"
         "place-items:center;height:90vh'><div><h2>{title}</h2><p>{text}</p></div>")


def google_sign_in(accounts, connect_gmail: bool, emit, open_browser=webbrowser.open) -> dict:
    config = oauth_config("google", accounts.root)
    client_id = config["client_id"].strip()
    client_secret = str(config.get("client_secret") or "")
    auth_uri = config.get("auth_uri") or GOOGLE_AUTH
    token_uri = config.get("token_uri") or GOOGLE_TOKEN
    userinfo_uri = config.get("userinfo_uri") or GOOGLE_USERINFO
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(24)
    result: dict = {}
    done = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            if "state" not in query and "code" not in query and "error" not in query:
                self.send_response(404)
                self.end_headers()
                return
            ok = query.get("state", [""])[0] == state and "code" in query
            if not done.is_set():
                if ok:
                    result["code"] = query["code"][0]
                    result["scope"] = query.get("scope", [""])[0]
                else:
                    result["error"] = query.get("error", ["state_mismatch"])[0]
                done.set()
            body = _PAGE.format(
                title="Signed in" if ok else "Sign-in failed",
                text="You can close this tab and return to Agnostos." if ok
                else "Return to Agnostos and try again.").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    server.timeout = 1
    redirect = f"http://127.0.0.1:{server.server_port}/"
    scopes = ["openid", "email", "profile"] + ([GMAIL_SCOPE] if connect_gmail else [])
    params = {"client_id": client_id, "redirect_uri": redirect, "response_type": "code",
              "scope": " ".join(scopes), "code_challenge": challenge,
              "code_challenge_method": "S256", "state": state}
    if connect_gmail:
        params.update(access_type="offline", prompt="consent", include_granted_scopes="true")
    else:
        params["prompt"] = "select_account"
    url = auth_uri + "?" + urllib.parse.urlencode(params)
    thread = threading.Thread(target=lambda: _serve_until(server, done), daemon=True)
    thread.start()
    try:
        emit("auth.progress", {"stage": "browser", "detail": "Opened your browser. Finish signing in there."})
        if not open_browser(url):
            emit("auth.progress", {"stage": "browser", "detail": "Open this link to sign in: " + url})
        if not done.wait(GOOGLE_TIMEOUT):
            raise EngineError("auth_failed", "Timed out waiting for Google sign-in")
    finally:
        done.set()
        thread.join(3)
        server.server_close()
    if "code" not in result:
        raise EngineError("auth_failed", f"Google sign-in was not completed ({result.get('error')})")
    emit("auth.progress", {"stage": "token", "detail": "Exchanging the authorization code"})
    form = {"grant_type": "authorization_code", "code": result["code"], "client_id": client_id,
            "redirect_uri": redirect, "code_verifier": verifier}
    if client_secret:
        form["client_secret"] = client_secret
    status, token = http_json(token_uri, form)
    if status != 200 or not token.get("access_token"):
        raise EngineError("auth_failed", "Google rejected the sign-in: "
                          f"{token.get('error', status)} {token.get('error_description', '')}".strip())
    emit("auth.progress", {"stage": "profile", "detail": "Reading your Google profile"})
    status, info = http_json(userinfo_uri, headers={"Authorization": "Bearer " + token["access_token"]})
    if status != 200 or not info.get("sub"):
        raise EngineError("auth_failed", f"Could not read the Google profile (HTTP {status})")
    user_id = "g-" + "".join(ch for ch in str(info["sub"]) if ch.isalnum())[:60]
    email = str(info.get("email") or "").lower() or None
    granted = set(str(token.get("scope") or result.get("scope") or "").split())
    previous = accounts._users().get(user_id, {})
    record = {"id": user_id, "provider": "google", "email": email,
              "name": info.get("name") or email or "Google user",
              "avatar_url": info.get("picture"),
              "gmail_connected": bool(previous.get("gmail_connected"))}
    user = accounts.sign_in_external(record)
    if connect_gmail:
        refresh = token.get("refresh_token") or accounts.tokens(user_id).get("google", {}).get("refresh_token")
        if GMAIL_SCOPE not in granted or not refresh or not email:
            emit("auth.progress", {"stage": "gmail", "detail": "Gmail access was not granted; "
                                   "email sending is not connected."})
        else:
            emit("auth.progress", {"stage": "gmail", "detail": "Connecting Gmail for sending and replies"})
            accounts.save_token(user_id, "google", {"refresh_token": refresh, "scope": " ".join(sorted(granted))})
            connect_gmail_workspace(accounts, user, {
                "client_id": client_id, "client_secret": client_secret,
                "refresh_token": refresh, "token_uri": token_uri})
            user = accounts.update_user(user_id, gmail_connected=True)
    emit("auth.progress", {"stage": "done", "detail": "Signed in"})
    return user


def _serve_until(server: HTTPServer, done: threading.Event) -> None:
    while not done.is_set():
        server.handle_request()


def connect_gmail_workspace(accounts, user: dict, token: dict) -> Path:
    """Write the XOAUTH2 token file and point the workspace .env at Gmail."""
    workspace = accounts.ensure_workspace(user["id"])
    path = workspace / TOKEN_FILE_NAME
    write_json(path, token)
    env = workspace / ".env"
    current = accounts.raw_settings() if accounts.user_id == user["id"] else {}
    email = user["email"]
    changes = {
        "SMTP_AUTH": "xoauth2", "GOOGLE_OAUTH_TOKEN_FILE": str(path),
        "SMTP_HOST": "smtp.gmail.com", "SMTP_PORT": "465", "SMTP_SECURITY": "ssl",
        "SMTP_USER": email, "SMTP_FROM": email,
        "IMAP_HOST": "imap.gmail.com", "IMAP_PORT": "993", "IMAP_USER": email,
    }
    if not current.get("SMTP_FROM_NAME") and user.get("name"):
        changes["SMTP_FROM_NAME"] = user["name"]
    update_env(env, changes)
    return path


# ---------- GitHub device flow ----------

class GitHubFlow:
    def __init__(self):
        self.pending: dict[str, dict] = {}
        self._lock = threading.Lock()

    def start(self, root: Path | None = None) -> dict:
        config = oauth_config("github", root)
        uri = config.get("device_code_uri") or GITHUB_DEVICE
        status, data = http_json(uri, {"client_id": config["client_id"].strip(),
                                       "scope": "read:user user:email"})
        if status != 200 or not data.get("device_code"):
            raise EngineError("unavailable", "GitHub did not start sign-in: "
                              f"{data.get('error_description') or data.get('error') or status}")
        interval = int(data.get("interval") or 5)
        expires = int(data.get("expires_in") or 900)
        with self._lock:
            self.pending[data["device_code"]] = {"expires": time.monotonic() + expires,
                                                 "interval": interval, "last": 0.0}
        return {"user_code": data.get("user_code", ""),
                "verification_uri": data.get("verification_uri") or "https://github.com/login/device",
                "device_code": data["device_code"], "interval": interval, "expires_in": expires}

    def poll(self, accounts, device_code) -> dict:
        if not isinstance(device_code, str) or not device_code:
            raise EngineError("bad_request", "device_code is required")
        with self._lock:
            entry = self.pending.get(device_code)
        if entry is None:
            raise EngineError("not_found", "Unknown or finished GitHub sign-in; start again")
        if time.monotonic() > entry["expires"]:
            with self._lock:
                self.pending.pop(device_code, None)
            return {"status": "expired"}
        config = oauth_config("github", accounts.root)
        uri = config.get("token_uri") or GITHUB_TOKEN
        status, data = http_json(uri, {
            "client_id": config["client_id"].strip(), "device_code": device_code,
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code"})
        error = data.get("error")
        if error == "authorization_pending":
            return {"status": "pending"}
        if error == "slow_down":
            entry["interval"] = int(data.get("interval") or entry["interval"] + 5)
            return {"status": "slow_down"}
        if error in ("expired_token", "access_denied") or (error and not data.get("access_token")):
            with self._lock:
                self.pending.pop(device_code, None)
            return {"status": {"expired_token": "expired", "access_denied": "denied"}.get(error, "denied")}
        token = data.get("access_token")
        if status != 200 or not token:
            raise EngineError("auth_failed", f"GitHub sign-in failed (HTTP {status})")
        with self._lock:
            self.pending.pop(device_code, None)
        api = (config.get("api_uri") or GITHUB_API).rstrip("/")
        headers = {"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json"}
        status, profile = http_json(api + "/user", headers=headers)
        if status != 200 or not profile.get("id"):
            raise EngineError("auth_failed", f"Could not read the GitHub profile (HTTP {status})")
        email = profile.get("email")
        if not email:
            code, emails = http_json(api + "/user/emails", headers=headers)
            listing = emails.get("value") if isinstance(emails.get("value"), list) else []
            primary = next((e for e in listing if isinstance(e, dict) and e.get("primary")
                            and e.get("verified")), None)
            email = primary.get("email") if primary else None
        user_id = "gh-" + str(int(profile["id"]))
        previous = accounts._users().get(user_id, {})
        user = accounts.sign_in_external({
            "id": user_id, "provider": "github", "email": (email or "").lower() or None,
            "name": profile.get("name") or profile.get("login") or "GitHub user",
            "avatar_url": profile.get("avatar_url"),
            "gmail_connected": bool(previous.get("gmail_connected"))})
        accounts.save_token(user_id, "github", {"access_token": token})
        return {"status": "done", "user": accounts.public(user)}
