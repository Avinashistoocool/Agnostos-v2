"""Funding-likelihood factor: pure scoring + ranking tests (no network)."""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _isolate  # noqa: F401,E402  (must precede outreach imports)

from outreach import legacy as L
from outreach.funding import blended, funding_score
from outreach.models import Professor


class FundingScoreTest(unittest.TestCase):
    def test_industry_lab_beats_uk_university(self):
        g, gnote = funding_score("Google DeepMind", "GB")
        u, unote = funding_score("University of Manchester", "GB")
        self.assertGreater(g, 0.9)
        self.assertIn("Google", gnote)
        self.assertLess(u, 0.2)
        self.assertIn("UK", unote)

    def test_named_facility_and_country_names(self):
        self.assertGreaterEqual(funding_score("CERN", "Switzerland")[0], 0.8)
        fr, note = funding_score("Université Paris-Saclay", "France")
        self.assertAlmostEqual(fr, 0.55)
        self.assertIn("Charpak", note)

    def test_no_funding_reply_zeroes_score(self):
        s, note = funding_score("Google", "US", reply_text="Sadly we have no funding for interns.")
        self.assertEqual(s, 0.0)
        self.assertEqual(note, "said no funding")

    def test_unknown_university_gets_low_prior(self):
        s, note = funding_score("Some Random University", "")
        self.assertAlmostEqual(s, 0.15)
        self.assertIn("uncertain", note)

    def test_meta_word_boundary(self):
        self.assertNotIn("industry", funding_score("Metabolic Research Unit", "")[1])

    def test_blend(self):
        self.assertEqual(blended(0.8, 0.2, 0.0), 0.8)
        self.assertAlmostEqual(blended(0.8, 0.2, 1.0), 0.5)
        self.assertAlmostEqual(blended(0.0, 1.0, 2.0), 2 / 3)


class MatcherFundingTest(unittest.TestCase):
    def test_rank_weight_reorders_and_floor_uses_fit(self):
        from outreach.matcher import filter_candidates
        from outreach.resume_parser import ResumeProfile
        profile = ResumeProfile(name="S", research_interests=["particle physics", "collider jets"],
                                keywords=["particle physics", "collider", "jets"],
                                raw_text="particle physics collider jets machine learning")
        topic = "particle physics collider jets machine learning tagging"
        a = Professor(name="A", email="a@x.ac.uk", institution="University of Leeds",
                      country="GB", research_area=topic)
        b = Professor(name="B", email="b@cern.ch", institution="CERN",
                      country="CH", research_area=topic)
        c = Professor(name="C", email="c@google.com", institution="Google DeepMind",
                      country="GB", research_area="protein folding biology")
        selected, rejected = filter_candidates([a, b, c], profile, min_score=0.2,
                                               max_count=10, funding_weight=1.0)
        self.assertEqual([p.name for p in selected][:2], ["B", "A"])
        self.assertIn("C", [p.name for p in rejected])  # funding can't rescue off-topic
        self.assertTrue(selected[0].funding_note)


class LegacyFundingTest(unittest.TestCase):
    def test_merge_adds_columns_and_funding_weight_sorts(self):
        rows = [
            {"Name": "Uni Prof", "Institution": "University of Leeds", "Country": "GB", "h-index": 90},
            {"Name": "Lab Prof", "Institution": "Microsoft Research", "Country": "US", "h-index": 70},
        ]
        out = L.merge([dict(r) for r in rows], [], funding_weight=0.0)
        self.assertEqual(out[0]["Name"], "Uni Prof")
        self.assertIn("Funding Score", out[0])
        out = L.merge([dict(r) for r in rows], [], funding_weight=1.0)
        self.assertEqual(out[0]["Name"], "Lab Prof")
        self.assertIn("Microsoft", out[0]["Funding Route"])
        self.assertIn("Funding Score", L.COLUMNS)

    def test_programme_for_adds_industry_route(self):
        self.assertIn("Microsoft Research", L.programme_for("Microsoft Research", "US"))


if __name__ == "__main__":
    unittest.main()
