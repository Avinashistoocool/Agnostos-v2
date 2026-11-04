"""Users, sessions, per-user workspace, settings, profile and onboarding."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import threading

from desktop_review.storage import Workspace
from .errors import EngineError
from .util import (KEY_RE, data_dir, protect, read_env, read_json, unprotect,
                   update_env, write_json)

STEPS = ["resume", "profile", "interests", "targets", "email", "llm", "funding", "limits"]
PBKDF2_ITERATIONS = 390_000
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}$")

# Keys always present in settings.get so forms have something to bind to.
DEFAULT_KEYS = [
    "LLM_PROVIDER", "GROQ_API_KEY", "OPENAI_API_KEY", "DRAFT_MODEL",
    "SMTP_HOST", "SMTP_PORT", "SMTP_SECURITY", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM",
    "SMTP_FROM_NAME", "REPLY_TO", "IMAP_HOST", "IMAP_PORT", "IMAP_USER", "IMAP_PASSWORD",
    "POSITION", "GEOGRAPHY", "AVAILABILITY", "DISCOVER_COUNTRIES", "DISCOVER_QUERIES",
    "TARGET_UNIVERSITIES", "FOCUS_KEYWORDS", "CAN_SELF_FUND", "SELF_FUND_NOTE",
    "DAILY_SEND_CAP", "RESEND_DAILY_CAP", "SEND_DELAY_MIN", "SEND_DELAY_MAX",
    "SEND_LOCAL_WINDOW", "SEND_WEEKDAYS", "OPENALEX_MAILTO", "RESUME_PATH", "TARGET_XLSX",
]
KNOWN_SECRETS = ["GROQ_API_KEY", "OPENAI_API_KEY", "SMTP_PASSWORD", "IMAP_PASSWORD",
                 "RESEND_SMTP_PASSWORD", "OPENALEX_API_KEY", "PROXY_PASSWORD"]
SECRET_RE = re.compile(r"(_PASSWORD|_API_KEY|_SECRET|_TOKEN)$")
MASK = "\u2022\u2022\u2022\u2022"
# Safety-relevant or engine-owned keys the UI may not write.
RESERVED = re.compile(r"^(AGNOSTOS_|PYTHON|FOCUS$|RESPECT_ROBOTS$|OUTPUT_DIR$|"
                      r"GOOGLE_OAUTH_TOKEN_FILE$)")
WINDOW_RE = re.compile(r"^(?:[0-1]?\d|2[0-3])-(?:[0-1]?\d|2[0-3])$")
WEEKDAYS = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}
KINDS = {
    "LLM_PROVIDER": "enum:groq|openai", "SMTP_SECURITY": "enum:ssl|starttls",
    "SMTP_PORT": "port", "IMAP_PORT": "port", "RESEND_SMTP_PORT": "port",
    "DAILY_SEND_CAP": "cap", "RESEND_DAILY_CAP": "cap",
    "SEND_DELAY_MIN": "delay", "SEND_DELAY_MAX": "delay",
    "SEND_LOCAL_WINDOW": "window", "SEND_WEEKDAYS": "weekdays",
    "CAN_SELF_FUND": "enum:true|false|yes|no|unset", "BUDGET_USD": "float",
    "MAX_PROFESSORS": "int", "SMTP_AUTH": "enum:password|xoauth2",
}


def is_secret(key: str) -> bool:
    return key in KNOWN_SECRETS or bool(SECRET_RE.search(key))


def mask(value: str) -> str:
    if not value:
        return ""
    return MASK + (value[-4:] if len(value) >= 8 else "")


class EngineWorkspace(Workspace):
    """desktop_review Workspace for a per-user folder that need not be a v2 checkout."""

    def __init__(self, path: Path, config_dir: Path):
        self.config_dir = Path(config_dir)
        self._lock = threading.RLock()
        self.path = self.validate(str(path))

    @staticmethod
    def validate(value: str) -> Path:
        if not isinstance(value, str) or not value.strip():
            raise EngineError("bad_request", "Workspace folder is required")
        path = Path(value).expanduser().resolve()
        if not path.is_dir():
            raise EngineError("not_found", f"Workspace folder does not exist: {path}")
        output = (path / "output").resolve()
        if not output.is_dir() or not output.is_relative_to(path):
            raise EngineError("bad_request", "Workspace must contain an output folder")
        return path

    def coordinated_cli(self) -> bool:
        # A checkout runs its own CLI from scheduled tasks; only trust it if it is
        # the lock-aware version. Plain per-user folders only ever use our CLI.
        if (self.path / "outreach").is_dir():
            return super().coordinated_cli()
        return True

    def coordinated_workbook(self) -> bool:
        if (self.path / "outreach").is_dir():
            return super().coordinated_workbook()
        return True


class Accounts:
    def __init__(self, root: Path | None = None):
        self.root = Path(root).resolve() if root else data_dir()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.user_id: str | None = None
        session = read_json(self.root / "session.json", {}) or {}
        if session.get("user_id") in self._users():
            self.user_id = session["user_id"]

    # ---------- storage ----------
    def _users(self) -> dict:
        data = read_json(self.root / "users.json", {}) or {}
        return data.get("users", {}) if isinstance(data, dict) else {}

    def _save_users(self, users: dict) -> None:
        write_json(self.root / "users.json", {"users": users})

    def _set_session(self, user_id: str | None) -> None:
        self.user_id = user_id
        write_json(self.root / "session.json", {"user_id": user_id})

    def user_dir(self, user_id: str | None = None) -> Path:
        uid = user_id or self.require()["id"]
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", uid):
            raise EngineError("internal", "Invalid user id")
        path = self.root / "users" / uid
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def public(record: dict | None) -> dict | None:
        if not record:
            return None
        return {"id": record["id"], "name": record.get("name") or "",
                "email": record.get("email"), "provider": record["provider"],
                "avatar_url": record.get("avatar_url"),
                "gmail_connected": bool(record.get("gmail_connected"))}

    def current(self) -> dict | None:
        with self._lock:
            return self._users().get(self.user_id) if self.user_id else None

    def require(self) -> dict:
        user = self.current()
        if not user:
            raise EngineError("not_signed_in", "Sign in first")
        return user

    def _upsert(self, record: dict, sign_in: bool = True) -> dict:
        with self._lock:
            users = self._users()
            users[record["id"]] = {**users.get(record["id"], {}), **record}
            self._save_users(users)
            self.ensure_workspace(record["id"])
            if sign_in:
                self._set_session(record["id"])
            return users[record["id"]]

    def update_user(self, user_id: str, **fields) -> dict:
        with self._lock:
            users = self._users()
            if user_id not in users:
                raise EngineError("not_found", "User not found")
            users[user_id].update(fields)
            self._save_users(users)
            return users[user_id]

    # ---------- auth ----------
    def guest(self, name: str | None = None) -> dict:
        if name is not None and (not isinstance(name, str) or len(name) > 100):
            raise EngineError("bad_request", "Invalid name")
        existing = self._users().get("guest", {})
        return self._upsert({"id": "guest", "provider": "guest", "email": None,
                             "name": (name or "").strip() or existing.get("name") or "Guest",
                             "gmail_connected": existing.get("gmail_connected", False)})

    @staticmethod
    def _hash(password: str, salt: bytes, iterations: int) -> str:
        return base64.b64encode(hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, iterations)).decode()

    def register(self, name, email, password) -> dict:
        if not isinstance(email, str) or not EMAIL_RE.fullmatch(email.strip()):
            raise EngineError("bad_request", "Enter a valid email address")
        if not isinstance(password, str) or len(password) < 8 or len(password) > 1024:
            raise EngineError("bad_request", "Password must be at least 8 characters")
        if name is not None and (not isinstance(name, str) or len(name) > 100):
            raise EngineError("bad_request", "Invalid name")
        email = email.strip().lower()
        with self._lock:
            if any(u.get("provider") == "local" and u.get("email") == email
                   for u in self._users().values()):
                raise EngineError("conflict", "An account with that email already exists")
            salt = secrets.token_bytes(16)
            return self._upsert({
                "id": "l-" + secrets.token_hex(8), "provider": "local", "email": email,
                "name": (name or "").strip() or email.split("@")[0], "gmail_connected": False,
                "password": {"algorithm": "pbkdf2_sha256", "iterations": PBKDF2_ITERATIONS,
                             "salt": base64.b64encode(salt).decode(),
                             "hash": self._hash(password, salt, PBKDF2_ITERATIONS)}})

    def login(self, email, password) -> dict:
        if not isinstance(email, str) or not isinstance(password, str):
            raise EngineError("bad_request", "Email and password are required")
        email = email.strip().lower()
        with self._lock:
            match = next((u for u in self._users().values()
                          if u.get("provider") == "local" and u.get("email") == email), None)
            stored = (match or {}).get("password") or {}
            try:
                salt = base64.b64decode(stored.get("salt", ""))
                iterations = int(stored.get("iterations") or PBKDF2_ITERATIONS)
                good = bool(match) and hmac.compare_digest(
                    self._hash(password, salt, iterations), stored.get("hash", ""))
            except (ValueError, TypeError):
                good = False
            if not good:
                raise EngineError("auth_failed", "Wrong email or password")
            self._set_session(match["id"])
            self.ensure_workspace(match["id"])
            return match

    def sign_in_external(self, record: dict) -> dict:
        return self._upsert(record)

    def logout(self) -> None:
        with self._lock:
            self._set_session(None)

    # ---------- tokens (DPAPI) ----------
    def tokens(self, user_id: str) -> dict:
        path = self.user_dir(user_id) / "tokens.bin"
        if not path.exists():
            return {}
        try:
            return json.loads(unprotect(path.read_bytes()))
        except (OSError, ValueError) as exc:
            raise EngineError("internal", "Cannot unlock stored sign-in tokens") from exc

    def save_token(self, user_id: str, provider: str, token: dict) -> None:
        with self._lock:
            tokens = self.tokens(user_id)
            tokens[provider] = token
            from .util import atomic_write_bytes
            atomic_write_bytes(self.user_dir(user_id) / "tokens.bin",
                               protect(json.dumps(tokens).encode("utf-8")))

    # ---------- workspace ----------
    def ensure_workspace(self, user_id: str) -> Path:
        prefs = read_json(self.user_dir(user_id) / "prefs.json", {}) or {}
        override = prefs.get("workspace")
        if override:
            path = Path(override)
            if path.is_dir():
                (path / "output").mkdir(exist_ok=True)
                return path.resolve()
        path = self.user_dir(user_id) / "workspace"
        (path / "output").mkdir(parents=True, exist_ok=True)
        env = path / ".env"
        if not env.exists():
            env.write_text("# Agnostos settings for this account (written by the desktop app)\n",
                           encoding="utf-8")
        return path.resolve()

    def workspace_path(self) -> Path:
        return self.ensure_workspace(self.require()["id"])

    def workspace(self) -> EngineWorkspace:
        user = self.require()
        return EngineWorkspace(self.ensure_workspace(user["id"]), self.user_dir(user["id"]))

    def set_workspace(self, value: str) -> None:
        user = self.require()
        prefs_path = self.user_dir(user["id"]) / "prefs.json"
        prefs = read_json(prefs_path, {}) or {}
        if not isinstance(value, str) or len(value) > 1024:
            raise EngineError("bad_request", "Invalid workspace path")
        if value.strip():
            path = Path(value.strip()).expanduser()
            if not path.is_absolute() or not path.is_dir():
                raise EngineError("not_found", f"Workspace folder does not exist: {value}")
            (path / "output").mkdir(exist_ok=True)
            prefs["workspace"] = str(path.resolve())
        else:
            prefs.pop("workspace", None)
        write_json(prefs_path, prefs)

    # ---------- settings ----------
    def env_file(self) -> Path:
        return self.workspace_path() / ".env"

    def raw_settings(self) -> dict:
        return read_env(self.env_file())

    def settings(self) -> dict:
        values = self.raw_settings()
        out = {key: "" for key in DEFAULT_KEYS}
        out.update(values)
        out = {k: (mask(v) if is_secret(k) else v) for k, v in out.items()}
        out["_workspace"] = str(self.workspace_path())
        return out

    def secret_keys(self) -> list[str]:
        keys = set(KNOWN_SECRETS) | {k for k in self.raw_settings() if is_secret(k)}
        return sorted(keys)

    @staticmethod
    def _check(key: str, value: str) -> str:
        kind = KINDS.get(key, "text")
        if not value:
            return value
        if kind.startswith("enum:"):
            if value.lower() not in kind[5:].split("|"):
                raise EngineError("bad_request", f"{key} must be one of {kind[5:].replace('|', ', ')}")
            value = value.lower()
            return "" if value == "unset" else value
        try:
            if kind == "port" and not 1 <= int(value) <= 65535:
                raise ValueError
            if kind == "cap" and not 1 <= int(value) <= 40:
                raise EngineError("bad_request", f"{key} must be between 1 and 40")
            if kind == "int" and not 1 <= int(value) <= 100000:
                raise ValueError
            if kind == "delay" and not 60 <= float(value) <= 100000:
                raise EngineError("bad_request", f"{key} must be at least 60 seconds")
            if kind == "float" and not 0 < float(value) <= 10000:
                raise ValueError
        except ValueError:
            raise EngineError("bad_request", f"Invalid {key}") from None
        if kind == "window" and not WINDOW_RE.fullmatch(value):
            raise EngineError("bad_request", "Send window must look like 9-17")
        if kind == "weekdays":
            days = [d.strip().lower() for d in value.split(",") if d.strip()]
            if not days or set(days) - WEEKDAYS:
                raise EngineError("bad_request", "SEND_WEEKDAYS must look like mon,tue,wed")
            value = ",".join(days)
        return value

    def update_settings(self, values: dict) -> dict:
        if not isinstance(values, dict):
            raise EngineError("bad_request", "values must be an object")
        changes: dict[str, str | None] = {}
        workspace = None
        for key, value in values.items():
            if key == "_workspace":
                workspace = value
                continue
            if not isinstance(key, str) or not KEY_RE.fullmatch(key) or RESERVED.match(key):
                raise EngineError("bad_request", f"Setting {key} cannot be changed here")
            if value is None:
                value = ""
            if not isinstance(value, str) or len(value) > 4096 or re.search(r"[\r\n\x00]", value):
                raise EngineError("bad_request", f"Invalid value for {key}")
            if is_secret(key) and value.startswith(MASK):
                continue
            value = value.strip() if not is_secret(key) else value
            changes[key] = self._check(key, value) or None
        with self._lock:
            if workspace is not None and str(workspace) != str(self.workspace_path()):
                self.set_workspace(workspace)
            if changes:
                update_env(self.env_file(), changes)
        return self.settings()

    # ---------- onboarding / profile ----------
    def onboarding(self) -> dict:
        if not self.current():
            return {"completed": [], "done": False}
        data = read_json(self.user_dir() / "onboarding.json", {}) or {}
        completed = [s for s in STEPS if s in (data.get("completed") or [])]
        return {"completed": completed, "done": len(completed) == len(STEPS)}

    def complete_step(self, step) -> dict:
        self.require()
        if step not in STEPS:
            raise EngineError("bad_request", f"Unknown onboarding step: {step}")
        state = self.onboarding()
        if step not in state["completed"]:
            state["completed"].append(step)
        write_json(self.user_dir() / "onboarding.json", {"completed": state["completed"]})
        return self.onboarding()

    def profile(self) -> dict:
        user = self.require()
        stored = read_json(self.user_dir() / "profile.json", {}) or {}
        return normalize_profile(stored, user)

    def save_profile(self, profile) -> dict:
        user = self.require()
        if not isinstance(profile, dict):
            raise EngineError("bad_request", "profile must be an object")
        merged = {**self.profile(), **profile}
        clean = normalize_profile(merged, user, strict=True)
        write_json(self.user_dir() / "profile.json", clean)
        return clean

    def import_resume(self, source) -> dict:
        self.require()
        if not isinstance(source, str) or not source.strip():
            raise EngineError("bad_request", "path is required")
        src = Path(source).expanduser()
        if not src.is_file():
            raise EngineError("not_found", f"File not found: {source}")
        suffix = src.suffix.lower()
        if suffix not in {".pdf", ".docx"}:
            raise EngineError("bad_request", "Resume must be a PDF or DOCX file")
        if src.stat().st_size > 20 * 1024 * 1024:
            raise EngineError("bad_request", "Resume file is larger than 20 MB")
        workspace = self.workspace_path()
        target = workspace / f"resume{suffix}"
        if src.resolve() != target.resolve():
            pending = workspace / f".resume.{secrets.token_hex(4)}{suffix}"
            shutil.copyfile(src, pending)
            os.replace(pending, target)
        for other in (".pdf", ".docx"):
            if other != suffix:
                (workspace / f"resume{other}").unlink(missing_ok=True)
        try:
            from outreach.resume_parser import parse_resume
            parsed = parse_resume(target)
        except Exception as exc:  # parser raises many library-specific errors
            raise EngineError("bad_request", f"Could not read the resume: {type(exc).__name__}: {exc}") from exc
        profile = {
            "name": parsed.name, "email": parsed.email, "degree": parsed.degree,
            "institution": parsed.institution,
            "research_interests": parsed.research_interests[:20] or parsed.keywords[:8],
            "skills": parsed.skills[:40],
            "projects": [{"title": p.get("title", ""),
                          "summary": " ".join(p.get("bullets", []))[:600]}
                         for p in parsed.projects[:12]],
            "resume_file": target.name,
        }
        update_env(self.env_file(), {"RESUME_PATH": str(target)})
        return self.save_profile(profile)


def _strings(value, limit: int, strict: bool, name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
        if strict:
            raise EngineError("bad_request", f"{name} must be a list of strings")
        return []
    return [v.strip()[:200] for v in value if v.strip()][:limit]


def normalize_profile(data: dict, user: dict, strict: bool = False) -> dict:
    out = {}
    for key in ("name", "email", "degree", "institution"):
        value = data.get(key)
        if value is None:
            value = ""
        if not isinstance(value, str) or len(value) > 300:
            if strict:
                raise EngineError("bad_request", f"Invalid profile {key}")
            value = ""
        out[key] = value.strip()
    out["name"] = out["name"] or (user.get("name") if user.get("provider") != "guest" else "") or ""
    out["email"] = out["email"] or user.get("email") or ""
    out["research_interests"] = _strings(data.get("research_interests"), 50, strict, "research_interests")
    out["skills"] = _strings(data.get("skills"), 100, strict, "skills")
    projects = data.get("projects") or []
    if not isinstance(projects, list):
        if strict:
            raise EngineError("bad_request", "projects must be a list")
        projects = []
    clean = []
    for item in projects[:30]:
        if not isinstance(item, dict) or not isinstance(item.get("title", ""), str) \
                or not isinstance(item.get("summary", ""), str):
            if strict:
                raise EngineError("bad_request", "Each project needs a title and summary")
            continue
        clean.append({"title": item.get("title", "")[:300], "summary": item.get("summary", "")[:2000]})
    out["projects"] = clean
    resume = data.get("resume_file")
    out["resume_file"] = resume if isinstance(resume, str) and resume else None
    return out
