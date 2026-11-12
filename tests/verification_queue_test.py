"""Deferred verification is local-only during sending and safe to process later."""
from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _isolate  # noqa: F401

from openpyxl import Workbook, load_workbook
from outreach.verification_queue import defer_rows, verify_deferred
from outreach.queue_store import workbook_operation
from outreach.send_guard import ColdGuard
from outreach.excel_io import load_for_sending


class DeferredTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name)
        self.book = self.out / "professors.xlsx"
        self.row = dict(sheet="Targets", row=2, name="Jane Doe", email="j.doe@example.org",
                        email_status="suspect", institution="University", country="DE",
                        send_status="")

    def queue(self):
        return json.loads((self.out / "verification_queue.json").read_text(encoding="utf-8"))

    def make_book(self, legacy=False):
        if legacy:
            self.book = self.out / "legacy.xlsx"
            self.row["sheet"] = "Legacy researchers"
        wb = Workbook()
        ws = wb.active
        ws.title = self.row["sheet"]
        ws.append(["Name" if legacy else "Professor Name",
                   "Email" if legacy else "Email Address", "Email Status",
                   "Custom Email Draft", "Send Status", "Approved"])
        ws.append([self.row["name"], self.row["email"], "suspect", "Draft", "", "yes"])
        wb.save(self.book)
        wb.close()
        defer_rows(self.out, self.book, [self.row])

    def test_skip_and_deduplicate_without_network(self):
        good = {**self.row, "email": "j.doe@other.org", "email_status": "ok"}
        missing = {**self.row, "name": "John Smith", "email": ""}
        with patch("outreach.verify.verify_many", side_effect=AssertionError("network verification")):
            for _ in range(2):
                result = defer_rows(self.out, self.book, [self.row, missing, good], ColdGuard())
                self.assertEqual(result, [good])
        self.assertEqual(len(self.queue()), 2)

    def test_sent_rows_are_never_queued(self):
        row = {**self.row, "send_status": "sent"}
        self.assertEqual(defer_rows(self.out, self.book, [row]), [row])
        self.assertFalse((self.out / "verification_queue.json").exists())

    def test_name_mismatch_deferred_but_caps_not_queued(self):
        mismatch = {**self.row, "email_status": "ok", "email": "wrong@uni.org"}
        cap = {**self.row, "email_status": "ok"}
        guard = ColdGuard(domain_counts={"example.org": 3})
        self.assertEqual(defer_rows(self.out, self.book, [mismatch, cap], guard), [cap])
        self.assertEqual(len(self.queue()), 1)

    def test_preview_has_no_network_or_writes(self):
        self.make_book()
        before = self.book.read_bytes(), (self.out / "verification_queue.json").read_bytes()
        verify = Mock()
        self.assertEqual(verify_deferred(self.out, verify, dry_run=True), 0)
        verify.assert_not_called()
        self.assertEqual(before, (self.book.read_bytes(), (self.out / "verification_queue.json").read_bytes()))

    def test_sender_lock_postpones_verification(self):
        self.make_book()
        verify = Mock()
        with workbook_operation(self.out):
            self.assertEqual(verify_deferred(self.out, verify), 3)
        verify.assert_not_called()
        self.assertEqual(next(iter(self.queue().values()))["status"], "pending")

    def test_verified_row_saved_then_not_checked_again(self):
        self.make_book()

        def verify(profs):
            profs[0].email_status = "ok"
            profs[0].email_confidence = 95
            profs[0].email_notes = "Official profile"

        self.assertEqual(verify_deferred(self.out, verify), 0)
        wb = load_workbook(self.book)
        self.assertEqual(wb.active.cell(2, 3).value, "ok")
        wb.close()
        self.assertEqual(next(iter(self.queue().values()))["status"], "verified")
        check = Mock()
        verify_deferred(self.out, check)
        check.assert_not_called()

    def test_changed_legacy_recipient_requires_reapproval(self):
        self.make_book(legacy=True)

        def verify(profs):
            profs[0].email = "j.doe@new.org"
            profs[0].email_status = "ok"

        verify_deferred(self.out, verify, apply=True)
        wb = load_workbook(self.book)
        self.assertEqual(wb.active.cell(2, 2).value, "j.doe@new.org")
        self.assertFalse(wb.active.cell(2, 6).value)
        wb.close()

    def test_changed_or_sent_row_is_not_overwritten(self):
        for value, expected in (("elsewhere@uni.org", "stale"), (self.row["email"], "already_sent")):
            self.make_book()
            wb = load_workbook(self.book)
            wb.active.cell(2, 2, value)
            if expected == "already_sent":
                wb.active.cell(2, 5, "sent")
            wb.save(self.book)
            wb.close()
            # Reset this test's earlier result to pending.
            from outreach.verification_queue import store
            with store(self.out) as data:
                for item in data.values():
                    item["status"] = "pending"
            check = Mock()
            verify_deferred(self.out, check)
            check.assert_not_called()
            self.assertEqual(next(iter(self.queue().values()))["status"], expected)

    def test_invalid_result_requires_explicit_retry(self):
        self.make_book()

        def verify(profs):
            profs[0].email_status = "invalid"

        verify_deferred(self.out, verify)
        check = Mock()
        verify_deferred(self.out, check)
        check.assert_not_called()
        verify_deferred(self.out, verify, retry=True)
        self.assertEqual(next(iter(self.queue().values()))["status"], "needs_review")

    def test_missing_email_loader_is_opt_in(self):
        self.row["email"] = ""
        self.make_book()
        self.assertEqual(load_for_sending(self.book), [])
        self.assertEqual(len(load_for_sending(self.book, include_missing=True)), 1)

    def test_malformed_queue_is_an_explicit_error(self):
        (self.out / "verification_queue.json").write_text("broken", encoding="utf-8")
        with self.assertRaises(json.JSONDecodeError):
            defer_rows(self.out, self.book, [self.row])

    def test_legacy_skips_first_unverified_and_sends_next_with_limit_one(self):
        from outreach.cli import build_parser, cmd_legacy
        from outreach.config import settings
        from outreach.resume_parser import ResumeProfile
        pending = [
            {"Name": "Jane Doe", "Email": "j.doe@uni.org", "Draft": "Draft",
             "Approved": "yes", "Email Status": "suspect"},
            {"Name": "John Smith", "Email": "j.smith@uni.org", "Draft": "Draft",
             "Approved": "yes", "Email Status": "ok", "Subject": "Project"},
        ]
        args = build_parser().parse_args(["legacy", "--send", "--limit", "1"])
        with patch.object(settings, "output_dir", self.out), \
                patch.object(settings, "require_resume", return_value=self.out / "cv.pdf"), \
                patch("outreach.cli.parse_resume", return_value=ResumeProfile()), \
                patch("outreach.legacy.load", return_value=pending), \
                patch("outreach.legacy.save"), \
                patch("outreach.send_guard.ColdGuard.from_settings", return_value=ColdGuard()), \
                patch("outreach.verify.verify_many", side_effect=AssertionError("inline verification")), \
                patch("outreach.cli.Mailer") as mailer:
            self.assertEqual(cmd_legacy(args), 0)
            instance = mailer.return_value.__enter__.return_value
            self.assertEqual(instance.build_message.call_args.args[0], "j.smith@uni.org")
            instance.deliver.assert_called_once()
        self.assertEqual(len(self.queue()), 1)

    def test_legacy_send_never_discovers_on_empty_workbook(self):
        from outreach.cli import build_parser, cmd_legacy
        from outreach.config import settings
        args = build_parser().parse_args(["legacy", "--send"])
        with patch.object(settings, "output_dir", self.out), \
                patch("outreach.legacy.load", return_value=[]), \
                patch("outreach.discover.Discoverer") as discovery:
            self.assertEqual(cmd_legacy(args), 0)
            discovery.assert_not_called()


if __name__ == "__main__":
    unittest.main()
