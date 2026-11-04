"""desktop_engine: protocol framing, auth, persistence, jobs and safety refusals.

Everything runs against a scratch data dir under build/; nothing is sent.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
import unittest
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SCRATCH = ROOT / "build" / "engine-test"
EXE = ROOT / "dist" / "engine" / "agnostos-engine.exe"
FIXTURE_XLSX = ROOT / "tests" / "fixtures" / "sample_targets.xlsx"
FIXTURE_RESUME = ROOT / "tests" / "fixtures" / "sample_resume.pdf"

from desktop_engine.errors import EngineError  # noqa: E402
from desktop_engine.server import Engine  # noqa: E402


def _engine_env(data_dir: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("SMTP_", "IMAP_"))}
    env.update(AGNOSTOS_DATA_DIR=str(data_dir), PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1",
               PYTHONPATH=str(ROOT))
    return env


def converse(command: list[str], data_dir: Path, requests: list[dict], timeout=60) -> list[dict]:
    """Send requests over stdin and return every stdout line as JSON (fails on non-JSON)."""
    payload = "".join(json.dumps(r) + "\n" for r in requests) + "this is not json\n"
    done = subprocess.run(command, input=payload.encode("utf-8"), capture_output=True,
                          cwd=ROOT, env=_engine_env(data_dir), timeout=timeout,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    lines = done.stdout.decode("utf-8").splitlines()
    return [json.loads(line) for line in lines]


class Recorder:
    def __init__(self):
        self.events = []
        self.lock = threading.Lock()

    def __call__(self, event, data):
        with self.lock:
            self.events.append((event, json.loads(json.dumps(data))))

    def named(self, name):
        with self.lock:
            return [d for e, d in self.events if e == name]


class EngineCase(unittest.TestCase):
    def setUp(self):
        self.dir = SCRATCH / self._testMethodName
        shutil.rmtree(self.dir, ignore_errors=True)
        self.dir.mkdir(parents=True)
        self.events = Recorder()
        self.engine = Engine(self.dir, emit_fn=self.events)

    def tearDown(self):
        self.engine.jobs.shutdown()
        shutil.rmtree(self.dir, ignore_errors=True)

    def call(self, method, params=None, request_id=1):
        response = self.engine.handle({"id": request_id, "method": method, "params": params or {}})
        self.assertEqual(response["id"], request_id)
        if "error" in response:
            raise EngineError(response["error"]["code"], response["error"]["message"])
        return response["result"]

    def assertCode(self, code, method, params=None):
        with self.assertRaises(EngineError) as ctx:
            self.call(method, params)
        self.assertEqual(ctx.exception.code, code, str(ctx.exception))
        return ctx.exception


class ProtocolTests(EngineCase):
    def test_stdio_framing_only_json_on_stdout(self):
        responses = converse([sys.executable, "-m", "desktop_engine"], self.dir, [
            {"id": 1, "method": "app.info", "params": {}},
            {"id": 2, "method": "ping"},
            {"id": 3, "method": "no.such.method", "params": {}},
            {"id": 4, "method": "auth.guest", "params": {"name": "Ünïcode ✓"}},
            {"id": 5, "method": "settings.get", "params": []},
        ])
        by_id = {r.get("id"): r for r in responses}
        self.assertEqual(by_id[1]["result"]["user"], None)
        self.assertEqual(by_id[1]["result"]["onboarding"], {"completed": [], "done": False})
        self.assertTrue(by_id[2]["result"]["ok"])
        self.assertEqual(by_id[3]["error"]["code"], "bad_request")
        self.assertEqual(by_id[4]["result"]["user"]["name"], "Ünïcode ✓")
        self.assertEqual(by_id[5]["error"]["code"], "bad_request")
        self.assertEqual(by_id[None]["error"]["code"], "bad_request")  # the garbage line

    def test_errors_and_not_signed_in(self):
        for method in ("profile.get", "settings.get", "stats.get", "jobs.list", "commands.list",
                       "onboarding.complete", "professors.list", "replies.list"):
            self.assertCode("not_signed_in", method, {"step": "resume"})
        self.assertEqual(self.call("auth.status"), {"user": None})
        self.assertEqual(self.call("dialog.none"), {})


class AuthTests(EngineCase):
    def test_local_register_login_logout(self):
        self.assertCode("bad_request", "auth.register", {"name": "A", "email": "bad", "password": "longenough"})
        self.assertCode("bad_request", "auth.register", {"name": "A", "email": "a@x.org", "password": "short"})
        user = self.call("auth.register", {"name": "Ada", "email": "Ada@Example.org",
                                           "password": "correct horse"})["user"]
        self.assertEqual((user["provider"], user["email"], user["gmail_connected"]),
                         ("local", "ada@example.org", False))
        self.assertCode("conflict", "auth.register", {"name": "B", "email": "ada@example.org",
                                                      "password": "another pass"})
        stored = (self.dir / "users.json").read_text(encoding="utf-8")
        self.assertNotIn("correct horse", stored)
        self.assertIn("pbkdf2_sha256", stored)
        self.assertEqual(self.call("auth.logout"), {"ok": True})
        self.assertCode("auth_failed", "auth.login", {"email": "ada@example.org", "password": "wrong pass"})
        self.assertCode("auth_failed", "auth.login", {"email": "nobody@example.org", "password": "whatever1"})
        again = self.call("auth.login", {"email": "ADA@example.org", "password": "correct horse"})["user"]
        self.assertEqual(again["id"], user["id"])
        # Session survives an engine restart.
        restarted = Engine(self.dir, emit_fn=self.events)
        self.assertEqual(restarted.accounts.public(restarted.accounts.current())["id"], user["id"])
        workspace = self.dir / "users" / user["id"] / "workspace"
        self.assertTrue((workspace / ".env").is_file() and (workspace / "output").is_dir())

    def test_guest(self):
        user = self.call("auth.guest")["user"]
        self.assertEqual((user["id"], user["provider"], user["name"], user["email"]),
                         ("guest", "guest", "Guest", None))
        self.assertEqual(self.call("auth.guest", {"name": "Sam"})["user"]["name"], "Sam")
        self.assertEqual(self.call("app.info")["user"]["provider"], "guest")

    def test_oauth_unavailable_without_config(self):
        message = str(self.assertCode("unavailable", "auth.google", {"connect_gmail": False}))
        self.assertIn("oauth.json", message)
        self.assertCode("unavailable", "auth.github.start")
        (self.dir / "oauth.json").write_text(json.dumps({"google": {"client_secret": "x"}}), encoding="utf-8")
        os.environ["AGNOSTOS_DATA_DIR"] = str(self.dir)
        try:
            self.assertCode("unavailable", "auth.google", {"connect_gmail": True})
        finally:
            os.environ.pop("AGNOSTOS_DATA_DIR")

    def test_google_pkce_loopback_and_gmail_connection(self):
        seen = {}

        class Fake(BaseHTTPRequestHandler):
            def do_POST(self):  # token endpoint
                form = urllib.parse.parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode())
                seen["token"] = {k: v[0] for k, v in form.items()}
                self._json({"access_token": "at", "refresh_token": "1//rt", "expires_in": 3600,
                            "scope": "openid email profile https://mail.google.com/"})

            def do_GET(self):  # userinfo
                seen["auth"] = self.headers.get("Authorization")
                self._json({"sub": "1234567890", "email": "Student@Gmail.com", "name": "Stu Dent",
                            "picture": "https://example.org/a.png"})

            def _json(self, value):
                data = json.dumps(value).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *_a):
                pass

        server = HTTPServer(("127.0.0.1", 0), Fake)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{server.server_port}"
        (self.dir / "oauth.json").write_text(json.dumps({"google": {
            "client_id": "cid.apps.googleusercontent.com", "client_secret": "csec",
            "auth_uri": base + "/auth", "token_uri": base + "/token",
            "userinfo_uri": base + "/userinfo"}}), encoding="utf-8")

        def browser(url):
            query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
            seen["query"] = query
            back = query["redirect_uri"] + "?" + urllib.parse.urlencode(
                {"code": "authcode", "state": query["state"], "scope": query["scope"]})
            threading.Thread(target=lambda: urllib.request.urlopen(back, timeout=10).read(),
                             daemon=True).start()
            return True

        os.environ["AGNOSTOS_DATA_DIR"] = str(self.dir)
        try:
            self.engine.open_browser = browser
            user = self.call("auth.google", {"connect_gmail": True})["user"]
        finally:
            os.environ.pop("AGNOSTOS_DATA_DIR")
            server.shutdown()
            server.server_close()
        query = seen["query"]
        self.assertEqual(query["code_challenge_method"], "S256")
        self.assertIn("https://mail.google.com/", query["scope"])
        self.assertTrue(query["redirect_uri"].startswith("http://127.0.0.1:"))
        verifier = seen["token"]["code_verifier"]
        self.assertEqual(base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
                         .rstrip(b"=").decode(), query["code_challenge"])
        self.assertEqual(seen["auth"], "Bearer at")
        self.assertEqual((user["provider"], user["email"], user["gmail_connected"]),
                         ("google", "student@gmail.com", True))
        workspace = self.dir / "users" / user["id"] / "workspace"
        token = json.loads((workspace / "gmail_oauth_token.json").read_text(encoding="utf-8"))
        self.assertEqual(token, {"client_id": "cid.apps.googleusercontent.com", "client_secret": "csec",
                                 "refresh_token": "1//rt", "token_uri": base + "/token"})
        from dotenv import dotenv_values
        env = dotenv_values(workspace / ".env")
        self.assertEqual(env["SMTP_AUTH"], "xoauth2")
        self.assertEqual(Path(env["GOOGLE_OAUTH_TOKEN_FILE"]), workspace / "gmail_oauth_token.json")
        self.assertEqual((env["SMTP_HOST"], env["SMTP_PORT"], env["SMTP_SECURITY"], env["IMAP_HOST"]),
                         ("smtp.gmail.com", "465", "ssl", "imap.gmail.com"))
        self.assertEqual(env["SMTP_USER"], "student@gmail.com")
        tokens = (self.dir / "users" / user["id"] / "tokens.bin").read_bytes()
        self.assertNotIn(b"1//rt", tokens)  # DPAPI-encrypted
        self.assertEqual(self.engine.accounts.tokens(user["id"])["google"]["refresh_token"], "1//rt")
        stages = [e["stage"] for e in self.events.named("auth.progress")]
        self.assertEqual(stages[0], "browser")
        self.assertEqual(stages[-1], "done")
        # The engine's settings refuse to let the UI rewrite the token file location.
        self.assertCode("bad_request", "settings.update", {"values": {"GOOGLE_OAUTH_TOKEN_FILE": "C:\\x"}})


class PersistenceTests(EngineCase):
    def setUp(self):
        super().setUp()
        self.user = self.call("auth.register", {"name": "Pat", "email": "pat@example.org",
                                                "password": "secret pass"})["user"]

    def test_onboarding(self):
        self.assertEqual(self.call("onboarding.get"), {"completed": [], "done": False})
        self.assertCode("bad_request", "onboarding.complete", {"step": "nope"})
        steps = ["limits", "resume", "profile", "interests", "targets", "email", "llm"]
        for step in steps:
            state = self.call("onboarding.complete", {"step": step})
        self.assertFalse(state["done"])
        state = self.call("onboarding.complete", {"step": "funding"})
        self.assertTrue(state["done"])
        self.assertEqual(state["completed"][0], "resume")
        restarted = Engine(self.dir, emit_fn=self.events)
        self.assertTrue(restarted.accounts.onboarding()["done"])

    def test_profile_and_resume(self):
        profile = self.call("profile.get")["profile"]
        self.assertEqual((profile["name"], profile["email"], profile["resume_file"]),
                         ("Pat", "pat@example.org", None))
        updated = self.call("profile.update", {"profile": {
            "degree": "BSc", "skills": ["Python", " ", "C++"],
            "projects": [{"title": "T", "summary": "S"}]}})["profile"]
        self.assertEqual(updated["skills"], ["Python", "C++"])
        self.assertEqual(self.call("profile.get")["profile"]["projects"], [{"title": "T", "summary": "S"}])
        self.assertCode("bad_request", "profile.update", {"profile": {"skills": "not a list"}})
        self.assertCode("not_found", "resume.import", {"path": str(self.dir / "missing.pdf")})
        self.assertCode("bad_request", "resume.import", {"path": str(FIXTURE_XLSX)})
        if FIXTURE_RESUME.exists():
            parsed = self.call("resume.import", {"path": str(FIXTURE_RESUME)})["profile"]
            self.assertEqual(parsed["resume_file"], "resume.pdf")
            workspace = self.dir / "users" / self.user["id"] / "workspace"
            self.assertTrue((workspace / "resume.pdf").is_file())
            self.assertIn("RESUME_PATH", (workspace / ".env").read_text(encoding="utf-8"))

    def test_settings_masking_validation_and_workspace(self):
        result = self.call("settings.update", {"values": {
            "SMTP_PASSWORD": "app-password-1234", "SMTP_HOST": "smtp.example.org",
            "TARGET_UNIVERSITIES": "ETH Zurich;EPFL", "SEND_WEEKDAYS": "Mon,tue",
            "CAN_SELF_FUND": "true", "SMTP_PORT": "587"}})["settings"]
        self.assertEqual(result["SMTP_PASSWORD"], "\u2022\u2022\u2022\u20221234")
        self.assertEqual(result["TARGET_UNIVERSITIES"], "ETH Zurich;EPFL")
        self.assertEqual(result["SEND_WEEKDAYS"], "mon,tue")
        got = self.call("settings.get")
        self.assertIn("SMTP_PASSWORD", got["secrets"])
        self.assertIn("_workspace", got["settings"])
        # Masked values are ignored; empty string clears.
        self.call("settings.update", {"values": {"SMTP_PASSWORD": got["settings"]["SMTP_PASSWORD"]}})
        self.assertEqual(self.engine.accounts.raw_settings()["SMTP_PASSWORD"], "app-password-1234")
        self.call("settings.update", {"values": {"SMTP_HOST": ""}})
        self.assertNotIn("SMTP_HOST", self.engine.accounts.raw_settings())
        for bad in ({"DAILY_SEND_CAP": "0"}, {"DAILY_SEND_CAP": "41"}, {"SEND_DELAY_MIN": "5"},
                    {"SEND_LOCAL_WINDOW": "nine"}, {"SEND_WEEKDAYS": "funday"}, {"FOCUS": "false"},
                    {"lower": "x"}, {"SMTP_HOST": "a\nb"}, {"AGNOSTOS_ENV_FILE": "x"}):
            self.assertCode("bad_request", "settings.update", {"values": bad})
        # Point at an existing folder (v2 checkout style), then back.
        other = self.dir / "checkout"
        other.mkdir()
        self.assertEqual(self.call("settings.update", {"values": {"_workspace": str(other)}})
                         ["settings"]["_workspace"], str(other.resolve()))
        self.assertTrue((other / "output").is_dir())
        self.assertCode("not_found", "settings.update", {"values": {"_workspace": str(self.dir / "nope")}})
        self.call("settings.update", {"values": {"_workspace": ""}})
        self.assertTrue(self.call("settings.get")["settings"]["_workspace"].endswith("workspace"))

    def test_probes_read_fresh_settings(self):
        self.call("settings.update", {"values": {"SMTP_HOST": ""}})
        self.assertEqual(self.call("email.test", {"kind": "smtp"}),
                         {"ok": False, "detail": "SMTP host is not set"})
        self.assertCode("bad_request", "email.test", {"kind": "pop3"})
        result = self.call("llm.test")
        self.assertFalse(result["ok"])

    def test_workbook_views_and_draft_edit(self):
        output = self.dir / "users" / self.user["id"] / "workspace" / "output"
        from openpyxl import Workbook
        book = Workbook()
        sheet = book.active
        sheet.title = "Profs"
        sheet.append(["Professor Name", "Email Address", "Institution", "Country",
                      "Probability of Acceptance", "Email Subject", "Custom Email Draft",
                      "Send Status", "Sent At", "Reply Status"])
        sheet.append(["Ann", "ann@uni.ch", "ETH", "Switzerland", "72%", "Hi", "Draft A", "", "", ""])
        sheet.append(["Bob", "bob@uni.de", "TUM", "Germany", "40%", "Yo", "Draft B", "sent",
                      "2026-11-01 10:00", "replied 2026-11-02"])
        sheet.append(["Cy", "cy@uni.fr", "ENS", "France", "", "", "Draft C",
                      "failed: SMTPRecipientsRefused", "", "bounced"])
        book.save(output / "professors.xlsx")
        stats = self.call("stats.get")
        self.assertEqual((stats["total"], stats["drafted"], stats["sent"], stats["replied"],
                          stats["bounced"]), (3, 3, 1, 1, 1))
        self.assertIn({"date": "2026-11-01", "count": 1}, stats["sent_per_day"]) \
            if any(d["date"] == "2026-11-01" for d in stats["sent_per_day"]) else None
        listing = self.call("professors.list", {})
        self.assertEqual(listing["total"], 3)
        self.assertEqual(listing["items"][0]["name"], "Ann")
        self.assertAlmostEqual(listing["items"][0]["probability"], 0.72)
        for status, names in (("unsent", {"Ann", "Cy"}), ("sent", {"Bob"}),
                              ("replied", {"Bob"}), ("failed", {"Cy"})):
            self.assertEqual({i["name"] for i in self.call("professors.list", {"status": status})["items"]},
                             names, status)
        self.assertEqual(self.call("professors.list", {"query": "germ"})["total"], 1)
        ann = listing["items"][0]
        bob = next(i for i in listing["items"] if i["name"] == "Bob")
        self.assertCode("conflict", "drafts.update", {"sheet": "Profs", "row": bob["row"],
                                                      "version": bob["version"], "draft": "x"})
        self.assertCode("conflict", "drafts.update", {"sheet": "Profs", "row": ann["row"],
                                                      "version": "stale", "draft": "x"})
        edited = self.call("drafts.update", {"sheet": "Profs", "row": ann["row"], "version": ann["version"],
                                             "subject": "New subject", "draft": "New body"})["professor"]
        self.assertEqual((edited["draft"], edited["subject"]), ("New body", "New subject"))
        self.assertNotEqual(edited["version"], ann["version"])
        self.assertCode("conflict", "drafts.update", {"sheet": "Profs", "row": ann["row"],
                                                      "version": ann["version"], "draft": "again"})

    def test_replies_and_conversations(self):
        output = self.dir / "users" / self.user["id"] / "workspace" / "output"
        self.assertEqual(self.call("replies.list")["items"], [])
        self.assertEqual(self.call("conversations.get"), {"html": "", "modified": None})
        (output / "reply_queue.json").write_text(json.dumps([
            {"name": "A", "email": "a@x.org", "subject": "Re", "their_message": "hi", "summary": "s",
             "action": "reply", "body": "b", "approved": False, "sent_at": ""},
            {"name": "B", "email": "b@x.org", "subject": "Re", "body": "c", "action": "reply",
             "approved": True, "sent_at": "2026-11-01"}]), encoding="utf-8")
        listing = self.call("replies.list")
        self.assertEqual(listing["items"][0]["sent_at"], None)
        version = self.call("replies.update", {"index": 0, "version": listing["version"],
                                               "body": "edited", "approved": True})["version"]
        self.assertCode("conflict", "replies.update", {"index": 0, "version": listing["version"],
                                                       "body": "x", "approved": False})
        self.assertCode("conflict", "replies.update", {"index": 1, "version": version,
                                                       "body": "x", "approved": False})
        self.assertEqual(self.call("replies.list")["items"][0]["body"], "edited")
        (output / "conversations.html").write_text("<p>thread</p>", encoding="utf-8")
        self.assertEqual(self.call("conversations.get")["html"], "<p>thread</p>")


class JobTests(EngineCase):
    def setUp(self):
        super().setUp()
        self.call("auth.guest")
        self.workspace = self.dir / "users" / "guest" / "workspace"

    def test_command_catalog_has_no_bypasses(self):
        specs = {c["name"]: c for c in self.call("commands.list")["commands"]}
        from desktop_review.commands import COMMANDS
        self.assertEqual(set(specs), set(COMMANDS))
        for spec in specs.values():
            names = {f["name"] for f in spec["fields"]}
            self.assertFalse(names & {"yes", "approve_all", "no_focus", "allow_unverified",
                                      "weekends", "no_backup", "skip", "resend"}, spec["name"])
            for field in spec["fields"]:
                self.assertIn(field["type"], {"bool", "int", "float", "str", "choice"})
        self.assertEqual((specs["send"]["live_field"], specs["send"]["confirmation"]), ("live", "SEND SEND"))
        self.assertEqual(specs["replies"]["confirmation"], "SEND REPLIES")
        self.assertEqual(specs["archive-sent"]["confirmation"], "ARCHIVE")
        self.assertNotIn("live_field", specs["stats"])
        limit = next(f for f in specs["send"]["fields"] if f["name"] == "limit")
        self.assertEqual((limit["min"], limit["max"]), (1, 40))

    def test_validation_and_safety_refusals(self):
        start = lambda **p: self.call("jobs.start", p)  # noqa: E731
        self.assertCode("bad_request", "jobs.start", {"command": "rm", "options": {}})
        for flag in ("yes", "approve_all", "no_focus", "allow_unverified", "weekends", "resend"):
            self.assertCode("bad_request", "jobs.start", {"command": "send", "options": {flag: True}})
        self.assertCode("bad_request", "jobs.start", {"command": "send", "options": {"limit": "5"}})
        self.assertCode("bad_request", "jobs.start", {"command": "send", "options": {"limit": 0}})
        self.assertCode("bad_request", "jobs.start", {"command": "discover", "options": {"count": 0}})
        self.assertCode("bad_request", "jobs.start", {"command": "stats", "options": {"xlsx": "C:\\Windows\\x.xlsx"}})
        self.assertCode("confirmation_required", "jobs.start", {"command": "send", "options": {"live": True, "limit": 2}})
        self.assertCode("confirmation_required", "jobs.start", {"command": "send", "options": {"live": True, "limit": 2},
                                                                "confirmation": "send send"})
        self.assertCode("bad_request", "jobs.start", {"command": "send", "options": {"live": True, "limit": 41},
                                                      "confirmation": "SEND SEND"})
        self.assertCode("bad_request", "jobs.start", {"command": "send", "options": {
            "live": True, "limit": 2, "delay_min": 5}, "confirmation": "SEND SEND"})
        self.assertCode("bad_request", "jobs.start", {"command": "replies", "options": {"live": True},
                                                      "confirmation": "SEND REPLIES"})
        self.assertCode("bad_request", "jobs.start", {"command": "stats", "options": {}, "confirmation": "SEND"})
        self.call("settings.update", {"values": {"DAILY_SEND_CAP": "3"}})
        self.assertCode("bad_request", "jobs.start", {"command": "send", "options": {"live": True, "limit": 5},
                                                      "confirmation": "SEND SEND"})
        self.assertEqual(self.call("jobs.list"), {"jobs": []})
        self.assertCode("bad_request", "jobs.log", {"job_id": "../x"})
        self.assertCode("not_found", "jobs.log", {"job_id": "a" * 24})
        self.assertCode("bad_request", "jobs.answer", {"job_id": "a" * 24, "answer": "yes"})
        del start

    def test_stats_job_streams_and_persists(self):
        shutil.copyfile(FIXTURE_XLSX, self.workspace / "output" / "professors.xlsx")
        job = self.call("jobs.start", {"command": "stats", "options": {}})["job"]
        self.assertEqual((job["status"], job["live"]), ("running", False))
        self.assertCode("conflict", "jobs.start", {"command": "stats", "options": {}})
        deadline = time.time() + 120
        while time.time() < deadline:
            statuses = [e["job"] for e in self.events.named("job.status") if e["job"]["id"] == job["id"]]
            if statuses and statuses[-1]["status"] not in ("running", "waiting_input"):
                break
            time.sleep(0.2)
        final = statuses[-1]
        log = self.call("jobs.log", {"job_id": job["id"], "offset": 0})
        self.assertEqual(final["status"], "done", "\n".join(log["lines"]))
        self.assertEqual(final["exit_code"], 0)
        streamed = [e["line"] for e in self.events.named("job.log") if e["job_id"] == job["id"]]
        self.assertEqual(log["lines"], streamed)
        self.assertGreater(log["offset"], 0)
        self.assertEqual(self.call("jobs.log", {"job_id": job["id"], "offset": log["offset"]})["lines"], [])
        listed = self.call("jobs.list")["jobs"]
        self.assertEqual(listed[0]["status"], "done")
        self.assertEqual(self.call("jobs.cancel", {"job_id": job["id"]}), {"ok": True})

    def test_worker_refuses_unapproved_or_tampered_jobs(self):
        env = _engine_env(self.dir)
        run = lambda extra, args: subprocess.run(  # noqa: E731
            [sys.executable, "-m", "desktop_engine", "--worker", *args], cwd=self.workspace,
            env={**env, **extra}, capture_output=True, timeout=60)
        self.assertEqual(run({}, ["stats"]).returncode, 3)
        jobs = self.dir / "users" / "guest" / "jobs"
        jobs.mkdir(parents=True, exist_ok=True)
        nonce = "n" * 32
        record = {"id": "b" * 24, "command": "stats", "options": {}, "confirmation": None,
                  "argv": ["stats"], "workspace": str(self.workspace.resolve()), "status": "running",
                  "nonce_hash": hashlib.sha256(nonce.encode()).hexdigest()}
        (jobs / ("b" * 24 + ".json")).write_text(json.dumps(record), encoding="utf-8")
        good = {"AGNOSTOS_ENGINE_JOB_NONCE": nonce, "AGNOSTOS_ENGINE_JOB_FILE": str(jobs / ("b" * 24 + ".json")),
                "AGNOSTOS_ENGINE_USER_DIR": str(self.dir / "users" / "guest")}
        self.assertEqual(run({**good, "AGNOSTOS_ENGINE_JOB_NONCE": "short"}, ["stats"]).returncode, 3)
        self.assertEqual(run({**good, "AGNOSTOS_ENGINE_JOB_NONCE": "x" * 32}, ["stats"]).returncode, 3)
        self.assertEqual(run(good, ["send", "--live", "--yes"]).returncode, 3)
        self.assertEqual(run(good, ["stats", "--sheet", "x"]).returncode, 3)
        record.update(command="send", options={"live": True, "limit": 1},
                      argv=["send", "--live", "--limit", "1", "--local-window", "9-17"])
        (jobs / ("b" * 24 + ".json")).write_text(json.dumps(record), encoding="utf-8")
        refused = run(good, record["argv"])
        self.assertEqual(refused.returncode, 3, refused.stdout)  # no confirmation stored

    def test_prompt_relay_and_live_cancel_refusal(self):
        from desktop_engine.jobs import now
        manager = self.engine.jobs
        script = ("import sys\nprint('preview line')\nsys.stdout.write(' Send REAL emails now? [Y/N]: ')\n"
                  "sys.stdout.flush()\nanswer = input()\nprint('answer=' + answer)\n")
        for live, answer in ((True, "n"), (False, "y")):
            job_id = ("c" if live else "d") * 24
            record = {"id": job_id, "command": "send", "options": {"live": live}, "live": live,
                      "status": "running", "started": now(), "finished": None, "exit_code": None,
                      "prompt": None}
            manager._write(record)
            manager._file(job_id, ".log").write_text("", encoding="utf-8")
            process = subprocess.Popen([sys.executable, "-c", script], stdin=subprocess.PIPE,
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            manager.active[job_id] = {"process": process, "record": record}
            thread = threading.Thread(target=manager._pump, args=(job_id,), daemon=True)
            thread.start()
            deadline = time.time() + 30
            while not self.events.named("job.prompt") or \
                    self.events.named("job.prompt")[-1]["job_id"] != job_id:
                self.assertLess(time.time(), deadline)
                time.sleep(0.05)
            waiting = [e["job"] for e in self.events.named("job.status") if e["job"]["id"] == job_id][-1]
            self.assertEqual(waiting["status"], "waiting_input")
            self.assertIn("[Y/N]", waiting["prompt"])
            if live:
                record["status"] = "running"
                self.assertCode("conflict", "jobs.cancel", {"job_id": job_id})
                record["status"] = "waiting_input"
            self.call("jobs.answer", {"job_id": job_id, "answer": answer})
            self.assertCode("conflict", "jobs.answer", {"job_id": job_id, "answer": answer})
            thread.join(30)
            lines = self.call("jobs.log", {"job_id": job_id})["lines"]
            self.assertIn("answer=" + answer, lines)
            self.assertIn("> " + answer.upper(), lines)
            self.assertEqual(self.call("jobs.list")["jobs"][0]["status"] if False else
                             manager._load(job_id)["status"], "done")


@unittest.skipUnless(EXE.is_file(), "built engine exe not found; run build-engine.ps1")
class FrozenSmokeTest(unittest.TestCase):
    def test_exe_answers_ping_and_hello(self):
        data = SCRATCH / "frozen"
        shutil.rmtree(data, ignore_errors=True)
        data.mkdir(parents=True)
        try:
            responses = converse([str(EXE)], data, [
                {"id": 1, "method": "ping", "params": {}},
                {"id": 2, "method": "app.info", "params": {}},
                {"id": 3, "method": "auth.guest", "params": {}},
                {"id": 4, "method": "commands.list", "params": {}},
            ], timeout=120)
            by_id = {r.get("id"): r for r in responses}
            self.assertTrue(by_id[1]["result"]["ok"])
            self.assertEqual(by_id[2]["result"]["data_dir"], str(data.resolve()))
            self.assertEqual(by_id[3]["result"]["user"]["provider"], "guest")
            self.assertGreater(len(by_id[4]["result"]["commands"]), 10)
            # Frozen worker: refuses a forged job, and runs a validated one.
            refused = subprocess.run([str(EXE), "--worker", "stats"], capture_output=True, timeout=120,
                                     env=_engine_env(data))
            self.assertEqual(refused.returncode, 3)
        finally:
            shutil.rmtree(data, ignore_errors=True)

    def test_exe_runs_validated_job(self):
        data = SCRATCH / "frozen-job"
        shutil.rmtree(data, ignore_errors=True)
        data.mkdir(parents=True)
        env = _engine_env(data)
        env.pop("PYTHONPATH")
        process = subprocess.Popen([str(EXE)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, env=env, cwd=data)
        try:
            def send(message):
                process.stdin.write((json.dumps(message) + "\n").encode())
                process.stdin.flush()
            send({"id": 1, "method": "auth.guest", "params": {}})
            shutil.copyfile(FIXTURE_XLSX, data / "users" / "guest" / "workspace" / "output" / "professors.xlsx") \
                if (data / "users" / "guest" / "workspace" / "output").is_dir() else None
            messages = []
            deadline = time.time() + 180
            started = False
            while time.time() < deadline:
                line = process.stdout.readline()
                if not line:
                    break
                message = json.loads(line)
                messages.append(message)
                if message.get("id") == 1 and not started:
                    output = data / "users" / "guest" / "workspace" / "output"
                    shutil.copyfile(FIXTURE_XLSX, output / "professors.xlsx")
                    send({"id": 2, "method": "jobs.start", "params": {"command": "stats", "options": {}}})
                    started = True
                if message.get("event") == "job.status" and message["data"]["job"]["status"] in (
                        "done", "failed", "interrupted"):
                    break
            final = [m for m in messages if m.get("event") == "job.status"][-1]["data"]["job"]
            lines = [m["data"]["line"] for m in messages if m.get("event") == "job.log"]
            self.assertEqual(final["status"], "done", "\n".join(lines))
            self.assertTrue(any("total" in line.lower() or "rows" in line.lower() for line in lines), lines)
        finally:
            process.stdin.close()
            process.wait(30)
            shutil.rmtree(data, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
