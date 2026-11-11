import tempfile
import unittest
import zipfile
from pathlib import Path

from jobpipe import cv

DOCX_BODY = (
    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
    "<w:p><w:r><w:t>Data Engineer</w:t></w:r></w:p>"
    "<w:p><w:r><w:t>Python, </w:t></w:r><w:r><w:t>Kafka</w:t></w:r></w:p>"
    "</w:body></w:document>"
)
PROFILE_CSV = (
    "First Name,Last Name,Address,Birth Date,Headline,Summary\n"
    'Ana,Doe,"Calle 1, Madrid",1 Jan 1990,Data Engineer | Python,"I build pipelines with Airflow."\n'
)
SKILLS_CSV = "Name\nPostgreSQL\nDocker\n"
POSITIONS_CSV = (
    "Notes:\n\"This file lists your positions\"\n\n"
    "Company Name,Title,Description,Location,Started On,Finished On\n"
    'Acme,Backend Engineer,"Go services on Kubernetes",Madrid,Jan 2022,\n'
)


class ReadTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_text_and_docx(self):
        (self.root / "cv.md").write_text("# Ana\nPython and SQL\n", encoding="utf-8")
        with zipfile.ZipFile(self.root / "cv.docx", "w") as archive:
            archive.writestr("word/document.xml", DOCX_BODY)

        self.assertIn("Python and SQL", cv.read_document(self.root / "cv.md"))
        self.assertEqual(cv.read_document(self.root / "cv.docx"), "Data Engineer\nPython, Kafka")
        with self.assertRaises(ValueError):
            cv.read_document(self.root / "cv.pdf")

    def test_linkedin_export_reads_only_the_profile_sections(self):
        with zipfile.ZipFile(self.root / "export.zip", "w") as archive:
            archive.writestr("Basic_LinkedInDataExport/Profile.csv", PROFILE_CSV)
            archive.writestr("Basic_LinkedInDataExport/Skills.csv", SKILLS_CSV)
            archive.writestr("Basic_LinkedInDataExport/Positions.csv", POSITIONS_CSV)
            archive.writestr("Basic_LinkedInDataExport/messages.csv", "FROM,CONTENT\nBob,Kafka?\n")
        folder = self.root / "export"
        folder.mkdir()
        (folder / "Skills.csv").write_text(SKILLS_CSV, encoding="utf-8")

        sections = cv.read_linkedin(self.root / "export.zip")

        self.assertEqual(sections["headline"], "Data Engineer | Python")
        self.assertEqual(sections["about"], "I build pipelines with Airflow.")
        self.assertEqual(sections["skills"], "PostgreSQL\nDocker")
        self.assertEqual(sections["experience"], "Backend Engineer\nGo services on Kubernetes")
        self.assertNotIn("Calle", "".join(sections.values()))  # the address is never read
        self.assertNotIn("Kafka", "".join(sections.values()))  # nor messages
        self.assertEqual(cv.read_linkedin(folder)["skills"], "PostgreSQL\nDocker")
        (self.root / "empty").mkdir()
        with self.assertRaises(ValueError):
            cv.read_linkedin(self.root / "empty")  # no export files


class ReviewTest(unittest.TestCase):
    wanted = cv.demand([
        ("Senior Data Engineer (m/w/d)", ["python", "kafka", "python"]),
        ("Data Engineer II - Zürich", ["python", "sql"]),
        ("Data Platform Engineer", ["python", "sql", "airflow"]),
        ("Backend Engineer", ["go"]),
    ])  # fmt: skip

    def test_demand_counts_postings(self):
        self.assertEqual(self.wanted.postings, 4)
        self.assertEqual(self.wanted.technologies["python"], 3)  # once per posting
        self.assertEqual(self.wanted.share("sql"), 0.5)
        self.assertEqual(self.wanted.titles.most_common(1), [("data engineer", 2)])

    def test_title_terms(self):
        self.assertEqual(cv.title_terms("Senior Backend Software Engineer, Payments"), {"software engineer"})
        self.assertEqual(cv.title_terms("Data Engineer / Data Analyst (m/w/d)"), {"data engineer", "data analyst"})
        self.assertEqual(cv.title_terms("Ingeniero/a de Datos - Madrid"), {"ingeniero de datos"})
        self.assertEqual(cv.title_terms("Desarrollador Backend"), {"desarrollador backend"})
        self.assertEqual(cv.title_terms("Head of Engineering"), set())

    def test_review_weights_by_demand(self):
        text = "Data engineer since 2020. Python, Kafka and dbt."
        found = cv.review("CV", text, {"python", "sql", "airflow"}, self.wanted)

        self.assertEqual(found.named, {"python", "kafka", "dbt"})
        self.assertAlmostEqual(found.coverage, 4 / 8)  # python 3 + kafka 1 of 8 asks
        self.assertEqual(found.to_add, ("sql", "airflow"))
        self.assertEqual(found.to_learn, ("kafka", "go"))
        self.assertEqual(found.not_in_skills, ("dbt", "kafka"))
        self.assertEqual(found.titles, ("data engineer",))

    def test_render(self):
        found = cv.reviews({"CV": "Python", "LinkedIn": "SQL", "empty": " "}, {"python", "sql"}, self.wanted)

        text = cv.render_text(self.wanted, found, {"python", "sql"})

        self.assertEqual([r.name for r in found], ["CV", "LinkedIn"])
        self.assertIn("Add to CV, you list them as skills: SQL (50%)", text)
        self.assertIn("Add to LinkedIn, you list them as skills: Python (75%)", text)
        self.assertIn("No open postings", cv.render_text(cv.demand([]), [], set()))


if __name__ == "__main__":
    unittest.main()
