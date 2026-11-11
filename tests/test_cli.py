import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from jobpipe.bronze import BronzeWriter, RawItem
from jobpipe.cli import main
from tests.fakes import FakeTransport, fast_client


class CliTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.data_dir = self.root / "bronze"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_cli(self, *argv: str, transport: FakeTransport | None = None) -> tuple[int, str]:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(io.StringIO()):
            code = main(
                ["--data-dir", str(self.data_dir), *argv],
                http=fast_client(transport or FakeTransport()),
            )
        return code, stdout.getvalue()

    def test_ingest_ats_writes_one_partition_per_ats_and_reports_failures(self):
        boards = self.root / "boards.toml"
        boards.write_text('[greenhouse]\nboards = ["acme", "typo"]\n[lever]\nboards = []\n')
        transport = FakeTransport()
        transport.add(body={"jobs": [{"id": 1}, {"id": 2}]})
        transport.add(status=404, body={})

        code, out = self.run_cli("ingest", "ats", "--boards", str(boards), transport=transport)

        self.assertEqual(code, 0)
        summary = json.loads(out)
        self.assertEqual(summary["source"], "greenhouse")
        self.assertEqual(summary["records"], 2)
        self.assertEqual(summary["failed_boards"], ["typo"])
        self.assertTrue(Path(summary["path"]).exists())

    def test_ingest_ats_fails_when_every_board_fails(self):
        boards = self.root / "boards.toml"
        boards.write_text('[ashby]\nboards = ["typo"]\n')
        transport = FakeTransport()
        transport.add(status=404, body={})

        code, _ = self.run_cli("ingest", "ats", "--boards", str(boards), transport=transport)

        self.assertEqual(code, 1)

    def test_ingest_adzuna_requires_credentials(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            code, out = self.run_cli("ingest", "adzuna")

        self.assertEqual(code, 2)
        self.assertEqual(out, "")

    def test_ingest_adzuna_writes_one_run_per_country_and_survives_a_failing_one(self):
        transport = FakeTransport()
        transport.add(body={"results": [{"id": "1", "created": "2026-11-08T07:00:00Z"}]})
        transport.add(status=400, body={"exception": "BAD_COUNTRY"})
        env = {"ADZUNA_APP_ID": "id", "ADZUNA_APP_KEY": "key"}

        with mock.patch.dict(os.environ, env, clear=True):
            code, out = self.run_cli(
                "ingest", "adzuna", "--country", "es", "--country", "xx", transport=transport
            )

        self.assertEqual(code, 0)
        [summary] = [json.loads(line) for line in out.splitlines()]
        self.assertEqual((summary["country"], summary["records"]), ("es", 1))
        self.assertIn("/jobs/es/search/1", transport.urls()[0])

    def test_discover_boards_prints_a_reviewable_toml_snippet(self):
        BronzeWriter(self.data_dir).write(
            "hn",
            [RawItem("1", {"comment": {"text": "Acme | Zurich | https://jobs.lever.co/acme"}})],
        )

        code, out = self.run_cli("discover-boards")

        self.assertEqual(code, 0)
        self.assertIn('[lever]\nboards = [\n  "acme",  # 1\n]', out)

    def test_salaries_reports_posted_ranges_per_currency(self):
        job = {
            "id": "a1",
            "title": "Backend Engineer",
            "location": "Zurich",
            "compensation": {
                "summaryComponents": [
                    {"compensationType": "Salary", "currencyCode": "CHF", "interval": "1 YEAR",
                     "minValue": 120000, "maxValue": 150000}
                ]
            },
        }  # fmt: skip
        BronzeWriter(self.data_dir).write("ashby", [RawItem("acme:a1", {"board": "acme", "job": job})])

        code, out = self.run_cli("salaries", "--region", "ch", "--title", "backend")
        _, as_json = self.run_cli("salaries", "--format", "json", "--region", "es")

        self.assertEqual(code, 0)
        self.assertIn("## CHF - 1 postings", out)
        self.assertIn("120k-150k  acme | Backend Engineer | Zurich", out)
        self.assertEqual(json.loads(as_json)["postings"], {})

    def test_ingest_adzuna_salaries_one_run_per_search(self):
        transport = FakeTransport()
        transport.add(body={"histogram": {"90000": "3"}})
        transport.add(body={"month": {"2026-10": 100000}})
        transport.add(body={"histogram": {"110000": "2"}})
        env = {"ADZUNA_APP_ID": "id", "ADZUNA_APP_KEY": "key"}

        with mock.patch.dict(os.environ, env, clear=True):
            code, out = self.run_cli(
                "ingest", "adzuna-salaries", "--what", "data engineer", "--what", "sre",
                transport=transport,
            )  # fmt: skip

        self.assertEqual(code, 0)
        summaries = [json.loads(line) for line in out.splitlines()]
        self.assertEqual([(s["what"], s["records"]) for s in summaries], [("data engineer", 2), ("sre", 1)])

    def test_levelsfyi_requires_an_official_api_key(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            code, out = self.run_cli("ingest", "levelsfyi", "--location", "zurich-area")
            lookup_code, _ = self.run_cli("levelsfyi-lookup", "locations", "zurich")

        self.assertEqual((code, lookup_code, out), (2, 2, ""))

    def test_ingest_levelsfyi_writes_benchmarks(self):
        transport = FakeTransport()
        transport.add(body=[{"locationName": "Zurich", "locationSlug": "zurich-area", "p10": 1,
                             "p25": 2, "p50": 3, "p75": 4, "p90": 5, "sampleSize": 8}])  # fmt: skip
        transport.add(body=[])

        with mock.patch.dict(os.environ, {"LEVELS_FYI_API_KEY": "k"}, clear=True):
            code, out = self.run_cli("ingest", "levelsfyi", "--location", "zurich-area", transport=transport)

        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["records"], 1)


if __name__ == "__main__":
    unittest.main()
