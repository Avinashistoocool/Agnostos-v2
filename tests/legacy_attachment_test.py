"""Per-row "Attachment" support in legacy.xlsx: no SMTP connection is opened."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import shutil
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from outreach import legacy as L
from outreach.config import settings
from outreach.mailer import Mailer


class LegacyAttachmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = ROOT / "build" / "legacy-attachment-test"
        cls.scratch.mkdir(parents=True, exist_ok=True)
        cls.cv = cls.scratch / "cv.pdf"
        cls.cv.write_bytes(b"%PDF-1.4 global cv")
        cls.portfolio = cls.scratch / "portfolio.pdf"
        cls.portfolio.write_bytes(b"%PDF-1.4 portfolio")
        cls.cern_cv = cls.scratch / "cern cv.pdf"
        cls.cern_cv.write_bytes(b"%PDF-1.4 cern cv")
        cls.s = replace(settings, attachments=[str(cls.cv)], smtp_from="me@example.org",
                        smtp_from_name="Me", reply_to="")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.scratch)

    def names(self, msg):
        return [p.get_filename() for p in msg.iter_attachments()]

    def test_row_attachments_parsing(self):
        self.assertIsNone(L.row_attachments({}))
        self.assertIsNone(L.row_attachments({"Attachment": "  "}))
        self.assertEqual(L.row_attachments({"Attachment": "none"}), [])
        self.assertEqual(L.row_attachments({"Attachment": ' a.pdf ; "b c.pdf";'}),
                         ["a.pdf", "b c.pdf"])
        self.assertIn("Attachment", L.COLUMNS)

    def test_blank_cell_keeps_global_attachments(self):
        m = Mailer(self.s, dry_run=True)
        msg = m.build_message("x@cern.ch", "X", "Hi", "Dear Dr. X,",
                              attachments=L.row_attachments({"Attachment": ""}))
        self.assertEqual(self.names(msg), ["cv.pdf"])

    def test_row_list_replaces_global_attachments(self):
        m = Mailer(self.s, dry_run=True)
        row = {"Attachment": f"{self.portfolio}; {self.cern_cv}"}
        msg = m.build_message("x@cern.ch", "X", "Hi", "Dear Dr. X,",
                              attachments=L.row_attachments(row))
        self.assertEqual(self.names(msg), ["portfolio.pdf", "cern cv.pdf"])

    def test_none_sends_without_attachment(self):
        m = Mailer(self.s, dry_run=True)
        msg = m.build_message("x@cern.ch", "X", "Hi", "Dear Dr. X,",
                              attachments=L.row_attachments({"Attachment": "none"}))
        self.assertEqual(self.names(msg), [])

    def test_missing_row_file_is_an_error(self):
        m = Mailer(self.s, dry_run=True)
        with self.assertRaises(FileNotFoundError):
            m.build_message("x@cern.ch", "X", "Hi", "Dear Dr. X,",
                            attachments=[str(self.scratch / "missing.pdf")])

    def test_workbook_round_trip_keeps_attachment(self):
        path = self.scratch / "legacy.xlsx"
        L.save(path, [{"Name": "A B", "Email": "a@cern.ch", "Attachment": str(self.portfolio)}])
        rows = L.load(path)
        self.assertEqual(L.row_attachments(rows[0]), [str(self.portfolio)])


if __name__ == "__main__":
    unittest.main()
