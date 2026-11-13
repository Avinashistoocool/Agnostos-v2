"""First-email drafting rules: prompt content, validation, number allow-list,
self-funding guard gaps, and the one-redraft-then-flag loop. No API calls."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import json
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _isolate  # noqa: F401,E402  (must precede outreach imports)

from outreach import humanize as H
from outreach.config import settings
from outreach.llm import LLMEvaluator, SYSTEM_TEMPLATE, tidy_body
from outreach.models import Professor
from outreach.resume_parser import ResumeProfile

FACTS = Path(__file__).resolve().parents[1] / "output" / "confirmed_facts.md"

def setUpModule():
    # The repo's facts file holds the verified numbers these drafts quote; the
    # built-in fallback is deliberately empty.
    global _facts_patch
    from unittest.mock import patch
    _facts_patch = patch.object(settings, "confirmed_facts_file", str(FACTS))
    _facts_patch.start()


def tearDownModule():
    _facts_patch.stop()


GOOD_SUBJECT = "Belle II GNN background sim / 84.84% JetClass tagger (IIT Delhi)"
GOOD_BODY = """Dear Prof. Kuhr,

I'm a second-year Engineering Physics student at IIT Delhi. In Prof. Abhishek Iyer's HEP group I built GDS-ParT, a gated Particle Transformer that reached 84.84% accuracy and 0.9853 macro AUC on 1M JetClass test jets, trained on 10M jets. Code: github.com/Avinashistoocool/Gated-Dual-Stream-Particle-Transformer

Your graph attention work on selective background simulation at Belle II uses the same variable-length particle inputs I spent the summer on.

Could I spend 8-10 weeks in summer 2027 working on testing that selection network on more background channels? If not, could you point me to someone who might be a good fit?

My CV is linked here: https://avinashistoocool.github.io/

Best regards,
Avinash"""


class _Choice:
    finish_reason = "stop"

    def __init__(self, text):
        self.message = type("M", (), {"content": text})()


class _Resp:
    def __init__(self, text):
        self.choices = [_Choice(text)]
        self.usage = type("U", (), {"prompt_tokens": 10, "completion_tokens": 10,
                                    "prompt_tokens_details": None})()


class _Client:
    def __init__(self, drafts):
        self.drafts = list(drafts)
        self.requests = []
        self.chat = type("C", (), {"completions": self})()

    def create(self, **kw):
        self.requests.append(kw)
        subject, body = self.drafts.pop(0)
        return _Resp(json.dumps({"probability": 55, "justification": "fit",
                                 "subject": subject, "body": body}))


def _evaluator():
    s = replace(settings, humanize_rewrite=False, can_self_fund="no",
                confirmed_facts_file=str(FACTS), cv_url="https://avinashistoocool.github.io/",
                student_intro="I'm a second-year Engineering Physics student at IIT Delhi.",
                subject_tag="IIT Delhi")
    profile = ResumeProfile(name="Avinash Chandra Gupta", email="a@iitd.ac.in")
    return LLMEvaluator(s, profile)


class PromptTests(unittest.TestCase):
    def test_prompt_contains_new_rules_and_facts(self):
        prompt = _evaluator().system_prompt
        for must in ("84.84%", "0.9853", "10M", "2.07M", "4.5x", "NMI 0.45/0.43",
                     "100% simulated coverage", "20 declarative diagnostic rules",
                     "Could I spend 8-10 weeks in summer 2027 working on",
                     "point me to someone", "My CV is linked here: https://avinashistoocool.github.io/",
                     "110-150 words", "4 short paragraphs", "(IIT Delhi)",
                     "Abhishek Iyer", "github.com/Avinashistoocool"):
            self.assertIn(must, prompt, must)
        for gone in ("on a small subset\", \"mostly", "Never cite metrics",
                     "whether they have capacity", "may send more detail"):
            self.assertNotIn(gone, prompt, gone)
        self.assertIn("{confirmed_facts}", SYSTEM_TEMPLATE)

    def test_good_draft_passes(self):
        self.assertEqual(H.validate_first_email(GOOD_SUBJECT, GOOD_BODY), [])
        self.assertEqual(H.unverified_numbers(GOOD_BODY), [])
        self.assertFalse(H.has_hard_claims(GOOD_BODY))


class ValidationTests(unittest.TestCase):
    def check(self, body="", subject=GOOD_SUBJECT, expect=""):
        problems = H.validate_first_email(subject, body or GOOD_BODY)
        self.assertTrue(any(expect in p for p in problems), (expect, problems))

    def test_rejects_each_banned_pattern(self):
        self.check(GOOD_BODY.replace("Could I spend", "Do you have capacity to host? Could I spend"),
                   expect="capacity")
        self.check(GOOD_BODY.replace("Your graph", "I had trouble following your graph"),
                   expect="trouble following")
        self.check(GOOD_BODY.replace("trained on 10M jets", "trained on a small subset"),
                   expect="small subset")
        self.check(GOOD_BODY.replace("IIT Delhi.", "IIT Delhi with a GPA of 8.67."),
                   expect="GPA")
        self.check(GOOD_BODY.replace("Dear Prof. Kuhr,\n", "Dear Prof. Kuhr,\n\nProfessor Kuhr,\n"),
                   expect="two greeting lines")
        self.check(subject="Summer internship inquiry: Belle II", expect="inquiry")
        self.check(subject="Summer research enquiry", expect="inquiry")
        self.check(GOOD_BODY.replace("My CV", "I'd need a funded position. My CV"),
                   expect="money/funding")
        self.check(GOOD_BODY.replace("My CV", "I can join unpaid. My CV"), expect="money")
        self.check(GOOD_BODY.replace("My CV", "May I send my CV? My CV"), expect="May I send")
        self.check(GOOD_BODY.replace("84.84%", "91.2%"), expect="unverified number")

    def test_planning_cost_map_is_not_money(self):
        body = GOOD_BODY.replace("Your graph", "My A* planner used a 6-term cost map. Your graph")
        self.assertFalse(any("money" in p for p in H.validate_first_email(GOOD_SUBJECT, body)))


class NumberAllowListTests(unittest.TestCase):
    def test_confirmed_numbers_are_allowed(self):
        allowed = H.allowed_metrics(FACTS.read_text(encoding="utf-8"))
        text = ("84.84% accuracy, 0.9853 macro AUC on 1M test jets; 10M jets; 2.07M params; "
                "NMI 0.45/0.43; 4.5x muon enrichment; 100% simulated coverage; "
                "~256 KB to ~1.9 KB; 6 GB GPU.")
        self.assertEqual(H.unverified_numbers(text, allowed), [])

    def test_other_numbers_are_stripped_but_plain_integers_kept(self):
        allowed = H.allowed_metrics(FACTS.read_text(encoding="utf-8"))
        body = ("I got 84.84% accuracy. It beat the baseline by 3.2%. My GPA is 7.6.\n\n"
                "Could I spend 8-10 weeks in summer 2027 on 10 classes?")
        out, removed = H.strip_unverified_numbers(body, allowed)
        self.assertIn("84.84%", out)
        self.assertNotIn("3.2%", out)
        self.assertNotIn("7.6", out)
        self.assertIn("8-10 weeks in summer 2027", out)
        self.assertEqual(sorted(removed), ["3.2%", "7.6"])

    def test_hard_claim_no_longer_fires_on_verified_percent(self):
        self.assertFalse(H.has_hard_claims("It reached 84.84% accuracy on 1M test jets."))
        self.assertTrue(H.has_hard_claims("improved the accuracy by 12%"))
        self.assertTrue(H.has_hard_claims("It outperformed ParticleNet."))

    def test_unknown_repo_link_replaced_with_profile(self):
        allowed = H.allowed_links(FACTS.read_text(encoding="utf-8"))
        text = ("Code: github.com/Avinashistoocool/Colour-Object-Tracking. Also "
                "https://github.com/Avinashistoocool/asclepius and github.com/Avinashistoocool")
        out, bad = H.fix_unverified_links(text, allowed)
        self.assertEqual(bad, ["github.com/Avinashistoocool/Colour-Object-Tracking."])
        self.assertIn("Code: github.com/Avinashistoocool. Also", out)
        self.assertIn("https://github.com/Avinashistoocool/asclepius", out)

    def test_links_survive_deslop(self):
        text = ("Dear Prof. X,\n\nCode: github.com/Avinashistoocool/GDS-parT-MoE and "
                "https://avinashistoocool.github.io/.\n\nBest,\nA")
        out = H.deslop(text)
        self.assertIn("github.com/Avinashistoocool/GDS-parT-MoE", out)
        self.assertIn("https://avinashistoocool.github.io/", out)


class SelfFundingGuardTests(unittest.TestCase):
    def test_gaps_found_by_diag_content_are_closed(self):
        for offer in ("I can join unpaid.", "I'd be happy to work unpaid for the summer.",
                      "I can discuss contributions toward costs.",
                      "I could make a contribution to the costs.",
                      "No stipend is needed.", "I don't need a stipend."):
            self.assertTrue(H.offers_self_funding(offer), offer)
            self.assertEqual(H.strip_self_funding(offer), "", offer)

    def test_existing_behaviour_kept(self):
        self.assertTrue(H.offers_self_funding("I can cover my own travel and living costs."))
        self.assertFalse(H.offers_self_funding("I can't cover my own travel costs."))
        self.assertFalse(H.offers_self_funding("I built a gated transformer."))


class RedraftLoopTests(unittest.TestCase):
    def prof(self):
        return Professor(name="Prof. Thomas Kuhr", email="thomas.kuhr@lmu.de",
                         institution="LMU Munich", research_area="Belle II")

    def test_bad_draft_is_redrafted_once(self):
        ev = _evaluator()
        bad = GOOD_BODY.replace("Could I spend", "Do you have capacity for a student? Could I spend")
        ev._client = _Client([("summer internship inquiry", bad), (GOOD_SUBJECT, GOOD_BODY)])
        p = ev.evaluate_one(self.prof(), model="gpt-4.1")
        self.assertEqual(len(ev._client.requests), 2)
        self.assertIn("REJECTED", ev._client.requests[1]["messages"][1]["content"])
        self.assertIn("capacity", ev._client.requests[1]["messages"][1]["content"])
        self.assertTrue(p.llm_status.startswith("ok") and "+redraft" in p.llm_status, p.llm_status)
        self.assertNotIn("REJECTED DRAFT", p.ai_flags)
        self.assertEqual(p.email_subject, GOOD_SUBJECT)

    def test_still_bad_after_redraft_is_flagged(self):
        ev = _evaluator()
        bad = GOOD_BODY.replace("My CV", "I had trouble following the proofs. My CV")
        ev._client = _Client([(GOOD_SUBJECT, bad), (GOOD_SUBJECT, bad)])
        p = ev.evaluate_one(self.prof(), model="gpt-4.1")
        self.assertEqual(len(ev._client.requests), 2)
        self.assertTrue(p.ai_flags.startswith("REJECTED DRAFT:"), p.ai_flags)
        self.assertIn("trouble following", p.ai_flags)

    def test_unverified_number_is_stripped_not_rejected(self):
        ev = _evaluator()
        body = GOOD_BODY.replace("trained on 10M jets.", "trained on 10M jets. My GPA was 7.6.")
        body = body.replace("GPA", "grade average")
        ev._client = _Client([(GOOD_SUBJECT, body)])
        p = ev.evaluate_one(self.prof(), model="gpt-4.1")
        self.assertNotIn("7.6", p.email_body)
        self.assertIn("84.84%", p.email_body)
        self.assertEqual(len(ev._client.requests), 1)

    def test_tidy_body_drops_second_greeting(self):
        body = "Dear Dr. Arganda,\n\nProfessor Arganda,\n\nI'm a student.\n\nBest,\nA"
        out = tidy_body(body, "Ernesto Arganda")
        self.assertEqual(out.count("Arganda"), 1, out)


if __name__ == "__main__":
    unittest.main()
