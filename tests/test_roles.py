import unittest

from jobpipe.roles import ALL, OTHER, role_of


class RoleTest(unittest.TestCase):
    def test_families(self):
        cases = {
            "Senior Backend Engineer": "backend",
            "Data Engineer": "data",
            "Data Scientist": "ml",
            "Engineering Manager, Payments": "eng_management",
            "Head of Data": "eng_management",
            "Mid Market Account Manager": OTHER.key,
            "Senior Product Manager": "product",
            "Site Reliability Engineer": "devops",
            "iOS Developer": "mobile",
            "Full Stack Developer (React/Node)": "fullstack",
            "Frontend Engineer": "frontend",
            "Software Engineer": "engineering",
            "Acme | Madrid | Data Engineer | Remote": "data",
            "Office Assistant": OTHER.key,
        }
        for title, family in cases.items():
            with self.subTest(title=title):
                self.assertEqual(role_of(title), family)

    def test_words_not_substrings(self):
        self.assertEqual(role_of("Google Ads Specialist"), OTHER.key)  # "go" inside "Google"
        self.assertEqual(role_of(None), OTHER.key)

    def test_every_family_has_unique_key_and_both_labels(self):
        self.assertEqual(len({f.key for f in ALL}), len(ALL))
        for family in ALL:
            self.assertTrue(family.en and family.es, family.key)
            self.assertNotIn("'", family.en + family.es)  # labels are inlined into SQL


if __name__ == "__main__":
    unittest.main()
