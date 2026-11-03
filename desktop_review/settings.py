"""Workspace-specific GUI overrides; never modifies the v2 .env file."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from dotenv import dotenv_values

from .storage import ReviewError, Workspace

FIELDS = {
    "RESUME_PATH": "path", "TARGET_XLSX": "path", "ATTACHMENTS": "path",
    "LLM_PROVIDER": "enum:groq|openai", "DRAFT_MODEL": "text",
    "GROQ_API_KEY": "secret", "OPENAI_API_KEY": "secret",
    "POSITION": "text", "GEOGRAPHY": "text", "AVAILABILITY": "text",
    "CAN_SELF_FUND": "enum:yes|no|unset", "SELF_FUND_NOTE": "text",
    "BUDGET_USD": "float", "MAX_PROFESSORS": "int",
    "SMTP_HOST": "text", "SMTP_PORT": "int", "SMTP_SECURITY": "enum:ssl|starttls",
    "SMTP_USER": "text", "SMTP_FROM": "text", "SMTP_FROM_NAME": "text",
    "SMTP_PASSWORD": "secret", "REPLY_TO": "text",
    "IMAP_HOST": "text", "IMAP_PORT": "int", "IMAP_USER": "text", "IMAP_PASSWORD": "secret",
    "RESEND_SMTP_HOST": "text", "RESEND_SMTP_PORT": "int",
    "RESEND_SMTP_USER": "text", "RESEND_SMTP_FROM": "text",
    "RESEND_SMTP_PASSWORD": "secret",
    "DAILY_SEND_CAP": "cap", "RESEND_DAILY_CAP": "cap",
    "SEND_LOCAL_WINDOW": "window", "SEND_DELAY_MIN": "delay",
    "SEND_DELAY_MAX": "delay", "DISCOVER_QUERIES": "text",
    "DISCOVER_COUNTRIES": "text", "OPENALEX_MAILTO": "text",
}
SECRETS = {key for key, kind in FIELDS.items() if kind == "secret"}


class SettingsStore:
    def __init__(self, workspace: Workspace):
        self.workspace = workspace

    def _dir(self) -> Path:
        if self.workspace.path is None:
            raise ReviewError(409, "Select a workspace first")
        digest = hashlib.sha256(str(self.workspace.path).encode("utf-8")).hexdigest()[:20]
        directory = self.workspace.config_dir / digest
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def _overrides(self) -> dict:
        path = self._dir() / "settings.json"
        try:
            return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except (OSError, ValueError):
            raise ReviewError(503, "GUI settings are unreadable") from None

    def _secrets(self) -> dict:
        path = self._dir() / "secrets.dpapi"
        if not path.exists():
            return {}
        if os.name != "nt":
            raise ReviewError(503, "Saved credentials require Windows DPAPI")
        try:
            import win32crypt
            return json.loads(win32crypt.CryptUnprotectData(path.read_bytes(), None, None, None, 0)[1])
        except (OSError, ValueError) as exc:
            raise ReviewError(503, "Cannot unlock stored GUI credentials") from exc

    def effective(self) -> dict:
        env = dotenv_values(self.workspace.path / ".env") if self.workspace.path else {}
        return {**{k: v for k, v in env.items() if k in FIELDS and v is not None},
                **self._overrides(), **self._secrets()}

    def public(self) -> dict:
        values = self.effective()
        return {"fields": FIELDS, "values": {
            key: ({"configured": bool(values.get(key))}
                  if key in SECRETS else values.get(key, ""))
            for key in FIELDS}}

    def save(self, patch: dict) -> dict:
        if not isinstance(patch, dict) or set(patch) - set(FIELDS):
            raise ReviewError(400, "Unknown GUI setting")
        values = self._overrides()
        secrets = self._secrets()
        for key, value in patch.items():
            kind = FIELDS[key]
            if value is None:
                (secrets if kind == "secret" else values).pop(key, None)
                continue
            if not isinstance(value, str) or len(value) > 1024 or "\x00" in value:
                raise ReviewError(400, f"Invalid {key}")
            if kind == "secret":
                if value:
                    secrets[key] = value
                continue
            if kind.startswith("enum:") and value and value not in kind[5:].split("|"):
                raise ReviewError(400, f"Invalid {key}")
            if kind == "cap" and value and (not value.isdecimal() or not 1 <= int(value) <= 40):
                raise ReviewError(400, f"{key} must be 1–40")
            if kind in {"int", "delay"} and value:
                try:
                    if not 0 <= float(value) <= 100000:
                        raise ValueError()
                except ValueError:
                    raise ReviewError(400, f"Invalid {key}") from None
            if kind == "float" and value:
                try:
                    if not 0 <= float(value) <= 10000:
                        raise ValueError()
                except ValueError:
                    raise ReviewError(400, f"Invalid {key}") from None
            if kind == "window" and value:
                from .commands import WINDOW
                if not WINDOW.fullmatch(value):
                    raise ReviewError(400, "Send window must look like 9-17")
            values[key] = "" if key == "CAN_SELF_FUND" and value == "unset" else value
        directory = self._dir()
        pending = directory / "settings.json.new"
        pending.write_text(json.dumps(values), encoding="utf-8")
        os.replace(pending, directory / "settings.json")
        if secrets:
            if os.name != "nt":
                raise ReviewError(400, "Saving secrets requires Windows DPAPI")
            import win32crypt
            blob = win32crypt.CryptProtectData(json.dumps(secrets).encode("utf-8"),
                                               "Agnostos desktop credentials", None, None, None, 0)
            pending = directory / "secrets.dpapi.new"
            pending.write_bytes(blob)
            os.replace(pending, directory / "secrets.dpapi")
        else:
            (directory / "secrets.dpapi").unlink(missing_ok=True)
        return self.public()

    def job_environment(self) -> dict:
        values = self.effective()
        output = self.workspace.path / "output"
        env = {k: v for k, v in os.environ.items() if k not in FIELDS}
        env.update({k: str(v) for k, v in values.items() if v is not None})
        env["OUTPUT_DIR"] = str(output)
        env["TARGET_XLSX"] = str(output / "professors.xlsx") if not values.get("TARGET_XLSX") \
            else str(values["TARGET_XLSX"])
        env["FOCUS"] = "true"
        env["RESPECT_ROBOTS"] = "true"
        env["SCRAPE_HEADLESS"] = "true"
        for key, default in (("DAILY_SEND_CAP", 25), ("RESEND_DAILY_CAP", 40)):
            try:
                configured = int(values.get(key) or default)
            except ValueError:
                configured = default
            env[key] = str(max(1, min(configured, 40)))
        try:
            delay = max(60.0, float(values.get("SEND_DELAY_MIN") or 90))
            delay_max = max(delay, float(values.get("SEND_DELAY_MAX") or 240))
        except ValueError:
            delay, delay_max = 90, 240
        env["SEND_DELAY_MIN"], env["SEND_DELAY_MAX"] = str(delay), str(delay_max)
        env["SEND_LOCAL_WINDOW"] = values.get("SEND_LOCAL_WINDOW") or "9-17"
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        return env
