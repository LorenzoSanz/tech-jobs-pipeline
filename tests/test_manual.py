import contextlib
import io
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from jobpipe import employers, jobs, salary
from jobpipe.bronze import read_records
from jobpipe.cli import main
from jobpipe.sources import manual

ADDED = datetime(2026, 11, 13, 9, 0, tzinfo=UTC)


def record(item):
    return {"source_id": item.source_id, "event_time": item.event_time.isoformat(), "payload": item.payload,
            "fetched_at": ADDED.isoformat(), "source": manual.SOURCE}  # fmt: skip


class ManualPostingTest(unittest.TestCase):
    def test_a_pasted_posting_becomes_a_posting_with_region_and_tier(self):
        item = manual.posting(
            "Software Engineer III", "Google", "Zurich, Switzerland", "CH",
            "https://careers.example/jobs/1", "Java and distributed systems. 2 years of experience.", ADDED,
        )  # fmt: skip

        posting = jobs.to_posting(manual.SOURCE, record(item))

        assert posting is not None
        self.assertEqual(posting.title, "Software Engineer III")
        self.assertEqual(posting.regions, ("ch",))
        self.assertEqual(posting.place.city, "Zurich")
        self.assertEqual(employers.employer_of(posting.company).tier, "faang")
        self.assertIn("Java", posting.description)

    def test_the_same_url_keeps_the_same_id(self):
        first = manual.posting("Engineer", "Acme", url="https://example.com/jobs/1")
        again = manual.posting("Engineer (edited)", "Acme", url="https://example.com/jobs/1")
        other = manual.posting("Engineer", "Acme", location="Zurich")

        self.assertEqual(first.source_id, again.source_id)
        self.assertNotEqual(first.source_id, other.source_id)

    def test_a_salary_in_the_text_is_extracted(self):
        item = manual.posting("Backend Engineer", "Acme", "Zurich", "ch", description="Salary: CHF 110k - 130k.")

        found = list(salary.EXTRACTORS[manual.SOURCE](record(item)))

        self.assertEqual([(s.currency, s.min_annual, s.max_annual) for s in found], [("CHF", 110000, 130000)])

    def test_jobpipe_add_writes_one_bronze_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "bronze"
            text = Path(tmp) / "posting.txt"
            text.write_text("About the job: Java.", encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                code = main(["--data-dir", str(data_dir), "add", "--title", "Software Engineer III",
                             "--company", "Google", "--location", "Zurich", "--country", "ch",
                             "--description-file", str(text)])  # fmt: skip

            records = list(read_records(data_dir, manual.SOURCE))

        self.assertEqual(code, 0)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["payload"]["description"], "About the job: Java.")


if __name__ == "__main__":
    unittest.main()
