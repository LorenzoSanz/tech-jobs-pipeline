import unittest
from datetime import datetime, timezone

from jobpipe.sources import adzuna
from tests.fakes import FakeTransport, fast_client

CREDENTIALS = adzuna.AdzunaCredentials(app_id="id-123", app_key="key-456")


def job(job_id: int) -> dict:
    return {"id": str(job_id), "created": "2026-11-08T07:00:00Z", "title": "DevOps Engineer"}


class AdzunaTest(unittest.TestCase):
    def test_pages_through_results_newest_first(self):
        transport = FakeTransport()
        transport.add(body={"count": 51, "results": [job(i) for i in range(adzuna.RESULTS_PER_PAGE)]})
        transport.add(body={"count": 51, "results": [job(999)]})

        items = list(adzuna.ingest(fast_client(transport), CREDENTIALS, adzuna.AdzunaQuery()))

        self.assertEqual(len(items), adzuna.RESULTS_PER_PAGE + 1)
        self.assertEqual(items[-1].source_id, "ch:999")
        self.assertEqual(items[0].event_time, datetime(2026, 11, 8, 7, tzinfo=timezone.utc))
        self.assertTrue(transport.urls()[1].startswith("https://api.adzuna.com/v1/api/jobs/ch/search/2?"))
        query = transport.query(0)
        self.assertEqual(query["category"], "it-jobs")
        self.assertEqual(query["sort_by"], "date")

    def test_respects_the_page_limit(self):
        transport = FakeTransport()
        transport.add(body={"results": [job(i) for i in range(adzuna.RESULTS_PER_PAGE)]})

        items = list(
            adzuna.ingest(fast_client(transport), CREDENTIALS, adzuna.AdzunaQuery(max_pages=1))
        )

        self.assertEqual(len(items), adzuna.RESULTS_PER_PAGE)
        self.assertEqual(len(transport.requests), 1)

    def test_credentials_stay_out_of_the_payload(self):
        transport = FakeTransport()
        transport.add(body={"results": [job(1)]})

        [item] = adzuna.ingest(fast_client(transport), CREDENTIALS, adzuna.AdzunaQuery())

        self.assertNotIn("key-456", repr(item.payload))


class AdzunaSalaryTest(unittest.TestCase):
    def test_histogram_for_each_search_and_category_history(self):
        transport = FakeTransport()
        transport.add(body={"histogram": {"80000": "4", "100000": "7"}})
        transport.add(body={"month": {"2026-10": 101000.5}})
        query = adzuna.SalaryQuery(country="ch", what="data engineer")

        items = list(adzuna.salary_benchmarks(fast_client(transport), CREDENTIALS, query))

        self.assertEqual([i.payload["kind"] for i in items], ["histogram", "history"])
        self.assertEqual(items[0].source_id, "ch:histogram:it-jobs:data engineer")
        self.assertEqual(items[0].payload["histogram"], {"80000": "4", "100000": "7"})
        self.assertIn("/jobs/ch/histogram?", transport.urls()[0])
        self.assertEqual(transport.query(0)["what"], "data engineer")
        self.assertEqual(transport.query(1)["months"], "12")
        self.assertNotIn("key-456", repr([i.payload for i in items]))

    def test_history_can_be_skipped(self):
        transport = FakeTransport()
        transport.add(body={"histogram": {}})

        items = list(
            adzuna.salary_benchmarks(
                fast_client(transport), CREDENTIALS, adzuna.SalaryQuery(history_months=0)
            )
        )

        self.assertEqual(len(items), 1)
        self.assertEqual(len(transport.requests), 1)


if __name__ == "__main__":
    unittest.main()
