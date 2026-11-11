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


class SmartRecruitersTest(unittest.TestCase):
    def test_pages_the_list_and_reads_the_text_of_regional_tech_postings_only(self):
        transport = FakeTransport()
        ch_dev = {"id": "1", "name": "Backend Developer", "releasedDate": "2026-11-01T10:00:00.000Z",
                  "location": {"country": "ch"}}
        ch_sales = {"id": "2", "name": "Account Manager", "location": {"country": "ch"}}
        us_dev = {"id": "3", "name": "Data Engineer", "location": {"country": "us"}}
        transport.add(body={"totalFound": 3, "content": [ch_dev, ch_sales]})
        transport.add(body={"totalFound": 3, "content": [us_dev]})
        transport.add(body={**ch_dev, "jobAd": {"sections": {"jobDescription": {"text": "Python"}}}})

        items = list(ats.smartrecruiters_jobs(fast_client(transport), "Acme"))

        self.assertEqual([i.source_id for i in items], ["Acme:1", "Acme:2", "Acme:3"])
        self.assertIn("jobAd", items[0].payload["job"])
        self.assertNotIn("jobAd", items[1].payload["job"])
        self.assertEqual(items[0].event_time, datetime(2026, 11, 1, 10, tzinfo=timezone.utc))
        self.assertEqual(transport.query(1)["offset"], "2")
        self.assertEqual(transport.urls()[2], f"{ats.SMARTRECRUITERS_API}/Acme/postings/1")  # fmt: skip


class WorkableTest(unittest.TestCase):
    def test_uses_the_shortcode_and_publication_day(self):
        transport = FakeTransport()
        transport.add(body={"jobs": [{"shortcode": "2FAA7C", "title": "SRE", "published_on": "2026-10-02"}]})

        [item] = ats.workable_jobs(fast_client(transport), "acme")

        self.assertEqual(item.source_id, "acme:2FAA7C")
        self.assertEqual(item.event_time, datetime(2026, 10, 2, tzinfo=timezone.utc))
        self.assertEqual(transport.query(0), {"details": "true"})


class RecruiteeTest(unittest.TestCase):
    def test_reads_the_board_host_and_its_utc_dates(self):
        transport = FakeTransport()
        transport.add(body={"offers": [{"id": 7, "title": "Dev", "published_at": "2026-11-03 20:08:14 UTC"}]})

        [item] = ats.recruitee_jobs(fast_client(transport), "acme")

        self.assertEqual(transport.urls(), ["https://acme.recruitee.com/api/offers/"])
        self.assertEqual(item.event_time, datetime(2026, 11, 3, 20, 8, 14, tzinfo=timezone.utc))

    def test_a_board_name_cannot_change_the_host(self):
        for board in ("evil.com/x", "a.b", "Acme", ""):
            with self.subTest(board=board), self.assertRaises(ValueError):
                list(ats.recruitee_jobs(fast_client(FakeTransport()), board))


class PersonioTest(unittest.TestCase):
    XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<workzag-jobs><position>
  <id>42</id><office>Zurich</office><additionalOffices><office>Madrid</office></additionalOffices>
  <name>Data Engineer</name><createdAt>2026-11-01T09:00:00+01:00</createdAt>
  <jobDescriptions><jobDescription><name>Tasks</name><value><![CDATA[<p>dbt and SQL</p>]]></value></jobDescription>
  </jobDescriptions>
</position></workzag-jobs>"""

    def test_turns_each_xml_position_into_a_job(self):
        transport = FakeTransport()
        transport.add(body=self.XML)

        [item] = ats.personio_jobs(fast_client(transport), "acme")

        job = item.payload["job"]
        self.assertEqual(item.source_id, "acme:42")
        self.assertEqual(item.event_time, datetime(2026, 11, 1, 8, tzinfo=timezone.utc))
        self.assertEqual((job["name"], job["office"], job["additionalOffices"]), ("Data Engineer", "Zurich", ["Madrid"]))
        self.assertEqual(job["descriptions"], [{"name": "Tasks", "value": "<p>dbt and SQL</p>"}])
        self.assertEqual(job["url"], "https://acme.jobs.personio.de/job/42")
        self.assertIn("<id>42</id>", job["xml"])
        self.assertEqual(transport.urls(), ["https://acme.jobs.personio.de/xml?language=en"])

    def test_broken_xml_fails_only_that_board(self):
        transport = FakeTransport()
        transport.add(body=b"<html>maintenance")
        failures: list = []

        self.assertEqual(list(ats.ingest(fast_client(transport), "personio", ["acme"], failures)), [])
        self.assertEqual([f.board for f in failures], ["acme"])


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
