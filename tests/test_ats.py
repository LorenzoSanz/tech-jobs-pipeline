import unittest
from datetime import datetime, timezone

from jobpipe.sources import ats
from tests.fakes import FakeTransport, fast_client


class GreenhouseTest(unittest.TestCase):
    def test_reads_full_board_with_content(self):
        transport = FakeTransport()
        transport.add(
            body={
                "jobs": [
                    {
                        "id": 4532353101,
                        "title": "Software Engineer",
                        "first_published": "2026-10-20T09:30:00-04:00",
                        "location": {"name": "Zürich, Switzerland"},
                    }
                ],
                "meta": {"total": 1},
            }
        )

        [item] = ats.greenhouse_jobs(fast_client(transport), "acme")

        self.assertEqual(item.source_id, "acme:4532353101")
        self.assertEqual(item.event_time, datetime(2026, 10, 20, 13, 30, tzinfo=timezone.utc))
        self.assertEqual(item.payload["board"], "acme")
        self.assertEqual(transport.urls(), ["https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=true"])

    def test_missing_publication_date_stays_unknown(self):
        transport = FakeTransport()
        transport.add(body={"jobs": [{"id": 1, "updated_at": "2026-11-01T00:00:00Z"}]})

        [item] = ats.greenhouse_jobs(fast_client(transport), "acme")

        self.assertIsNone(item.event_time)


class LeverTest(unittest.TestCase):
    def test_paginates_until_a_short_page(self):
        transport = FakeTransport()
        full_page = [{"id": f"id-{i}", "createdAt": 1761900000000} for i in range(ats.LEVER_PAGE_SIZE)]
        transport.add(body=full_page)
        transport.add(body=[{"id": "last", "createdAt": None}])

        items = list(ats.lever_jobs(fast_client(transport), "acme"))

        self.assertEqual(len(items), ats.LEVER_PAGE_SIZE + 1)
        self.assertEqual(items[0].event_time, datetime.fromtimestamp(1761900000, tz=timezone.utc))
        self.assertIsNone(items[-1].event_time)
        self.assertEqual(transport.query(1)["skip"], str(ats.LEVER_PAGE_SIZE))


class AshbyTest(unittest.TestCase):
    def test_requests_compensation_and_uses_published_at(self):
        transport = FakeTransport()
        transport.add(
            body={
                "jobs": [
                    {
                        "id": "145ff46b",
                        "title": "Platform Engineer",
                        "publishedAt": "2026-09-15T08:00:00.000+00:00",
                        "compensation": {"compensationTierSummary": "CHF 120K – 150K"},
                    }
                ]
            }
        )

        [item] = ats.ashby_jobs(fast_client(transport), "acme")

        self.assertEqual(item.event_time, datetime(2026, 9, 15, 8, tzinfo=timezone.utc))
        self.assertEqual(transport.query(0), {"includeCompensation": "true"})


class IngestTest(unittest.TestCase):
    def test_a_broken_board_is_recorded_and_skipped(self):
        transport = FakeTransport()
        transport.add(status=404, body={"error": "not found"})
        transport.add(body={"jobs": [{"id": 1}]})
        failures: list = []

        items = list(ats.ingest(fast_client(transport), "greenhouse", ["typo", "acme"], failures))

        self.assertEqual([i.source_id for i in items], ["acme:1"])
        self.assertEqual([(f.ats, f.board) for f in failures], [("greenhouse", "typo")])

    def test_a_board_failing_mid_pagination_contributes_nothing(self):
        transport = FakeTransport()
        transport.add(body=[{"id": f"id-{i}"} for i in range(ats.LEVER_PAGE_SIZE)])
        transport.add(status=400, body={"error": "bad request"})
        failures: list = []

        items = list(ats.ingest(fast_client(transport), "lever", ["acme"], failures))

        self.assertEqual(items, [])
        self.assertEqual(len(failures), 1)


class BoardNameTest(unittest.TestCase):
    def test_board_names_with_spaces_are_url_encoded(self):
        transport = FakeTransport()
        transport.add(body={"jobs": []})

        list(ats.ashby_jobs(fast_client(transport), "Acme AI"))

        self.assertTrue(transport.urls()[0].startswith(f"{ats.ASHBY_API}/Acme%20AI?"))


if __name__ == "__main__":
    unittest.main()
