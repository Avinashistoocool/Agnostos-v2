"""Pure legacy live-selection tests: no SMTP or CLI live action is executed."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import shutil
import sys
import unittest
from unittest.mock import patch
import os

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _isolate  # noqa: F401,E402  (must precede outreach imports)

from outreach.legacy_guard import plan_legacy_live


def candidate(name: str, *, status: str = "ok", country: str = "Germany") -> dict:
    return {"Name": name, "Email": name.lower() + "@university.de",
            "Email Status": status, "Country": country,
            "Institution": "Physics Institute",
            "Known for": "particle physics", "Recent work": "collider detectors",
            "Send Status": "", "Sent At": "", "Draft": "Draft", "Approved": "yes"}


class LegacyGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = ROOT / "build" / "legacy-guard-test"
        cls.scratch.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.scratch)

    def test_verified_focus_weekday_and_daily_cap(self):
        now = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)  # Monday 13:00 Germany
        log = self.scratch / "send_log.csv"
        log.write_text("time,mode,status,email\n"
                       "2026-11-02 08:00:00,legacy,sent,old@university.de\n",
                       encoding="utf-8")
        rows = [candidate("Good"), candidate("Extra"),
                candidate("Invalid", status="invalid"),
                {**candidate("OffTopic"), "Known for": "clinical surgery",
                 "Recent work": "tumour research", "Institution": "Medical Institute"},
                candidate("Unknown", country="")]
        rows[-1]["Email"] = "unknown@university.edu"
        allowed, held, window, room = plan_legacy_live(
            rows, log, daily_cap=2, limit=10, window_spec="9-17", now=now)
        self.assertEqual([r["Name"] for r in allowed], ["Good"])
        self.assertEqual(room, 1)
        self.assertEqual(len(held), 4)
        self.assertEqual(window.spec, "9-17")
        self.assertTrue(any("not verified" in reason for _, reason in held))
        self.assertTrue(any("focus" in reason for _, reason in held))
        self.assertTrue(any("timezone" in reason for _, reason in held))

    def test_weekend_and_disabled_window_never_pass(self):
        saturday = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)
        rows, held, _, room = plan_legacy_live(
            [candidate("Weekend")], self.scratch / "missing.csv",
            daily_cap=25, limit=10, window_spec="9-17", now=saturday)
        self.assertEqual(rows, [])
        self.assertEqual(room, 25)
        self.assertIn("weekday", held[0][1])
        for unsafe in ("", "off", "any", "none"):
            with self.subTest(unsafe=unsafe), self.assertRaises(ValueError):
                plan_legacy_live([candidate("A")], self.scratch / "missing.csv",
                                 daily_cap=25, limit=10, window_spec=unsafe)

    def test_second_mailbox_resends_share_legacy_daily_cap(self):
        log = self.scratch / "shared_send_log.csv"
        log.write_text("time,mode,status,email\n"
                       "2026-11-02 08:00:00,resend,sent,one@university.de\n"
                       "2026-11-02 09:00:00,legacy,sent,two@university.de\n",
                       encoding="utf-8")
        allowed, held, _, room = plan_legacy_live(
            [candidate("Good")], log, daily_cap=2, limit=10, window_spec="9-17",
            now=datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc))
        self.assertEqual((allowed, room), ([], 0))
        self.assertIn("daily cap", held[0][1])

    def test_operator_ceiling_ninety_counts_prior_sends(self):
        log = self.scratch / "ninety.csv"
        log.write_text("time,mode,status,email\n" +
                       "".join(f"2026-11-02 09:00:00,legacy,sent,old{i}@uni.de\n"
                               for i in range(87)), encoding="utf-8")
        with patch("outreach.legacy_guard.COLD_DAILY_HARD_CAP", 90):
            allowed, _, _, room = plan_legacy_live(
                [candidate(f"Next{i}") for i in range(10)], log,
                daily_cap=150, limit=150, window_spec="9-17",
                now=datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc))
        self.assertEqual(room, 3)
        self.assertEqual(len(allowed), 3)

    def test_ceiling_configuration_validation(self):
        from outreach.config import _cold_daily_ceiling, ConfigError
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(_cold_daily_ceiling(), 40)
        with patch.dict(os.environ, {"COLD_DAILY_HARD_CAP": "90"}):
            self.assertEqual(_cold_daily_ceiling(), 90)
        for invalid in ("0", "91", "-1", "ninety", "40.5"):
            with patch.dict(os.environ, {"COLD_DAILY_HARD_CAP": invalid}):
                with self.assertRaises(ConfigError):
                    _cold_daily_ceiling()

    def test_reply_queue_daily_cap_counts_prior_delivery(self):
        with patch.dict(os.environ, {"PYTHON_DOTENV_DISABLED": "1"}):
            from outreach.cli import reply_live_room
        queue = [{"sent_at": "2026-11-02 09:00:00"},
                 {"sent_at": "2026-11-02 10:00:00"},
                 {"sent_at": ""}]
        self.assertEqual(reply_live_room(queue, 3, "2026-11-02"), 1)
        self.assertEqual(reply_live_room(queue, 2, "2026-11-02"), 0)
        self.assertEqual(reply_live_room(queue, 100, "2026-11-02"), 38)

    def test_duplicate_approved_recipient_only_selected_once(self):
        now = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
        first = candidate("Duplicate")
        allowed, held, _, room = plan_legacy_live(
            [first, dict(first)], self.scratch / "missing.csv",
            daily_cap=25, limit=10, window_spec="9-17", now=now)
        self.assertEqual(room, 25)
        self.assertEqual(len(allowed), 1)
        self.assertEqual(len(held), 1)
        self.assertIn("duplicate", held[0][1])


if __name__ == "__main__":
    unittest.main()
