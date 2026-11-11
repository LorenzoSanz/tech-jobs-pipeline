import re
import unittest

from jobpipe import tech


class TechnologiesTest(unittest.TestCase):
    def test_spellings_land_on_one_key(self):
        for text in ("Postgres", "PostgreSQL 16", "postgres/redis"):
            self.assertIn("postgresql", tech.technologies_in(text), text)
        self.assertEqual(tech.technologies_in("k8s and Kubernetes"), ("kubernetes",))

    def test_ambiguous_names(self):
        cases = {
            "JavaScript and TypeScript": ("javascript", "typescript"),
            "Java 21, Spring Boot": ("java", "spring"),
            "React Native apps": ("react_native",),
            "React and Node.js": ("react", "nodejs"),
            "C++ and C#": ("csharp", "cpp"),
            "SQL, PostgreSQL and MySQL": ("sql", "postgresql", "mysql"),
            "PySpark jobs": ("spark",),
        }
        for text, expected in cases.items():
            self.assertEqual(tech.technologies_in(text), expected, text)

    def test_go_the_language_not_the_verb(self):
        for text in ("We write Go and Python", "Go, Rust or Java", "Golang services", "Go (preferred)",
                     "experience with Go microservices", "Go fluency"):  # fmt: skip
            self.assertIn("go", tech.technologies_in(text), text)
        for text in ("Be curious: Go deep", "Go-to-market team", "Go To Market", "Go onsite to meet users",
                     "go to the office", "Go beyond the brief", "go-live"):  # fmt: skip
            self.assertNotIn("go", tech.technologies_in(text), text)

    def test_words_inside_other_words_do_not_count(self):
        self.assertEqual(tech.technologies_in("Rustic charm, a scalable sqlite-free goal"), ())
        self.assertEqual(tech.technologies_in(None), ())

    def test_a_company_does_not_ask_for_its_own_product(self):
        self.assertEqual(tech.technologies_in("Datadog, Kubernetes", company="Datadog"), ("kubernetes",))
        self.assertEqual(tech.technologies_in("Grafana and Go", company="Grafana Labs"), ("go",))
        self.assertEqual(tech.technologies_in("Grafana", company="Acme"), ("grafana",))

    def test_catalogue_is_consistent(self):
        keys = [t.key for t in tech.CATALOGUE]
        self.assertEqual(len(keys), len(set(keys)))
        for t in tech.CATALOGUE:
            self.assertIn(t.category, tech.CATEGORIES, t.key)
            self.assertNotIn("'", t.label, t.key)  # labels go into SQL literals
            re.compile(t.pattern)


if __name__ == "__main__":
    unittest.main()
