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

    def test_discover_boards_prints_a_reviewable_toml_snippet(self):
        BronzeWriter(self.data_dir).write(
            "hn",
            [RawItem("1", {"comment": {"text": "Acme | Zurich | https://jobs.lever.co/acme"}})],
        )

        code, out = self.run_cli("discover-boards")

        self.assertEqual(code, 0)
        self.assertIn('[lever]\nboards = [\n  "acme",  # 1\n]', out)


if __name__ == "__main__":
    unittest.main()
