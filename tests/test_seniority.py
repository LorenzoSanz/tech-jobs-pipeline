import unittest

from jobpipe.seniority import ALL, ORDER, UNSPECIFIED, seniority_of


class SeniorityTest(unittest.TestCase):
    def test_levels(self):
        cases = {
            "Data Engineering Intern": "intern",
            "Werkstudent Data Engineering (m/w/d)": "intern",
            "Becario/a de Datos": "intern",
            "Apprenti/e Employé/e de commerce": "intern",
            "Lernende/r Informatiker/in EFZ": "intern",
            "Head of Data": "head",
            "Director, Engineering": "head",
            "VP of Engineering": "head",
            "Senior Staff Engineer": "lead",
            "Principal Data Scientist": "lead",
            "Tech Lead, Payments": "lead",
            "Senior Backend Engineer": "senior",
            "Sr. Data Engineer": "senior",
            "Software Engineer III": "senior",
            "Junior Frontend Developer": "junior",
            "Graduate Software Engineer": "junior",
            "Software Engineer I": "junior",
            "Data Engineer II - Platform": "mid",
            "Mid-Level Python Developer": "mid",
            "Data Engineer": UNSPECIFIED.key,
            "Manager II, Engineering": UNSPECIFIED.key,  # a management step, not mid-level
            "Commercial & Mid-Market Sales Engineer": UNSPECIFIED.key,
            "AI Engineer": UNSPECIFIED.key,
            "": UNSPECIFIED.key,
        }
        for title, expected in cases.items():
            with self.subTest(title=title):
                self.assertEqual(seniority_of(title), expected)

    def test_every_level_has_both_labels(self):
        self.assertEqual(ORDER[-1], UNSPECIFIED.key)
        for level in ALL:
            self.assertTrue(level.label("en") and level.label("es"), level.key)


if __name__ == "__main__":
    unittest.main()
