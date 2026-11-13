"""Internship programme reminders: milestones, idempotency, missed days, calendar."""
import json
import shutil
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _isolate  # noqa: F401,E402  (must precede outreach imports)

from outreach import program_reminders as pr

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sample_programs.json"
WORK = Path(__file__).resolve().parent / "_program_reminders_work"


def programs():
    return pr.load_programs(FIXTURE)


class FakeEvents:
    def __init__(self, store):
        self.store = store

    def _x(self, value):
        class R:
            def execute(_self):
                return value
        return R()

    def insert(self, calendarId, body):
        eid = f"ev{len(self.store) + 1}"
        self.store[eid] = body
        return self._x({"id": eid})

    def update(self, calendarId, eventId, body):
        self.store[eventId] = body
        return self._x({"id": eventId})

    def list(self, calendarId, privateExtendedProperty, **kw):
        key = privateExtendedProperty.split("=", 1)[1]
        items = [{"id": k} for k, b in self.store.items()
                 if b["extendedProperties"]["private"]["agnostosKey"] == key]
        return self._x({"items": items[:1]})

    def delete(self, calendarId, eventId):
        self.store.pop(eventId, None)
        return self._x({})


class FakeCal:
    def __init__(self):
        self.store = {}

    def events(self):
        return FakeEvents(self.store)


class Base(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(WORK, ignore_errors=True)
        WORK.mkdir()
        self.mails = []
        self.cv_patch = patch.object(pr.settings, "program_cv_dir", str(WORK / "nocv"))
        self.cv_patch.start()
        self.to_patch = patch.object(pr.settings, "reminder_recipients",
                                     ["owner@example.org", "owner@uni.example.edu"])
        self.to_patch.start()
        self.tz_patch = patch.object(pr.settings, "reminder_tz", "Asia/Kolkata")
        self.tz_patch.start()
        self.dir_patch = patch.object(pr, "programs_dir", lambda: WORK)
        self.dir_patch.start()

    def tearDown(self):
        self.cv_patch.stop()
        self.to_patch.stop()
        self.tz_patch.stop()
        self.dir_patch.stop()
        shutil.rmtree(WORK, ignore_errors=True)

    def send(self, subject, body):
        self.mails.append((subject, body))

    def run_on(self, day, progs=None, **kw):
        before = len(self.mails)
        res = pr.run(progs or programs(), date.fromisoformat(day), WORK,
                     send=self.send, log=lambda s: None, **kw)
        return [s for s, _ in self.mails[before:]], res

    def state(self):
        return json.loads((WORK / "reminders_sent.json").read_text(encoding="utf-8"))["sent"]


class MilestoneTest(Base):
    def test_schedule(self):
        cern = programs()[0]
        got = {m.key: m.day.isoformat() for m in pr.milestones(cern)}
        self.assertEqual(got, {
            "opens": "2026-12-01", "referees-21": "2027-01-10",
            "deadline-30": "2027-01-01", "deadline-14": "2027-01-17",
            "deadline-7": "2027-01-24", "deadline-3": "2027-01-28",
            "deadline-1": "2027-01-30"})

    def test_null_deadline_and_no_referees(self):
        epfl, iter_ = programs()[1], programs()[2]
        self.assertEqual({m.key for m in pr.milestones(epfl)},
                         {f"deadline-{n}" for n in pr.DEADLINE_OFFSETS})
        self.assertEqual(pr.milestones(iter_), [])
        self.assertEqual(pr.due_reminders([iter_], date(2027, 1, 1), {}), [])
        self.assertNotIn("iter-internship|deadline", pr.calendar_bodies(programs(), date(2026, 11, 1)))

    def test_subject_format(self):
        cern = programs()[0]
        d = pr.Due(cern, next(m for m in pr.milestones(cern) if m.key == "deadline-7"))
        subj, body = pr.reminder_email(d, date(2027, 1, 24))
        self.assertEqual(subj, "[Agnostos] CERN Summer Student Programme: deadline in 7 days (2027-01-31)")
        self.assertIn("[ ] Motivation letter", body)
        self.assertIn("https://careers.cern/summer", body)

    def test_cv_path_found(self):
        cvs = WORK / "cvs"
        cvs.mkdir()
        (cvs / "cern-summer-student.pdf").write_bytes(b"%PDF")
        self.assertEqual(pr.cv_path(programs()[0]), cvs / "cern-summer-student.pdf")
        self.assertIsNone(pr.cv_path(programs()[1]))


class RunTest(Base):
    def test_dry_run_sends_nothing(self):
        cal = FakeCal()
        subjects, res = self.run_on("2026-11-08", dry_run=True, calendar_svc=cal,
                                    sms=lambda t: self.fail("sms in dry run"))
        self.assertEqual(self.mails, [])
        self.assertTrue(res["emails"])
        self.assertEqual(cal.store, {})
        self.assertFalse((WORK / "reminders_sent.json").exists())
        self.assertFalse((WORK / "calendar_events.json").exists())

    def test_welcome_then_idempotent(self):
        subjects, _ = self.run_on("2026-11-08")
        self.assertEqual(len(subjects), 1)
        self.assertIn("tracker is live", subjects[0])
        body = self.mails[0][1]
        self.assertLess(body.index("EPFL"), body.index("CERN Summer"))   # sorted by deadline
        self.assertIn("ITER", body)
        again, _ = self.run_on("2026-11-08")
        self.assertEqual(again, [])
        later, _ = self.run_on("2026-11-09")   # welcome on a Sunday covers Monday's digest
        self.assertEqual(later, [])

    def test_daily_milestones_once_each(self):
        self.run_on("2026-11-08")
        self.assertEqual(self.run_on("2026-11-10")[0], [])
        self.assertEqual(self.run_on("2026-11-17")[0][-1],     # Tue, new week -> digest + 14d
                         "[Agnostos] EPFL Excellence Research Internship: deadline in 14 days (2026-12-01)")
        self.assertEqual(self.run_on("2026-11-17")[0], [])
        s = self.run_on("2026-11-24")[0]
        self.assertTrue(any("deadline in 7 days" in x for x in s))
        self.assertEqual(self.run_on("2026-11-24")[0], [])

    def test_missed_days_send_latest_only(self):
        self.run_on("2026-11-08")
        # Runner was off from Nov 9 to Nov 29: 14/7/3 day milestones all missed.
        subjects, _ = self.run_on("2026-11-29")
        epfl = [s for s in subjects if "EPFL" in s and "digest" not in s.lower()]
        self.assertEqual(epfl, ["[Agnostos] EPFL Excellence Research Internship: deadline in 2 days (2026-12-01)"])
        st = self.state()
        self.assertEqual(st["epfl-summer|deadline-3"]["how"], "sent")
        self.assertEqual(st["epfl-summer|deadline-14"]["how"], "superseded")
        nxt, _ = self.run_on("2026-11-30")
        self.assertEqual([s for s in nxt if "EPFL" in s and "digest" not in s.lower()],
                         ["[Agnostos] EPFL Excellence Research Internship: deadline tomorrow (2026-12-01)"])
        # EPFL past deadline: silent; CERN applications opened yesterday (missed day) -> once.
        self.assertEqual(self.run_on("2026-12-02")[0],
                         ["[Agnostos] CERN Summer Student Programme: applications are open (deadline 2027-01-31)"])
        self.assertEqual(self.run_on("2026-12-03")[0], [])

    def test_referee_and_deadline_merge(self):
        self.run_on("2026-11-08")
        progs = programs()
        progs[1]["referees_needed"] = 1        # EPFL: referees-21 was Nov 10
        subjects, _ = self.run_on("2026-11-24", progs)
        epfl = [s for s in subjects if "EPFL" in s]
        self.assertEqual(epfl, ["[Agnostos] EPFL Excellence Research Internship: deadline in 7 days (2026-12-01)"])
        self.assertIn("referee(s) have been asked", self.mails[-1][1])
        self.assertEqual(self.state()["epfl-summer|referees-21"]["how"], "superseded")

    def test_welcome_folds_far_milestones(self):
        # First ever run on Jan 12: CERN opens (stale), referees-21 and 30-day due.
        subjects, _ = self.run_on("2027-01-12")
        self.assertIn("tracker is live", subjects[0])
        self.assertEqual(subjects[1:], [
            "[Agnostos] CERN Summer Student Programme: ask your 2 referee(s) now "
            "(deadline in 19 days, 2027-01-31)"])
        self.assertEqual(self.state()["cern-summer-student|deadline-30"]["how"], "sent")

    def test_send_failure_not_marked(self):
        def boom(s, b):
            raise OSError("smtp down")
        with self.assertRaises(OSError):
            pr.run(programs(), date(2026, 11, 8), WORK, send=boom, log=lambda s: None)
        self.assertNotIn("welcome", json.loads(
            (WORK / "reminders_sent.json").read_text() if (WORK / "reminders_sent.json").exists()
            else '{"sent": {}}')["sent"])

    def test_sms_hook(self):
        texts = []
        self.run_on("2026-11-08")
        self.run_on("2026-11-24", sms=lambda t: texts.append(t) or True)
        self.assertEqual(len(texts), 1)
        self.assertIn("EPFL", texts[0])
        with patch.dict("os.environ", {}, clear=True):
            self.assertFalse(pr.sms_configured())
            self.assertFalse(pr.twilio_sms("x"))

    def test_recipient_guard(self):
        with self.assertRaises(ValueError):
            pr._guard(["someone@else.org"])
        self.assertEqual(pr._guard(pr.recipients()), list(pr.recipients()))
        with patch.object(pr.settings, "reminder_recipients", []):
            with self.assertRaises(RuntimeError):
                pr._guard(["owner@example.org"])

    def test_no_personal_defaults(self):
        import inspect
        src = inspect.getsource(pr)
        for personal in ("gmail.com", "iitd", "+91", "C:\\Users"):
            self.assertNotIn(personal, src)
        with patch.object(pr.settings, "reminder_sms_to", ""), \
                patch.dict("os.environ", {"TWILIO_ACCOUNT_SID": "a", "TWILIO_AUTH_TOKEN": "b",
                                          "TWILIO_FROM": "c"}):
            self.assertFalse(pr.sms_configured())


class CalendarTest(Base):
    def test_calendar_idempotent_and_updates(self):
        cal = FakeCal()
        _, res = self.run_on("2026-11-08", calendar_svc=cal)
        # CERN: deadline + 7 milestones; EPFL: deadline + 4 (30-day mark already past); ITER: none.
        self.assertEqual(res["calendar"]["created"], 13)
        self.assertEqual(len(cal.store), 13)
        _, res = self.run_on("2026-11-09", calendar_svc=cal)
        self.assertEqual(res["calendar"]["created"], 0)
        self.assertEqual(res["calendar"]["unchanged"], 13)
        progs = programs()
        progs[0]["deadline"] = "2027-02-07"
        _, res = self.run_on("2026-11-09", progs, calendar_svc=cal)
        self.assertEqual(res["calendar"]["created"], 0)
        self.assertEqual(res["calendar"]["updated"], 8)
        self.assertEqual(len(cal.store), 13)
        dl = next(b for b in cal.store.values() if b["summary"].startswith("DEADLINE: CERN"))
        self.assertEqual(dl["start"], {"date": "2027-02-07"})
        self.assertTrue(any(o["method"] == "popup" for o in dl["reminders"]["overrides"]))
        timed = next(b for b in cal.store.values() if "Ask referees" in b["summary"])
        self.assertEqual(timed["start"]["dateTime"], "2027-01-17T09:00:00")
        self.assertEqual(timed["start"]["timeZone"], "Asia/Kolkata")

    def test_calendar_recovers_lost_store(self):
        cal = FakeCal()
        self.run_on("2026-11-08", calendar_svc=cal)
        (WORK / "calendar_events.json").unlink()
        _, res = self.run_on("2026-11-09", calendar_svc=cal)
        self.assertEqual(res["calendar"]["created"], 0)
        self.assertEqual(len(cal.store), 13)

    def test_removed_program_events_deleted(self):
        cal = FakeCal()
        self.run_on("2026-11-08", calendar_svc=cal)
        _, res = self.run_on("2026-11-09", programs()[:1], calendar_svc=cal)
        self.assertEqual(res["calendar"]["deleted"], 5)
        self.assertEqual(len(cal.store), 8)


class CliTest(Base):
    def test_cli_dry_run_missing_file(self):
        from outreach.cli import main
        self.assertEqual(main(["program-reminders", "--dry-run", "--now", "2026-11-08",
                               "--programs", str(WORK / "missing.json")]), 0)

    def test_cli_live_disabled_without_recipients(self):
        from outreach.cli import main
        src = WORK / "p.json"
        shutil.copy(FIXTURE, src)
        with patch.object(pr.settings, "reminder_recipients", []), \
                patch.object(pr, "GmailSender", side_effect=AssertionError("must not send")):
            self.assertEqual(main(["program-reminders", "--now", "2026-11-08",
                                   "--programs", str(src)]), 0)
        self.assertFalse((WORK / "reminders_sent.json").exists())

    def test_cli_dry_run_fixture(self):
        from outreach.cli import main
        src = WORK / "p.json"
        shutil.copy(FIXTURE, src)
        with patch.object(pr, "GmailSender", side_effect=AssertionError("no SMTP in dry run")):
            self.assertEqual(main(["program-reminders", "--dry-run", "--now", "2026-11-08",
                                   "--programs", str(src)]), 0)
        self.assertFalse((WORK / "reminders_sent.json").exists())


if __name__ == "__main__":
    unittest.main(verbosity=1)
