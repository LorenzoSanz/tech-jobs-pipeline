import unittest

from jobpipe import jobs


def record(source: str, job: dict, board: str = "acme") -> dict:
    return {"source": source, "source_id": f"{board}:1", "payload": {"board": board, "job": job},
            "event_time": "2026-11-01T00:00:00+00:00", "fetched_at": "2026-11-10T08:00:00+00:00"}  # fmt: skip


class ToPostingTest(unittest.TestCase):
    def test_smartrecruiters(self):
        job = {"id": "1", "name": "Data Engineer", "company": {"name": "Acme AG"},
               "location": {"fullLocation": "Bern, BE, Switzerland", "country": "ch"},
               "postingUrl": "https://jobs.smartrecruiters.com/Acme/1",
               "jobAd": {"sections": {"jobDescription": {"text": "<p>Kafka</p>"}, "qualifications": {"text": "SQL"}}}}  # fmt: skip

        posting = jobs.to_posting("smartrecruiters", record("smartrecruiters", job))

        self.assertEqual((posting.title, posting.company, posting.regions), ("Data Engineer", "Acme AG", ("ch",)))
        self.assertEqual(posting.description.split(), ["Kafka", "SQL"])

    def test_smartrecruiters_without_detail_still_has_a_link(self):
        job = {"id": "2", "name": "Account Manager", "location": {"country": "us"}}

        posting = jobs.to_posting("smartrecruiters", record("smartrecruiters", job, board="Acme"))

        self.assertEqual(posting.url, "https://jobs.smartrecruiters.com/Acme/2")
        self.assertEqual(posting.description, "")

    def test_workable_uses_the_country_code(self):
        job = {"shortcode": "9F", "title": "SRE", "city": "Madrid", "country": "Spain",
               "locations": [{"countryCode": "ES"}], "url": "https://apply.workable.com/j/9F"}  # fmt: skip

        posting = jobs.to_posting("workable", record("workable", job))

        self.assertEqual((posting.location, posting.country, posting.regions), ("Madrid, Spain", "ES", ("es",)))

    def test_recruitee(self):
        job = {"id": 1, "title": "Backend Developer", "company_name": "Acme", "location": "Zürich, Switzerland",
               "country_code": "CH", "careers_url": "https://jobs.acme.ch/o/dev",
               "description": "<p>Go</p>", "requirements": "<p>PostgreSQL</p>"}  # fmt: skip

        posting = jobs.to_posting("recruitee", record("recruitee", job))

        self.assertEqual((posting.url, posting.regions), ("https://jobs.acme.ch/o/dev", ("ch",)))
        self.assertEqual(posting.description.split(), ["Go", "PostgreSQL"])

    def test_personio_lists_every_office(self):
        job = {"id": "42", "name": "Data Engineer", "office": "Zurich", "additionalOffices": ["Madrid"],
               "url": "https://acme.jobs.personio.de/job/42", "descriptions": [{"name": "Tasks", "value": "dbt"}]}  # fmt: skip

        posting = jobs.to_posting("personio", record("personio", job))

        self.assertEqual((posting.location, posting.regions), ("Zurich, Madrid", ("ch", "es")))
        self.assertEqual(posting.description.strip(), "dbt")


if __name__ == "__main__":
    unittest.main()
