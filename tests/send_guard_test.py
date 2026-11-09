"""Cold-send gate: bounce blocklist, no-cold-email list, student/shared mailboxes,
first-initial + surname check, suspect status, domain cap, daily-cap clamp,
probability floor, and no CV attachment on cold first emails. No SMTP traffic."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
import csv
import json
import shutil
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _isolate  # noqa: F401,E402  (must precede outreach imports)

from openpyxl import Workbook

from outreach import send_guard as G
from outreach.config import COLD_DAILY_HARD_CAP, settings
from outreach.mailer import Mailer
from outreach.resume_parser import ResumeProfile

ROOT = Path(__file__).resolve().parents[1]
WORK = Path(__file__).resolve().parent / "_send_guard_work"
LOG_FIELDS = ["time", "mode", "status", "email", "name", "sheet", "row", "detail"]


def write_log(path, records):
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=LOG_FIELDS)
        w.writeheader()
        for r in records:
            w.writerow({k: r.get(k, "") for k in LOG_FIELDS})


def row(i, email, name="", **kw):
    base = {"sheet": "Targets", "row": i, "email": email, "name": name, "send_status": "",
            "probability": 80, "email_status": "ok", "subject": "x / y (IIT Delhi)",
            "body": "Dear Prof. X,\n\nHello.\n\nBest,\nA"}
    base.update(kw)
    return base


class GuardTestBase(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(WORK, ignore_errors=True)
        WORK.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(WORK, ignore_errors=True)


class BlocklistTests(GuardTestBase):
    def build_sources(self):
        wb = Workbook()
        ws = wb.active
        ws.title = "Targets"
        ws.append(["Professor Name", "Email Address", "Reply Status", "Send Status"])
        ws.append(["A One", "a.one@uni-a.de", "bounced 2026-10-16 15:16", "sent"])
        ws.append(["B Two", "b.two@uni-b.de", "replied 2026-10-16 12:00", "sent"])
        ws.append(["C Three", "C.Three@Uni-C.de", "Bounced", "sent"])
        wb.save(WORK / "professors.xlsx")
        write_log(WORK / "send_log.csv", [
            {"time": "2026-11-01 10:00:00", "mode": "resend", "status": "bounced",
             "email": "d.four@uni-d.de"},
            {"time": "2026-11-01 10:00:00", "mode": "resend", "status": "sent",
             "email": "e.five@uni-e.de", "detail": "550 bounce: user unknown"},
            {"time": "2026-11-01 10:00:00", "mode": "live", "status": "sent",
             "email": "f.six@uni-f.de"},
        ])
        (WORK / "FAILURES.json").write_text(json.dumps({"failures": [
            {"email": "g.seven@uni-g.de", "failure": "bounce", "root_cause": "MAILBOX_DOES_NOT_EXIST"},
            {"email": "h.eight@uni-h.de", "failure": "bounce", "root_cause": "DELAYED_NOT_FAILED"},
            {"email": "i.nine@uni-i.de", "failure": "wrong_person",
             "root_cause": "WRONG_PERSON_NAME_COLLISION"},
        ]}), encoding="utf-8")

    def test_blocklist_merges_all_sources(self):
        self.build_sources()
        blocked = G.load_blocklist(WORK)
        for addr in ("a.one@uni-a.de", "c.three@uni-c.de", "d.four@uni-d.de",
                     "e.five@uni-e.de", "g.seven@uni-g.de"):
            self.assertEqual(blocked.get(addr), G.BOUNCED, addr)
        self.assertEqual(blocked.get("i.nine@uni-i.de"), G.WRONG_PERSON)
        for addr in ("b.two@uni-b.de", "f.six@uni-f.de", "h.eight@uni-h.de"):
            self.assertNotIn(addr, blocked)

    def test_missing_files_are_fine(self):
        self.assertEqual(G.load_blocklist(WORK / "nope"), {})

    def test_send_batch_skips_bounced(self):
        self.build_sources()
        s = replace(settings, output_dir=WORK, send_min_probability=0, max_per_domain_week=3)
        guard = G.ColdGuard.from_settings(s, WORK / "professors.xlsx")
        rows = [row(2, "A.One@uni-a.de", "Anna One"), row(3, "j.ten@uni-j.de", "Jo Ten")]
        updates = Mailer(s, dry_run=True).send_batch(rows, guard=guard)
        by = {u["row"]: u["status"] for u in updates}
        self.assertEqual(by[2], "skipped: bounced before")
        self.assertEqual(by[3], "dry-run")


class MailboxAndNameTests(unittest.TestCase):
    def test_student_and_shared_mailboxes(self):
        for addr in ("q.qiao@postgrad.manchester.ac.uk", "guiye.lin@studenti.unipd.it",
                     "knajafi@g.harvard.edu", "fanjin.wang.20@ucl.ac.uk",
                     "lehre-hillerbrand@itas.kit.edu", "Roma3@pec.infn.it",
                     "m.rossi@pec.unipd.it", "info@uni-x.de", "abc21@imperial.ac.uk"):
            self.assertTrue(G.mailbox_problem(addr), addr)
        for addr in ("j.fottner@tum.de", "lhernquist@cfa.harvard.edu",
                     "s.kalliadasis@imperial.ac.uk", "mc2281@cam.ac.uk",
                     "peter.smith@physics.ox.ac.uk"):
            self.assertEqual(G.mailbox_problem(addr), "", addr)

    def test_first_initial_plus_surname(self):
        ok = [("Johannes Fottner", "j.fottner@tum.de"),
              ("Stefan Wagner", "stefan.wagner@tum.de"),
              ("Lars Hernquist", "lhernquist@cfa.harvard.edu"),
              ("Prof. Dr. Anna Schmidt", "anna.schmidt@kit.edu"),
              ("Isabel Lopes", "lopes.i@lip.pt"),
              ("Lorenzo Del Moro", "l.delmoro@uni.it"),
              ("Matthias Ludwig Schott", "mschott@uni-bonn.de"),
              ("Dennis Noll", "nollde@stanford.edu")]
        for name, addr in ok:
            self.assertEqual(G.name_email_problem(name, addr), "", (name, addr))
        bad = [("Matthias Althoff", "althoff@tum.de"),          # surname only
               ("Filippo Vicentini", "francesco.vicentini@epfl.ch"),
               ("Jens Eisert", "peter.eisert@hhi.fraunhofer.de"),
               ("Rob Ashmore", "emily.ashmore@brighton-hove.gov.uk"),
               ("Yaoyi Chen", "xin.chen@fu-berlin.de"),
               ("Cenk Tuysuz", "cengiz.tuysuz@usak.edu.tr"),
               ("Raquel Gomez-Ambrosio", "roma3@pec.infn.it")]
        for name, addr in bad:
            self.assertTrue(G.name_email_problem(name, addr), (name, addr))

    def test_guard_reasons(self):
        guard = G.ColdGuard()
        self.assertEqual(guard.check(row(2, "althoff@tum.de", "Matthias Althoff")),
                         "skipped: name/email mismatch (surname-only address (no first initial))")
        self.assertEqual(guard.check(row(2, "j.doe@uni.de", "Jane Doe", email_status="suspect")),
                         "skipped: suspect address")
        self.assertEqual(guard.check(row(2, "j.doe@uni.de", "Jane Doe", email_status="suspect"),
                                     allow_unverified=True), "")
        self.assertTrue(guard.check(row(2, "g.lin@studenti.unipd.it", "Guiye Lin"))
                        .startswith("skipped: student"))
        self.assertEqual(guard.check(row(2, "j.doe@uni.de", "Jane Doe")), "")
        self.assertFalse(G.ColdGuard(strict_names=False).check(row(2, "althoff@tum.de", "Matthias Althoff")))
        flagged = row(2, "j.doe@uni.de", "Jane Doe", review_flags="REJECTED DRAFT: capacity")
        self.assertEqual(guard.check(flagged), "skipped: draft failed validation")


class NoColdEmailTests(unittest.TestCase):
    def test_real_list_loads_and_blocks(self):
        data = G.load_no_cold(ROOT / "output" / "no_cold_email.json")
        if not data:
            self.skipTest("output/no_cold_email.json not present")
        guard = G.ColdGuard(no_cold=data)
        for name, addr in (("Johannes Fottner", "j.fottner@tum.de"),
                           ("Nils Thuerey", "nils.thuerey@tum.de"),
                           ("Anyone Else", "a.else@iter.org"),
                           ("Other Prof", "o.prof@epfl.ch"),
                           ("Other Prof", "o.prof@physik.uni-bonn.de")):
            self.assertTrue(guard.check(row(2, addr, name)).startswith("skipped: no cold email"),
                            addr)
        self.assertEqual(guard.check(row(2, "j.bloggs@tum.de", "Joe Bloggs")), "")

    def test_person_matched_by_name_at_new_address(self):
        guard = G.ColdGuard(no_cold={"people": [{"name": "Stefan Wagner", "reason": "no interns"}]})
        self.assertIn("no interns", guard.check(row(2, "s.wagner@cit.tum.de", "Prof. Stefan Wagner")))


class DomainCapTests(GuardTestBase):
    def test_org_domain(self):
        self.assertEqual(G.org_domain("a@physics.ox.ac.uk"), "ox.ac.uk")
        self.assertEqual(G.org_domain("a@cfa.harvard.edu"), "harvard.edu")
        self.assertEqual(G.org_domain("a@tum.de"), "tum.de")
        self.assertEqual(G.org_domain("a@cit.tum.de"), "tum.de")

    def test_counts_only_recent_cold_sends(self):
        now = datetime(2026, 11, 9, 12, 0)
        recent = (now - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S")
        old = (now - timedelta(days=9)).strftime("%Y-%m-%d %H:%M:%S")
        write_log(WORK / "send_log.csv", [
            {"time": recent, "mode": "live", "status": "sent", "email": "a.b@imperial.ac.uk"},
            {"time": recent, "mode": "resend", "status": "sent", "email": "c.d@ic.imperial.ac.uk"},
            {"time": recent, "mode": "legacy", "status": "sent", "email": "e.f@imperial.ac.uk"},
            {"time": recent, "mode": "dry-run", "status": "dry-run", "email": "g.h@imperial.ac.uk"},
            {"time": recent, "mode": "live", "status": "skipped: x", "email": "i.j@imperial.ac.uk"},
            {"time": old, "mode": "live", "status": "sent", "email": "k.l@imperial.ac.uk"},
            {"time": old, "mode": "live", "status": "sent", "email": "m.n@ethz.ch"},
        ])
        counts = G.domain_counts(WORK / "send_log.csv", now=now)
        self.assertEqual(counts["imperial.ac.uk"], 3)
        self.assertEqual(counts["ethz.ch"], 0)

    def test_send_batch_enforces_cap_within_and_across_runs(self):
        s = replace(settings, send_min_probability=0, send_delay_min=0, send_delay_max=0)
        guard = G.ColdGuard(domain_counts={"ethz.ch": 1}, max_per_domain=3)
        names = ["Anna Weber", "Bruno Keller", "Carla Meier", "Dario Frei"]
        rows = [row(i, f"{n.split()[0][0].lower()}.{n.split()[1].lower()}@phys.ethz.ch", n)
                for i, n in enumerate(names, 2)]
        rows += [row(9, "a.bauer@uzh.ch", "Alma Bauer")]
        updates = Mailer(s, dry_run=True).send_batch(rows, guard=guard)
        statuses = [u["status"] for u in updates]
        self.assertEqual(statuses.count("dry-run"), 3)  # 2 for ethz + 1 for uzh
        capped = [u for u in updates if u["status"].startswith("skipped: domain cap")]
        self.assertEqual(len(capped), 2)
        self.assertIn("ethz.ch", capped[0]["status"])


class CapAndProbabilityTests(unittest.TestCase):
    def test_cold_daily_cap_is_clamped_at_40(self):
        self.assertEqual(COLD_DAILY_HARD_CAP, 40)
        s = replace(settings, daily_send_cap=150, send_min_probability=0,
                    send_delay_min=0, send_delay_max=0)
        mailer = Mailer(s, dry_run=False)

        def send_one(r):
            msg = EmailMessage()
            msg["Message-ID"] = f"<{r['row']}@x>"
            mailer.sent_count += 1
            return {"status": "sent", "message": msg}

        mailer.send_one = send_one
        rows = [row(i, f"a{i}.b{i}@u{i}.edu", f"Aa{i} B{i}") for i in range(60)]
        updates = mailer.send_batch(rows)
        self.assertEqual(sum(u["status"] == "sent" for u in updates), 40)

    def test_default_min_probability_is_40(self):
        from outreach.config import Settings
        self.assertEqual(Settings.__dataclass_fields__["cold_min_probability"].default, 40)
        s = replace(settings, send_min_probability=40)
        rows = [row(2, "a.b@u.edu", "Al B", probability=39), row(3, "c.d@u.edu", "Cy D", probability=40)]
        updates = Mailer(s, dry_run=True).send_batch(rows)
        self.assertEqual([u["row"] for u in updates], [3])


class ColdAttachmentTests(GuardTestBase):
    def setUp(self):
        super().setUp()
        self.cv = WORK / "cv.pdf"
        self.cv.write_bytes(b"%PDF-1.4 cv")
        self.s = replace(settings, attachments=[str(self.cv)], smtp_from="me@example.org",
                         smtp_from_name="Me", reply_to="", cv_url="https://avinashistoocool.github.io/")
        self.profile = ResumeProfile(name="Avinash", email="me@example.org",
                                     institution="IIT Delhi", degree="B.Tech")

    @staticmethod
    def names(msg):
        return [p.get_filename() for p in msg.iter_attachments()]

    def test_cold_email_has_no_attachment_and_links_cv(self):
        m = Mailer(replace(self.s, cold_attach_cv=False), self.profile, dry_run=True)
        msg = m.send_one(row(2, "a.b@uni.de", "Al B"))["message"]
        self.assertEqual(self.names(msg), [])
        self.assertIn("https://avinashistoocool.github.io/", msg.get_body(("plain",)).get_content())

    def test_link_not_duplicated_when_body_has_it(self):
        m = Mailer(replace(self.s, cold_attach_cv=False), self.profile, dry_run=True)
        body = "Dear Prof. B,\n\nMy CV is linked here: https://avinashistoocool.github.io/\n\nA"
        msg = m.build_message("a.b@uni.de", "Al B", "s", body)
        self.assertEqual(msg.get_body(("plain",)).get_content().count("avinashistoocool.github.io"), 1)

    def test_opt_in_attaches_cv(self):
        m = Mailer(replace(self.s, cold_attach_cv=True), self.profile, dry_run=True)
        self.assertEqual(self.names(m.send_one(row(2, "a.b@uni.de"))["message"]), ["cv.pdf"])

    def test_explicit_row_attachment_still_works(self):
        m = Mailer(replace(self.s, cold_attach_cv=False), self.profile, dry_run=True)
        msg = m.build_message("a.b@uni.de", "Al B", "s", "Dear X,", attachments=[str(self.cv)])
        self.assertEqual(self.names(msg), ["cv.pdf"])

    def test_reply_still_attaches_when_body_says_so(self):
        m = Mailer(replace(self.s, cold_attach_cv=False), self.profile, dry_run=True)
        msg = m.build_reply("a.b@uni.de", "Al B", "Re: x",
                            "Dear Prof. B,\n\nMy CV is attached.\n\nA")
        self.assertEqual(self.names(msg), ["cv.pdf"])
        msg = m.build_reply("a.b@uni.de", "Al B", "Re: x", "Dear Prof. B,\n\nThanks.\n\nA")
        self.assertEqual(self.names(msg), [])


class IsolationTests(unittest.TestCase):
    def test_tests_never_see_real_credentials(self):
        _isolate.assert_isolated(settings)
        self.assertNotIn("iitd", (settings.smtp_host + settings.imap_host).lower())


if __name__ == "__main__":
    unittest.main()
