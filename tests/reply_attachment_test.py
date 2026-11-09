"""Per-item "attachments" on reply_queue.json items: no SMTP connection is opened."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import shutil
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _isolate  # noqa: F401,E402  (must precede outreach imports)

from outreach.config import settings
from outreach.mailer import Mailer

BODY = "Dear Professor Lopes,\n\nPlease find attached my transcript of records."


class ReplyAttachmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = ROOT / "build" / "reply-attachment-test"
        cls.scratch.mkdir(parents=True, exist_ok=True)
        cls.cv = cls.scratch / "cv.pdf"
        cls.cv.write_bytes(b"%PDF-1.4 global cv")
        cls.transcript = cls.scratch / "Transcript.pdf"
        cls.transcript.write_bytes(b"%PDF-1.4 transcript")
        cls.s = replace(settings, attachments=[str(cls.cv)], smtp_from="me@example.org",
                        smtp_from_name="Me", reply_to="")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.scratch)

    def build(self, body=BODY, **kw):
        return Mailer(self.s, dry_run=True).build_reply(
            "isabel@example.pt", "Isabel Lopes", "Re: summer student", body,
            "<prof@lip.pt>", "<first@iitd.ac.in>", **kw)

    @staticmethod
    def names(msg):
        return [p.get_filename() for p in msg.iter_attachments()]

    def test_no_item_list_uses_global_attachments(self):
        self.assertEqual(self.names(self.build()), ["cv.pdf"])

    def test_item_list_replaces_global_attachments(self):
        msg = self.build(attachments=[str(self.transcript)])
        self.assertEqual(self.names(msg), ["Transcript.pdf"])
        self.assertEqual(msg["In-Reply-To"], "<prof@lip.pt>")
        self.assertEqual(msg["References"], "<first@iitd.ac.in> <prof@lip.pt>")

    def test_item_list_attached_even_without_mention(self):
        msg = self.build("Dear Professor Lopes,\n\nThank you.",
                         attachments=[str(self.transcript)])
        self.assertEqual(self.names(msg), ["Transcript.pdf"])

    def test_single_string_is_accepted(self):
        self.assertEqual(self.names(self.build(attachments=str(self.transcript))),
                         ["Transcript.pdf"])

    def test_missing_item_file_is_an_error(self):
        with self.assertRaises(FileNotFoundError):
            self.build(attachments=[str(self.scratch / "missing.pdf")])

    def test_empty_list_with_promise_is_an_error(self):
        with self.assertRaises(ValueError):
            self.build(attachments=[])
        msg = self.build("Dear Professor Lopes,\n\nThank you.", attachments=[])
        self.assertEqual(self.names(msg), [])


if __name__ == "__main__":
    unittest.main()
