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


if __name__ == "__main__":
    unittest.main()
