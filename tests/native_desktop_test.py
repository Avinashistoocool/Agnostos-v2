"""Native Qt widgets smoke-tested with isolated project-local v2 files."""
from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch

from openpyxl import Workbook

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication, QLineEdit
from desktop_review.commands import COMMANDS, build_argv
from desktop_review.native import DesktopWindow
from desktop_review.storage import Workspace
from desktop_review.storage import ReviewError, read_drafts, update_draft


class NativeDesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = ROOT / "build" / "native-desktop-test"
        if cls.scratch.exists():
            shutil.rmtree(cls.scratch)
        cls.output = cls.scratch / "repo" / "output"
        cls.output.mkdir(parents=True)
        code = cls.scratch / "repo" / "outreach"
        code.mkdir()
        (code / "cli.py").write_text(
            "# queue_operation(settings.output_dir\n# workbook_operation(settings.output_dir",
            encoding="utf-8")
        (code / "replier.py").write_text("# write_queue(path,", encoding="utf-8")
        (code / "queue_store.py").write_text("# def workbook_operation(", encoding="utf-8")
        book = Workbook()
        book.active.append(["Professor Name", "Email Address", "Custom Email Draft",
                            "Send Status", "Sent At"])
        book.active.append(["Professor Fixture", "fixture@example.org", "Draft", ""])
        book.active.append(["Professor Sent", "sent@example.org", "Sent draft",
                            "sent", "2026-10-30"])
        book.save(cls.output / "professors.xlsx")
        book.close()
        (cls.output / "reply_queue.json").write_text(json.dumps([{
            "name": "Fixture", "email": "fixture@example.org", "subject": "Re: ",
            "body": "Unsent", "approved": False, "action": "reply", "sent_at": ""}]), encoding="utf-8")
        (cls.output / "conversations.html").write_text(
            "<html><style>body{display:none}</style><p>Saved thread</p>"
            "<script>evil()</script></html>", encoding="utf-8")
        cls.app = QApplication.instance() or QApplication([])
        cls.workspace = Workspace(cls.scratch / "appdata")
        cls.workspace.select(str(cls.scratch / "repo"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.scratch)

    def test_native_tabs_and_all_cli_forms(self):
        isolated = subprocess.run(
            [sys.executable, "-c",
             "import sys; import desktop_review.native; "
             "assert 'desktop_review.app' not in sys.modules"],
            cwd=ROOT, capture_output=True, text=True, timeout=20)
        self.assertEqual(isolated.returncode, 0, isolated.stderr)
        window = DesktopWindow(self.workspace)
        try:
            self.assertEqual(window.tabs.count(), 7)
            self.assertEqual(window.command_select.count(), len(COMMANDS))
            window.command_select.setCurrentIndex(
                list(COMMANDS).index("run"))
            self.assertIn("mode", window.option_inputs)
            window.command_select.setCurrentIndex(
                list(COMMANDS).index("send"))
            self.assertFalse(window.option_inputs["live"][1].isChecked())
            window.refresh_conversations()
            self.assertIn("Saved thread", window.conversation_text.toPlainText())
            self.assertNotIn("evil()", window.conversation_text.toPlainText())
            self.assertEqual(window.reply_list.count(), 1)
            self.assertEqual(window.draft_list.count(), 1)
            self.assertEqual(window.metrics.text().split()[0], "Researchers")
        finally:
            window.close()

    def test_secrets_masked_and_no_implicit_live_start(self):
        window = DesktopWindow(self.workspace)
        try:
            window.jobs.settings.save({"SMTP_PASSWORD": "fixture-secret"})
            window.refresh_settings()
            password = window._controls["SMTP_PASSWORD"]
            self.assertEqual(password.echoMode(), QLineEdit.Password)
            self.assertEqual(password.text(), "")
            window.command_select.setCurrentIndex(list(COMMANDS).index("send"))
            window.option_inputs["live"][1].setChecked(True)
            with patch("desktop_review.native.QInputDialog.getText", return_value=("wrong", True)), \
                 patch.object(window.jobs, "start", side_effect=AssertionError("Must not start")):
                window.start_command()
        finally:
            window.close()

    def test_internal_cli_rejects_raw_flags_even_with_forged_environment(self):
        from desktop_review.launcher import main
        job_id = "c" * 24
        nonce = "only-a-test-nonce-with-enough-length"
        result = self.workspace.config_dir / "jobs" / (job_id + ".result.json")
        result.parent.mkdir(parents=True, exist_ok=True)
        record = {"id": job_id, "command": "stats", "options": {},
                  "confirmation": None, "argv": ["stats"],
                  "workspace": str(self.workspace.path),
                  "nonce_hash": hashlib.sha256(nonce.encode()).hexdigest()}
        (result.parent / (job_id + ".json")).write_text(json.dumps(record), encoding="utf-8")
        environment = {
            "LOCALAPPDATA": str(self.workspace.config_dir.parent),
            "AGNOSTOS_DESKTOP_WORKSPACE": str(self.workspace.path),
            "AGNOSTOS_DESKTOP_JOB_RESULT": str(result),
            "AGNOSTOS_DESKTOP_CONFIG_DIR": str(self.workspace.config_dir),
            "AGNOSTOS_DESKTOP_JOB_NONCE": nonce,
            "AGNOSTOS_ENV_FILE": str(self.workspace.path / ".env"),
            "AGNOSTOS_DESKTOP_JOB_SPEC": json.dumps({
                "command": "stats", "options": {}, "confirmation": None}),
        }
        cwd = Path.cwd()
        try:
            os.chdir(self.workspace.path)
            with patch.dict(os.environ, environment), \
                 patch("outreach.cli.main", side_effect=AssertionError("Must not run raw CLI")):
                self.assertEqual(main(["--cli", "stats", "--yes"]), 3)
                self.assertEqual(main(["--cli", "send", "--live", "--no-focus"]), 3)
            self.assertFalse(result.exists())
        finally:
            os.chdir(cwd)

    def test_live_zero_limit_cannot_fall_back_to_full_cap(self):
        for command in ("send", "resend"):
            for value in (0, -1):
                with self.subTest(command=command, limit=value), \
                     self.assertRaises(ReviewError) as rejected:
                    build_argv(self.workspace, command, {"live": True, "limit": value},
                               f"SEND {command.upper()}")
                self.assertEqual(rejected.exception.status, 400)

    def test_external_cli_workbook_lock_rejects_draft_edits(self):
        revision = read_drafts(self.workspace)["version"]
        script = """
import sys
from pathlib import Path
from outreach.queue_store import workbook_operation
with workbook_operation(Path(sys.argv[1])):
    print("locked", flush=True)
    sys.stdin.readline()
"""
        child = subprocess.Popen(
            [sys.executable, "-c", script, str(self.output)],
            cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(), "locked")
            with self.assertRaises(ReviewError) as busy:
                update_draft(self.workspace, "Sheet", 2, revision, "Busy edit")
            self.assertEqual(busy.exception.status, 409)
            self.assertEqual(read_drafts(self.workspace)["items"][0]["body"], "Draft")
            _, stderr = child.communicate(input="\n", timeout=15)
            self.assertEqual(child.returncode, 0, stderr)
        finally:
            if child.poll() is None:
                child.communicate(input="\n", timeout=15)

    def test_native_first_draft_edit_never_changes_sent_row(self):
        from openpyxl import load_workbook
        from PySide6.QtWidgets import QMessageBox
        window = DesktopWindow(self.workspace)
        try:
            window.draft_list.setCurrentRow(0)
            window.draft_body.setPlainText("Edited unsent draft")
            with patch("desktop_review.native.QMessageBox.question",
                       return_value=QMessageBox.Yes):
                window.save_draft()
            book = load_workbook(self.output / "professors.xlsx", read_only=True)
            try:
                self.assertEqual(book.active["C2"].value, "Edited unsent draft")
                self.assertEqual(book.active["C3"].value, "Sent draft")
            finally:
                book.close()
            revision = read_drafts(self.workspace)["version"]
            with self.assertRaises(ReviewError) as sent:
                update_draft(self.workspace, "Sheet", 3, revision, "Forbidden sent edit")
            self.assertEqual(sent.exception.status, 409)
            with self.assertRaises(ReviewError) as stale:
                update_draft(self.workspace, "Sheet", 2, "0" * 64, "Stale edit")
            self.assertEqual(stale.exception.status, 409)
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
