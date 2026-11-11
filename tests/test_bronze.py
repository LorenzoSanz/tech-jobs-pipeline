import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from jobpipe.bronze import BronzeWriter, RawItem, payload_hash, read_records

T0 = datetime(2026, 11, 9, 8, 15, tzinfo=UTC)


class StepClock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        value = self.now
        self.now += timedelta(seconds=1)
        return value


class BronzeWriterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.writer = BronzeWriter(self.root, clock=StepClock())

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_writes_one_envelope_per_item_in_a_dated_partition(self):
        items = [
            RawItem("acme:1", {"title": "Backend Engineer"}, datetime(2026, 10, 1, tzinfo=UTC)),
            RawItem("acme:2", {"title": "Platform Engineer"}),
        ]

        result = self.writer.write("lever", items, run_id="run-1")

        self.assertEqual(result.records, 2)
        self.assertEqual(
            result.path, self.root / "source=lever" / "ingest_date=2026-11-09" / "run=run-1.jsonl"
        )
        first, second = [json.loads(line) for line in result.path.read_text().splitlines()]
        self.assertEqual(first["source_id"], "acme:1")
        self.assertEqual(first["event_time"], "2026-10-01T00:00:00+00:00")
        self.assertEqual(first["payload"], {"title": "Backend Engineer"})
        self.assertEqual(first["payload_sha256"], payload_hash({"title": "Backend Engineer"}))
        self.assertIsNone(second["event_time"])
        self.assertLess(first["fetched_at"], second["fetched_at"])

    def test_hash_ignores_key_order(self):
        self.assertEqual(payload_hash({"a": 1, "b": 2}), payload_hash({"b": 2, "a": 1}))

    def test_refuses_to_overwrite_an_existing_run(self):
        self.writer.write("hn", [RawItem("1", {})], run_id="run-1")

        with self.assertRaises(FileExistsError):
            self.writer.write("hn", [RawItem("2", {})], run_id="run-1")

    def test_writes_nothing_when_there_are_no_items(self):
        result = self.writer.write("hn", [], run_id="run-1")

        self.assertIsNone(result.path)
        self.assertEqual(list(self.root.rglob("*")), [])

    def test_leaves_no_partial_file_when_the_source_fails_mid_run(self):
        def failing():
            yield RawItem("1", {})
            raise RuntimeError("API went away")

        with self.assertRaises(RuntimeError):
            self.writer.write("hn", failing(), run_id="run-1")

        self.assertEqual([p for p in self.root.rglob("*") if p.is_file()], [])

    def test_rejects_naive_timestamps(self):
        with self.assertRaises(ValueError):
            self.writer.write("hn", [RawItem("1", {}, datetime(2026, 1, 1))], run_id="run-1")

    def test_reads_back_all_runs_of_a_source(self):
        self.writer.write("hn", [RawItem("1", {})], run_id="run-1")
        self.writer.write("hn", [RawItem("2", {})], run_id="run-2")
        self.writer.write("lever", [RawItem("x", {})], run_id="run-3")

        ids = [record["source_id"] for record in read_records(self.root, "hn")]

        self.assertEqual(ids, ["1", "2"])


if __name__ == "__main__":
    unittest.main()
