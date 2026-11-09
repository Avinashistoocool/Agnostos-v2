"""`coordinators`: dry run by default, approval filter, per-row CV attachment."""
import shutil
import sys
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from openpyxl import Workbook, load_workbook

from outreach import coordinators as co
from outreach.cli import main
from outreach.config import settings
from outreach.mailer import Mailer
from outreach.schedule import SendWindow

WORK = Path(__file__).resolve().parent / "_coordinators_work"
BODY = "Dear team,\n\nI have a short question about eligibility. My CV is attached.\n\nBest regards,\nA"


class CoordinatorsTest(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(WORK, ignore_errors=True)
        WORK.mkdir(parents=True)
        self.cv_a = WORK / "CV_a.pdf"
        self.cv_b = WORK / "CV_b_nophoto.pdf"
        self.default_cv = WORK / "CV_default.pdf"
        for p in (self.cv_a, self.cv_b, self.default_cv):
            p.write_bytes(b"%PDF-1.4 " + p.name.encode())
        self.xlsx = WORK / "coordinator_outreach.xlsx"
        wb = Workbook()
        ws = wb.active
        ws.title = co.SHEET
        ws.append(co.COLUMNS)
        rows = [
            ("a", "a@example.org", self.cv_a, "yes", "", BODY, "Germany"),
            ("b", "b@example.org", self.cv_b, "Yes", "", BODY, "Japan"),
            ("c", "c@example.org", self.cv_a, "", "", BODY, "Germany"),
            ("d", "d@example.org", self.cv_a, "no", "", BODY, "Germany"),
            ("e", "e@example.org", self.cv_a, "yes", "2026-11-01 10:00", BODY, "Germany"),
            ("f", "f@example.org", self.cv_a, "yes", "",
             "Dear team,\n\nI can cover my own travel and living costs.\n\nA", "Germany"),
        ]
        for rid, email, cv, ok, sent, body, country in rows:
            ws.append([rid, f"Prog {rid}", "", "Office", email, "https://example.org",
                       f"Question {rid}", body, str(cv), ok, sent, "", country, ""])
        wb.save(self.xlsx)
        self.s = replace(settings, smtp_from="me@example.edu", smtp_from_name="Me",
                         reply_to="", attachments=[str(self.default_cv)], can_self_fund="no",
                         send_delay_min=0, send_delay_max=0, output_dir=WORK)
        # Monday 10:00 UTC: 11:00 Berlin (open), 19:00 Tokyo (closed).
        self.now = datetime(2026, 11, 9, 10, 0, tzinfo=timezone.utc)

    def tearDown(self):
        shutil.rmtree(WORK, ignore_errors=True)

    def test_approval_filter(self):
        ids = [r["id"] for r in co.select(co.load_rows(self.xlsx))]
        self.assertEqual(ids, ["a", "b", "f"])

    def test_attachment_is_the_rows_cv_only(self):
        mailer = Mailer(self.s, dry_run=True)
        row = co.load_rows(self.xlsx)[1]
        msg = co.build(mailer, row)
        self.assertEqual([p.get_filename() for p in msg.iter_attachments()], ["CV_b_nophoto.pdf"])
        self.assertEqual(mailer.s.attachments, [str(self.default_cv)])
        self.assertEqual(msg["To"], "b@example.org")
        self.assertEqual(msg["Subject"], "Question b")

    def test_missing_attachment_is_skipped(self):
        self.cv_a.unlink()
        res = co.run(self.xlsx, send=True, s=self.s, now=self.now, out=lambda *_: None)
        self.assertEqual({r["id"]: r["status"] for r in res}["a"], "skipped: missing attachment")

    def test_dry_run_sends_nothing_and_writes_nothing(self):
        before = self.xlsx.read_bytes()
        with patch.object(Mailer, "_deliver", side_effect=AssertionError("SMTP in dry run")), \
                patch.object(Mailer, "connect", side_effect=AssertionError("connect in dry run")):
            res = co.run(self.xlsx, send=True, live=False, s=self.s, now=self.now,
                         window=SendWindow("9-17"), out=lambda *_: None)
        status = {r["id"]: r["status"] for r in res}
        self.assertEqual(status, {"a": "dry-run", "b": "dry-run", "f": "skipped: self-funding offer"})
        self.assertEqual(self.xlsx.read_bytes(), before)

    def test_cli_defaults_to_preview(self):
        with patch.object(Mailer, "_deliver", side_effect=AssertionError("SMTP")), \
                patch.object(Mailer, "connect", side_effect=AssertionError("connect")):
            self.assertEqual(main(["coordinators", "--xlsx", str(self.xlsx)]), 0)
            self.assertEqual(main(["coordinators", "--send", "--xlsx", str(self.xlsx)]), 0)

    def test_live_send_respects_confirmation_window_and_records(self):
        delivered = []
        with patch.object(Mailer, "_deliver", lambda _self, m: delivered.append(m)), \
                patch.object(Mailer, "connect", lambda _self: None), \
                patch.object(Mailer, "_archive", lambda _self, m: None):
            res = co.run(self.xlsx, send=True, live=True, s=self.s, now=self.now,
                         ask=lambda _p: "n", out=lambda *_: None)
            self.assertEqual((res, delivered), ([], []))
            res = co.run(self.xlsx, send=True, live=True, s=self.s, now=self.now,
                         window=SendWindow("9-17"), ask=lambda _p: "y", out=lambda *_: None)
        status = {r["id"]: r["status"] for r in res}
        self.assertEqual(status, {"a": "sent", "b": "outside window",
                                  "f": "skipped: self-funding offer"})
        self.assertEqual([m["To"] for m in delivered], ["a@example.org"])
        self.assertEqual([p.get_filename() for p in delivered[0].iter_attachments()], ["CV_a.pdf"])
        ws = load_workbook(self.xlsx)[co.SHEET]
        header = [c.value for c in ws[1]]
        row_a = [c.value for c in ws[2]]
        self.assertTrue(row_a[header.index("sent_at")])
        self.assertEqual(row_a[header.index("message_id")], delivered[0]["Message-ID"])
        again = co.select(co.load_rows(self.xlsx))
        self.assertNotIn("a", [r["id"] for r in again])


if __name__ == "__main__":
    unittest.main(verbosity=1)
