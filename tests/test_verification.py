import tomllib
import unittest

from jobpipe.discovery import location_pattern
from jobpipe.http import HttpClient
from jobpipe.verification import BoardCheck, job_locations, render_toml, verify
from tests.fakes import FakeTransport


def client(transport: FakeTransport) -> HttpClient:
    return HttpClient(transport=transport, sleep=lambda _: None, max_attempts=1)


class JobLocationsTest(unittest.TestCase):
    def test_reads_every_location_field_of_each_ats(self):
        self.assertEqual(
            job_locations("greenhouse", {"location": {"name": "Zurich"}, "offices": [{"name": "Basel", "location": None}]}),
            ["Zurich", "Basel"],
        )
        self.assertEqual(
            job_locations("lever", {"categories": {"location": "Remote", "allLocations": ["Madrid"]}, "country": "ES"}),
            ["Remote", "Madrid", "ES"],
        )
        self.assertEqual(
            job_locations("ashby", {"location": "Berlin", "secondaryLocations": [{"location": "Zug"}]}),
            ["Berlin", "Zug"],
        )


class VerifyTest(unittest.TestCase):
    def test_keeps_boards_with_regional_jobs_and_drops_the_rest(self):
        transport = FakeTransport()
        transport.add(body={"jobs": [
            {"id": 1, "location": {"name": "Zürich, Switzerland"}},
            {"id": 2, "location": {"name": "New York"}},
        ]})
        transport.add(body={"jobs": [{"id": 3, "location": {"name": "Austin"}}]})
        transport.add(status=404, body={"error": "not found"})

        checks = verify(client(transport), {"greenhouse": ["acme", "usonly", "gone"]}, location_pattern(["ch"]))

        self.assertEqual(
            [(c.board, c.regional_jobs, c.total_jobs, c.keep) for c in checks],
            [("acme", 1, 2, True), ("usonly", 0, 1, False), ("gone", 0, 0, False)],
        )

    def test_renders_a_loadable_boards_file(self):
        checks = [
            BoardCheck("lever", "small", 3, 1),
            BoardCheck("lever", "big", 9, 5),
            BoardCheck("ashby", "gone", 0, 0, "404"),
        ]

        text = render_toml(checks)

        self.assertEqual(tomllib.loads(text)["lever"]["boards"], ["big", "small"])
        self.assertEqual(tomllib.loads(text)["ashby"]["boards"], [])
        self.assertIn("ashby/gone: unreachable", text)
