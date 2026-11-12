import unittest
from pathlib import Path

from jobpipe import match

EXAMPLE = Path(__file__).resolve().parent.parent / "config" / "profile.example.toml"

PROFILE = match.parse_profile("""
skills = ["python", "sql", "postgresql"]
roles = ["data", "backend"]
regions = ["ch", "es"]
exclude_title = 'intern|\\bvp\\b'
""")


class ProfileTest(unittest.TestCase):
    def test_example_profile_is_valid(self):
        profile = match.load_profile(EXAMPLE)
        self.assertIn("python", profile.skills)
        self.assertTrue(profile.exclude_title.search("Enterprise Account Executive"))
        self.assertIn("unspecified", profile.seniority)

    def test_unknown_names_are_rejected_with_the_valid_ones(self):
        with self.assertRaisesRegex(match.ProfileError, "unknown skills: pyhton.*python"):
            match.parse_profile('skills = ["pyhton"]')
        with self.assertRaisesRegex(match.ProfileError, "unknown regions: de"):
            match.parse_profile('skills = ["sql"]\nregions = ["de"]')
        with self.assertRaisesRegex(match.ProfileError, "skills is empty"):
            match.parse_profile("roles = []")


class MatchTest(unittest.TestCase):
    def test_score_is_the_share_of_asked_technologies_you_know(self):
        m = match.match(PROFILE, "Data Engineer", "data", ["ch"], ["python", "sql", "kafka", "spark"])

        self.assertTrue(m.fits)
        self.assertEqual(m.score, 0.5)
        self.assertEqual((m.have, m.missing), (("python", "sql"), ("kafka", "spark")))

    def test_filters(self):
        self.assertFalse(match.match(PROFILE, "Designer", "product", ["ch"], []).fits)
        self.assertFalse(match.match(PROFILE, "Data Engineer", "data", ["eu"], []).fits)
        self.assertFalse(match.match(PROFILE, "Data Intern", "data", ["es"], []).fits)
        self.assertFalse(match.match(PROFILE, "Data Engineer", "data", [], []).fits)  # unknown region is "other"
        everywhere = match.Profile(skills=frozenset({"sql"}))
        self.assertTrue(match.match(everywhere, "Anything", "other", [], []).fits)

    def test_seniority_filter(self):
        profile = match.parse_profile('skills = ["sql"]\nseniority = ["mid", "unspecified"]')

        self.assertTrue(match.match(profile, "Data Engineer", "data", ["ch"], []).fits)
        self.assertTrue(match.match(profile, "Data Engineer II", "data", ["ch"], [], "mid").fits)
        self.assertFalse(match.match(profile, "Head of Data", "data", ["ch"], [], "head").fits)
        big_tech = match.parse_profile('skills = ["sql"]\ncompany_tiers = ["faang", "big_tech"]')
        self.assertTrue(match.match(big_tech, "SWE", "backend", ["ch"], [], company_tier="faang").fits)
        self.assertFalse(match.match(big_tech, "SWE", "backend", ["ch"], []).fits)  # "other" by default
        with self.assertRaisesRegex(match.ProfileError, "unknown company_tiers: faamg"):
            match.parse_profile('skills = ["sql"]\ncompany_tiers = ["faamg"]')
        with self.assertRaisesRegex(match.ProfileError, "unknown seniority: medior"):
            match.parse_profile('skills = ["sql"]\nseniority = ["medior"]')

    def test_rank_needs_evidence(self):
        def rank(have, missing):
            return match.match(PROFILE, "x", "data", ["ch"], have + missing).rank

        self.assertLess(rank(["sql"], []), rank(["python", "sql", "postgresql"], ["kafka"]))
        self.assertLess(rank(["sql"], []), rank(["python", "sql"], []))
        self.assertLess(match.match(PROFILE, "x", "data", ["ch"], []).rank, rank([], ["kafka"]))
        self.assertIsNone(match.match(PROFILE, "x", "data", ["ch"], []).score)

    def test_gaps_count_fitting_scored_postings_only(self):
        matches = [
            match.match(PROFILE, "a", "data", ["ch"], ["python", "kafka"]),
            match.match(PROFILE, "b", "data", ["es"], ["kafka", "spark"]),
            match.match(PROFILE, "c", "data", ["es"], []),  # no technologies: not in the denominator
            match.match(PROFILE, "d", "product", ["es"], ["figma"]),  # does not fit
        ]
        self.assertEqual(match.gaps(matches), [("kafka", 2, 1.0), ("spark", 1, 0.5)])


if __name__ == "__main__":
    unittest.main()
