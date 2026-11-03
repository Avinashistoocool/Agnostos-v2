"""Explicit GUI command surface; never accepts shell syntax or unreviewed CLI flags."""
from __future__ import annotations

from pathlib import Path
import re

from .storage import ReviewError, Workspace


def spec(description: str, **fields) -> dict:
    return {"description": description, "fields": fields}


# Type strings: bool, int, float, text, file, resume, enum:a|b, list.
# Safety bypasses (--yes, --approve-all, --no-focus, --allow-unverified,
# --weekends, --no-backup, --skip gate, and send --resend) are intentionally absent.
COMMANDS = {
    "profile": spec("Parse and inspect your resume", resume="resume"),
    "models": spec("List provider models (online)", provider="enum:groq|openai"),
    "run": spec("Score and draft emails (cost gate remains interactive)",
                mode="enum:list|scrape", resume="resume", xlsx="file", sheet="text",
                sources="file", output="file", max_professors="int", min_score="float",
                budget="float", provider="enum:groq|openai", model="text",
                no_enrich="bool", no_profile_hop="bool"),
    "send": spec("Preview drafts; live SMTP requires double confirmation",
                 xlsx="file", sheet="text", resume="resume", live="bool",
                 review="bool", review_to="text", export="bool", export_dir="file",
                 top="int", limit="int", delay_min="float", delay_max="float",
                 min_probability="int", preview="int", at="text",
                 local_window="text", wait="bool"),
    "resend": spec("Review resends; live SMTP requires double confirmation",
                   who="enum:all|bounced|noreply", xlsx="file", sheet="text",
                   resume="resume", min_days="int", limit="int", local_window="text",
                   wait="bool", prioritize_top="int", region="text",
                   delay_min="float", delay_max="float", live="bool"),
    "stats": spec("Read pipeline statistics", xlsx="file", sheet="text"),
    "check-replies": spec("Fetch IMAP replies and update workbook", xlsx="file",
                          sheet="text", dry_run="bool"),
    "replies": spec("Draft replies or preview/send individually approved replies",
                    xlsx="file", sheet="text", resume="resume", redraft="bool",
                    send="bool", live="bool", local_window="text", wait="bool"),
    "conversations": spec("Rebuild local conversation HTML from IMAP",
                          xlsx="file", no_open="bool"),
    "archive-sent": spec("Preview/copy delivered mail into IMAP Sent", xlsx="file",
                         resume="resume", live="bool"),
    "legacy": spec("Legacy researcher discovery, drafts, and selected sending",
                   find="bool", topics="text", include="text", countries="text",
                   min_h="int", per_topic="int", workers="int", draft="bool",
                   summer="text", send="bool", limit="int", local_window="text",
                   live="bool", resume="resume"),
    "legacy-researchers": spec("Alias of legacy", find="bool", topics="text",
                               include="text", countries="text", min_h="int",
                               per_topic="int", workers="int", draft="bool",
                               summer="text", send="bool", limit="int",
                               local_window="text", live="bool",
                               resume="resume"),
    "replace-failed": spec("Find replacements for failed addresses",
                           xlsx="file", per_failure="int"),
    "calendar-auth": spec("Authorize Google Calendar in the system browser"),
    "tls-check": spec("Check certificate configuration"),
    "discover": spec("Discover researchers from topics", query="text", resume="resume",
                     count="int", batches="int", countries="text", since="int",
                     max_pages="int", min_h_index="int", min_works="int",
                     top_universities="int", prestige_weight="float",
                     also_universities="text", list_universities="bool", output="file",
                     verify_emails="bool", workers="int", exclude="list", fresh="bool"),
    "recheck": spec("Recheck professor and email status", xlsx="file", sheet="text",
                    apply="bool", professors_only="bool", emails_only="bool",
                    workers="int", dry_run="bool"),
    "verify": spec("Verify or repair addresses", xlsx="file", sheet="text",
                   top="int", repair="bool", apply="bool", probe_smtp="bool",
                   workers="int", only_missing="bool", dry_run="bool"),
}

SAFE_TEXT = re.compile(r"^[^\x00-\x1f\x7f]{1,300}$")
LIVE_COMMANDS = {"send", "resend", "replies", "legacy", "legacy-researchers"}
WINDOW = re.compile(r"^(?:[0-1]?\d|2[0-3])-(?:[0-1]?\d|2[0-3])$")
PATH_FIELDS = {"xlsx", "sources", "output", "export_dir", "exclude"}


def _file(value: str, workspace: Path, *, resume: bool = False) -> str:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = workspace / path
    path = path.resolve()
    if not resume and not path.is_relative_to(workspace):
        raise ReviewError(400, "Command file paths must remain in the selected workspace")
    return str(path)


def build_argv(workspace: Workspace, command: str, options: dict,
               confirmation: str | None = None) -> tuple[list[str], bool]:
    entry = COMMANDS.get(command)
    if entry is None or not isinstance(options, dict) or set(options) - set(entry["fields"]):
        raise ReviewError(400, "Unknown command or option")
    if workspace.path is None:
        raise ReviewError(409, "Select a workspace first")
    root = workspace.validate(str(workspace.path))
    parsed = {}
    argv = [command]
    for key, raw in options.items():
        typ = entry["fields"][key]
        if raw is None or raw == "":
            continue
        flag = "--" + key.replace("_", "-")
        if typ == "bool":
            if not isinstance(raw, bool):
                raise ReviewError(400, f"{key} must be a checkbox")
            if raw:
                argv.append(flag)
                parsed[key] = True
            continue
        if typ == "list":
            if not isinstance(raw, list) or not 1 <= len(raw) <= 10:
                raise ReviewError(400, f"{key} must be a list of up to 10 paths")
            values = [_file(v, root) for v in raw if isinstance(v, str) and v]
            if len(values) != len(raw):
                raise ReviewError(400, f"{key} has invalid paths")
            for value in values:
                argv.extend((flag, value))
            parsed[key] = values
            continue
        if typ == "int":
            if isinstance(raw, bool) or not isinstance(raw, int) or not 0 <= raw <= 100000:
                raise ReviewError(400, f"{key} must be an integer from 0 to 100000")
            value = str(raw)
        elif typ == "float":
            if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not 0 <= raw <= 10000:
                raise ReviewError(400, f"{key} must be a nonnegative finite number")
            value = str(raw)
        elif typ in ("file", "resume"):
            if not isinstance(raw, str) or not raw.strip() or len(raw) > 1024:
                raise ReviewError(400, f"{key} must be a path")
            value = _file(raw, root, resume=typ == "resume")
        elif typ.startswith("enum:"):
            if not isinstance(raw, str) or raw not in typ[5:].split("|"):
                raise ReviewError(400, f"{key} has an unsupported value")
            value = raw
        elif typ == "text":
            if not isinstance(raw, str) or not SAFE_TEXT.fullmatch(raw):
                raise ReviewError(400, f"{key} must be 1–300 printable characters")
            value = raw
        else:
            raise RuntimeError(f"Unknown schema type: {typ}")
        argv.extend((flag, value))
        parsed[key] = raw if typ in ("int", "float") else value
    if parsed.get("live") and command in {"replies", "legacy", "legacy-researchers"} and not parsed.get("send"):
        raise ReviewError(400, "Live requires selecting Send for this command")
    if command == "send" and parsed.get("review_to") and not parsed.get("review"):
        raise ReviewError(400, "Review-to requires Review")
    live = bool(parsed.get("live") or (command == "send" and
                (parsed.get("review") or parsed.get("review_to"))))
    if command in LIVE_COMMANDS and live:
        if "limit" in parsed and parsed["limit"] <= 0:
            raise ReviewError(400, "Live send limit must be at least one")
        if parsed.get("limit", 0) > 40:
            raise ReviewError(400, "Live send limit cannot exceed 40")
        if parsed.get("delay_min", 60) < 60 or parsed.get("delay_max", 60) < 60:
            raise ReviewError(400, "Live SMTP delays must be at least 60 seconds")
        if parsed.get("delay_max", 0) and parsed.get("delay_min", 0) \
                and parsed["delay_max"] < parsed["delay_min"]:
            raise ReviewError(400, "Maximum delay must not be below minimum delay")
        window = parsed.get("local_window", "9-17")
        if not WINDOW.fullmatch(window):
            raise ReviewError(400, "Live sending requires recipient-local hours (e.g. 9-17)")
        if "local_window" not in parsed:
            argv.extend(("--local-window", window))
        if confirmation != f"SEND {command.upper()}":
            raise ReviewError(403, f"Type SEND {command.upper()} to confirm live SMTP")
    elif command == "archive-sent" and parsed.get("live"):
        if confirmation != "ARCHIVE":
            raise ReviewError(403, "Type ARCHIVE to confirm copying mail to IMAP")
    elif confirmation:
        raise ReviewError(400, "Confirmation only applies to live mail actions")
    if parsed.get("at") and command != "send":
        raise ReviewError(400, "Scheduled send time is only for first sends")
    return argv, live
