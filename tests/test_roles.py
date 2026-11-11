import unittest

from jobpipe.roles import OTHER, role_of


class RoleTest(unittest.TestCase):
    def test_families(self):
        cases = {
            "Senior Backend Engineer": "Backend",
            "Data Engineer": "Datos",
            "Data Scientist": "ML / IA",
            "Engineering Manager, Payments": "Gestión técnica",
            "Head of Data": "Gestión técnica",
            "Mid Market Account Manager": OTHER,
            "Senior Product Manager": "Producto y diseño",
            "Site Reliability Engineer": "DevOps / SRE / Plataforma",
            "iOS Developer": "Móvil",
            "Full Stack Developer (React/Node)": "Full-stack",
            "Frontend Engineer": "Frontend",
            "Software Engineer": "Ingeniería (general)",
            "Acme | Madrid | Data Engineer | Remote": "Datos",
            "Office Assistant": OTHER,
        }
        for title, family in cases.items():
            with self.subTest(title=title):
                self.assertEqual(role_of(title), family)

    def test_words_not_substrings(self):
        self.assertEqual(role_of("Google Ads Specialist"), OTHER)  # "go" inside "Google"
        self.assertEqual(role_of(None), OTHER)


if __name__ == "__main__":
    unittest.main()
