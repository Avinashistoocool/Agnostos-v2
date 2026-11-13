"""Offline contract checks for the desktop CLI boundary and job controls."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from desktop_review.commands import COMMANDS, build_argv
from desktop_review.jobs import Jobs
from desktop_review.settings import SECRETS, SettingsStore
from desktop_review.storage import ReviewError, Workspace


class FakeProcess:
    def __init__(self):
        self.pid = os.getpid()
        self.stdin = None
        self.finished = threading.Event()
        self.returncode = None

    def poll(self):
        return self.returncode

    def wait(self):
        self.finished.wait(5)
        return self.returncode if self.returncode is not None else -1

    def terminate(self):
        self.returncode = -15
        self.finished.set()


class FullDesktopContractTests(unittest.TestCase):
    def setUp(self):
        # Keep fixtures in the repository, never in the shared tests/_tmp or real output.
        self.scratch = tempfile.TemporaryDirectory(prefix="desktop-contract-", dir=ROOT)
        self.addCleanup(self.scratch.cleanup)
        base = Path(self.scratch.name)
        path = base / "workspace"
        (path / "outreach").mkdir(parents=True)
        (path / "outreach" / "cli.py").write_text("# fixture\n", encoding="utf-8")
        (path / "output").mkdir()
        self.workspace = Workspace(base / "config")
        self.workspace.select(str(path))

    def assert_rejected(self, command, options, status=400, confirmation=None):
        with self.assertRaises(ReviewError) as caught:
            build_argv(self.workspace, command, options, confirmation)
        self.assertEqual(caught.exception.status, status, str(caught.exception))

    def test_every_public_cli_command_is_in_desktop_allowlist(self):
        # Building the parser does not execute any commands or contact services.
        with patch.dict(os.environ, {"PYTHON_DOTENV_DISABLED": "1"}):
            from outreach.cli import build_parser
        parser = build_parser()
        subcommands = next(action for action in parser._actions
                           if isinstance(action, argparse._SubParsersAction))
        self.assertEqual(set(subcommands.choices), set(COMMANDS))
        for command in COMMANDS:
            with self.subTest(command=command):
                argv, live = build_argv(self.workspace, command, {})
                self.assertEqual(argv, [command])
                self.assertFalse(live)
                self.assertEqual(parser.parse_args(argv).command, command)

    def test_every_allowlisted_flag_is_accepted_by_the_real_parser(self):
        with patch.dict(os.environ, {"PYTHON_DOTENV_DISABLED": "1"}):
            from outreach.cli import build_parser
        parser = build_parser()
        values = {
            "bool": True, "int": 1, "float": 0.5, "text": "ordinary",
            "file": "fixture.xlsx", "resume": "resume.pdf",
            "list": ["other.xlsx"],
        }
        for command, entry in COMMANDS.items():
            for name, kind in entry["fields"].items():
                # Live actions are checked separately; parser compatibility is
                # independent of whether the desktop authorizes execution.
                value = kind[5:].split("|")[0] if kind.startswith("enum:") else values[kind]
                flag = "--" + name.replace("_", "-")
                args = [command, flag]
                if kind != "bool":
                    args += [str(value[0] if kind == "list" else value)]
                with self.subTest(command=command, flag=flag):
                    try:
                        parser.parse_args(args)
                    except SystemExit as exc:
                        self.fail(f"{command} desktop exposes {flag}, but CLI rejects it ({exc.code})")

    def test_unlisted_commands_bypass_flags_and_malformed_types_are_rejected(self):
        for command in ("", "send; echo injected", "--help", "not-a-command"):
            self.assert_rejected(command, {})
        for option in ("yes", "approve_all", "no_focus", "allow_unverified",
                       "weekends", "no_backup", "skip", "resend", "dry_run"):
            self.assert_rejected("send", {option: True})
        for command, options in [
            ("run", {"no_enrich": "false"}), ("run", {"max_professors": True}),
            ("run", {"max_professors": -1}), ("run", {"budget": float("nan")}),
            ("run", {"budget": float("inf")}), ("run", {"mode": "bad"}),
            ("send", {"sheet": "line\n--live"}), ("discover", {"exclude": "file.xlsx"}),
            ("discover", {"exclude": ["ok.xlsx", 42]}),
            ("send", {"xlsx": "..\\outside.xlsx"}),
        ]:
            with self.subTest(command=command, options=options):
                self.assert_rejected(command, options)
        self.assert_rejected("send", [])
        self.assert_rejected("run", {"output": str(Path(self.scratch.name).parent / "outside.xlsx")})
        argv, live = build_argv(self.workspace, "run",
                                {"sheet": "physics; echo injected", "mode": "scrape"})
        self.assertFalse(live)
        self.assertEqual(argv, ["run", "--sheet", "physics; echo injected",
                                "--mode", "scrape"])

    def test_mail_defaults_and_confirmations(self):
        for command in ("send", "resend", "replies", "archive-sent",
                        "legacy", "legacy-researchers", "coordinators"):
            with self.subTest(command=command):
                argv, live = build_argv(self.workspace, command, {})
                self.assertFalse(live)
                self.assertNotIn("--live", argv)
                self.assert_rejected(command, {}, confirmation="SEND SEND")
        for command, options in [
            ("send", {"live": True}), ("send", {"review": True}),
            ("resend", {"live": True}), ("replies", {"send": True, "live": True}),
            ("legacy", {"send": True, "live": True}),
            ("legacy-researchers", {"send": True, "live": True}),
            ("coordinators", {"send": True, "live": True}),
        ]:
            with self.subTest(command=command, options=options):
                self.assert_rejected(command, options, status=403)
                argv, live = build_argv(self.workspace, command, options,
                                        f"SEND {command.upper()}")
                self.assertTrue(live)
                self.assertIn("--local-window", argv)
        for command in ("legacy", "legacy-researchers", "coordinators"):
            self.assert_rejected(command, {"live": True},
                                 confirmation=f"SEND {command.upper()}")
        self.assert_rejected("replies", {"live": True}, confirmation="SEND REPLIES")
        self.assert_rejected("send", {"review_to": "fixture@example.org"})
        self.assert_rejected("send", {"live": True, "local_window": "off"},
                             confirmation="SEND SEND")
        self.assert_rejected("archive-sent", {"live": True}, status=403)
        argv, live = build_argv(self.workspace, "archive-sent", {"live": True},
                                confirmation="ARCHIVE")
        self.assertIn("--live", argv)
        self.assertTrue(live)

    def test_settings_public_view_masks_secrets_without_writing_env(self):
        store = SettingsStore(self.workspace)
        secret = "fixture-secret-never-return"
        with patch.object(store, "_secrets", return_value={key: secret for key in SECRETS}):
            public = store.public()
            self.assertEqual(set(public["values"]), set(public["fields"]))
            for key in SECRETS:
                self.assertEqual(public["values"][key], {"configured": True})
            self.assertNotIn(secret, str(public))
        self.assertFalse((self.workspace.path / ".env").exists())
        self.assert_rejected("run", {"yes": True})

    def test_job_lifecycle_and_cancel_never_spawn_real_process(self):
        jobs = Jobs(self.workspace)
        process = FakeProcess()
        with patch("desktop_review.jobs.subprocess.Popen", return_value=process) as spawn, \
             patch("desktop_review.jobs.lock_held", return_value=False):
            record = jobs.start("send", {}, None)
            self.assertFalse(record["live"])
            self.assertEqual(record["status"], "running")
            self.assertEqual(spawn.call_count, 1)
            self.assertIsInstance(spawn.call_args.args[0], list)
            self.assertNotIn("--live", spawn.call_args.args[0])
            self.assertFalse(spawn.call_args.kwargs.get("shell", False))
            self.assertEqual(spawn.call_args.kwargs["cwd"], self.workspace.path)
            self.assertEqual(jobs.get(record["id"])["status"], "running")
            self.assertEqual(jobs.list()[0]["id"], record["id"])
            with self.assertRaises(ReviewError) as busy:
                jobs.start("stats", {}, None)
            self.assertEqual(busy.exception.status, 409)
            with self.assertRaises(ReviewError) as wrong_input:
                jobs.input(record["id"], "yes; send")
            self.assertEqual(wrong_input.exception.status, 400)
            self.assertEqual(jobs.cancel(record["id"]), {"ok": True})
            deadline = time.monotonic() + 3
            while jobs.get(record["id"])["status"] == "running" and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertEqual(jobs.get(record["id"])["status"], "cancelled")
            self.assertEqual(jobs.get(record["id"])["exit_code"], -15)
            with self.assertRaises(ReviewError) as invalid:
                jobs.get("..")
            self.assertEqual(invalid.exception.status, 400)

    def test_live_job_cannot_be_cancelled_mid_delivery(self):
        jobs = Jobs(self.workspace)
        process = FakeProcess()
        with patch("desktop_review.jobs.subprocess.Popen", return_value=process), \
             patch("desktop_review.jobs.lock_held", return_value=False):
            record = jobs.start("send", {"live": True}, "SEND SEND")
            try:
                self.assertTrue(record["live"])
                with self.assertRaises(ReviewError) as rejected:
                    jobs.cancel(record["id"])
                self.assertEqual(rejected.exception.status, 409)
            finally:
                process.terminate()
                deadline = time.monotonic() + 3
                while jobs.active_id is not None and time.monotonic() < deadline:
                    time.sleep(0.01)


if __name__ == "__main__":
    unittest.main()
