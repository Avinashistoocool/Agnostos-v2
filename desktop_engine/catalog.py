"""CommandSpec catalog built from the vetted desktop_review command registry."""
from __future__ import annotations

from desktop_review.commands import COMMANDS, LIVE_COMMANDS

META = {
    "discover": ("Discover professors", "Find"),
    "verify": ("Verify email addresses", "Find"),
    "recheck": ("Recheck professors and emails", "Find"),
    "replace-failed": ("Replace failed addresses", "Find"),
    "legacy": ("Senior researchers (legacy)", "Find"),
    "legacy-researchers": ("Senior researchers (alias)", "Find"),
    "profile": ("Inspect resume parse", "Draft"),
    "run": ("Match & draft", "Draft"),
    "models": ("List LLM models", "Draft"),
    "send": ("Send emails", "Send"),
    "resend": ("Resend from second account", "Send"),
    "check-replies": ("Check replies", "Replies"),
    "replies": ("Draft / send replies", "Replies"),
    "conversations": ("Rebuild conversations", "Replies"),
    "archive-sent": ("Archive sent mail to IMAP", "Replies"),
    "stats": ("Statistics", "Maintain"),
    "tls-check": ("TLS check", "Maintain"),
    "calendar-auth": ("Authorize Google Calendar", "Maintain"),
}

HELP = {
    "live": "Off = dry run. On = real emails to real people.",
    "limit": "Maximum emails this run (1-40 when live).",
    "delay_min": "Seconds between emails (at least 60 when live).",
    "delay_max": "Seconds between emails (at least 60 when live).",
    "local_window": "Recipient-local hours, e.g. 9-17.",
    "max_professors": "Cap on LLM-evaluated professors (controls cost).",
    "budget": "Hard USD budget for this run.",
    "dry_run": "Report only; change nothing.",
    "mode": "list = use your workbook; scrape = crawl faculty pages (source checkout only).",
    "review": "Send every draft to yourself first (counts as live mail).",
    "review_to": "Address that receives review copies (requires Review).",
    "send": "Send approved items (dry run unless Live is on).",
    "wait": "Wait for the recipient-local window to open.",
    "export": "Write .eml files instead of sending.",
}

# Fields where 0 is meaningless and must be refused even outside live mode.
MIN_ONE = {"limit", "top", "count", "batches", "max_professors", "workers", "per_topic",
           "per_failure", "max_pages", "prioritize_top", "min_days"}
INT_MAX = {"limit": 40}
EXCLUDED_TYPES = {"list"}


def confirmation_for(command: str) -> str | None:
    if command in LIVE_COMMANDS:
        return f"SEND {command.upper()}"
    if command == "archive-sent":
        return "ARCHIVE"
    return None


def field_spec(name: str, typ: str) -> dict | None:
    if typ in EXCLUDED_TYPES:
        return None
    label = name.replace("_", " ").capitalize()
    out: dict = {"name": name, "label": label}
    if typ == "bool":
        out.update(type="bool", default=False)
    elif typ == "int":
        out.update(type="int", min=1 if name in MIN_ONE else 0, max=INT_MAX.get(name, 100000))
    elif typ == "float":
        out.update(type="float", min=0, max=10000)
        if name.startswith("delay_"):
            out["min"] = 60
    elif typ.startswith("enum:"):
        choices = typ[5:].split("|")
        out.update(type="choice", choices=choices, default=choices[0])
    else:
        out["type"] = "str"
        if typ in ("file", "resume"):
            out["help"] = "Path (relative to your workspace)." if typ == "file" else "Resume path (defaults to your imported resume)."
    if name in HELP:
        out["help"] = HELP[name]
    return out


def command_specs() -> list[dict]:
    specs = []
    for name, entry in COMMANDS.items():
        title, group = META.get(name, (name, "Other"))
        fields = [f for f in (field_spec(k, t) for k, t in entry["fields"].items()) if f]
        spec = {"name": name, "title": title, "group": group,
                "description": entry["description"], "fields": fields}
        confirmation = confirmation_for(name)
        if confirmation and "live" in entry["fields"]:
            spec["live_field"] = "live"
            spec["confirmation"] = confirmation
        specs.append(spec)
    return specs


def allowed_options(command: str) -> set[str]:
    entry = COMMANDS.get(command)
    if entry is None:
        return set()
    return {k for k, t in entry["fields"].items()}
