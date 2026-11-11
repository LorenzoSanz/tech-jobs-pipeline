import unittest
import urllib.parse

from jobpipe.sources import levelsfyi
from tests.fakes import FakeTransport, fast_client

LOCATION_ROW = {"locationName": "Zurich Area", "locationSlug": "zurich-area", "p10": 1, "p25": 2,
                "p50": 3, "p75": 4, "p90": 5, "sampleSize": 50}  # fmt: skip


class LevelsFyiTest(unittest.TestCase):
    def test_collects_location_percentiles_then_experience_buckets(self):
        transport = FakeTransport()
        transport.add(body=[LOCATION_ROW])
        transport.add(body=[{"yoeRange": "5-7", "p25": 1, "p50": 2, "p75": 3, "sampleSize": 9}])
        query = levelsfyi.BenchmarkQuery(locations=("zurich-area",), focus_tags=("backend",))

        items = list(levelsfyi.benchmarks(fast_client(transport), "secret", query))

        self.assertEqual([i.payload["kind"] for i in items], ["location_percentiles", "by_experience"])
        self.assertEqual(items[1].source_id, "software-engineer:backend:total_compensation:yoe:zurich-area:5-7")
        first = transport.requests[0]
        self.assertTrue(first.full_url.startswith(f"{levelsfyi.API}/benchmark/software-engineer/locations/compare?"))
        self.assertEqual(first.get_header("X-api-key"), "secret")
        query_params = urllib.parse.parse_qs(urllib.parse.urlsplit(first.full_url).query)
        self.assertEqual(query_params["compareToLocations"], ["zurich-area"])
        self.assertEqual(query_params["focusTagSlugs"], ["backend"])

    def test_compares_at_most_seven_locations_per_call(self):
        transport = FakeTransport()
        transport.add(body=[])
        transport.add(body=[])
        for _ in range(9):
            transport.add(body=[])
        query = levelsfyi.BenchmarkQuery(locations=tuple(f"loc-{i}" for i in range(9)))

        list(levelsfyi.benchmarks(fast_client(transport), "k", query))

        compares = [u for u in transport.urls() if "/locations/compare" in u]
        self.assertEqual(len(compares), 2)

    def test_api_key_stays_out_of_urls_and_payloads(self):
        transport = FakeTransport()
        transport.add(body=[LOCATION_ROW])
        transport.add(body=[])
        query = levelsfyi.BenchmarkQuery(locations=("zurich-area",))

        [item] = levelsfyi.benchmarks(fast_client(transport), "secret", query)

        self.assertNotIn("secret", repr(item.payload))
        self.assertTrue(all("secret" not in url for url in transport.urls()))


if __name__ == "__main__":
    unittest.main()
