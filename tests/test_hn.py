import unittest
from datetime import date, datetime, timezone

from jobpipe.sources import hn
from tests.fakes import FakeTransport, fast_client


def ts(year: int, month: int, day: int) -> int:
    return int(datetime(year, month, day, 16, tzinfo=timezone.utc).timestamp())


def story_hit(object_id: str, title: str, created: int) -> dict:
    return {"objectID": object_id, "title": title, "created_at_i": created}


SEARCH_PAGE = {
    "nbPages": 1,
    "hits": [
        story_hit("300", "Ask HN: Who is hiring? (November 2026)", ts(2026, 11, 2)),
        story_hit("301", "Ask HN: Freelancer? Seeking freelancer? (November 2026)", ts(2026, 11, 2)),
        story_hit("302", "Ask HN: Who wants to be hired? (November 2026)", ts(2026, 11, 2)),
        story_hit("200", "Ask HN: Who is hiring? (October 2026)", ts(2026, 10, 1)),
        story_hit("100", "Ask HN: Who is hiring? (September 2026)", ts(2026, 9, 1)),
    ],
}


class FindHiringThreadsTest(unittest.TestCase):
    def test_keeps_only_who_is_hiring_threads(self):
        transport = FakeTransport()
        transport.add(body=SEARCH_PAGE)

        threads = hn.find_hiring_threads(fast_client(transport))

        self.assertEqual([t.id for t in threads], [300, 200, 100])
        self.assertEqual(transport.query(0)["tags"], "story,author_whoishiring")

    def test_stops_at_the_since_date(self):
        transport = FakeTransport()
        transport.add(body=SEARCH_PAGE)

        threads = hn.find_hiring_threads(fast_client(transport), since=date(2026, 10, 1))

        self.assertEqual([t.id for t in threads], [300, 200])

    def test_follows_pagination(self):
        transport = FakeTransport()
        transport.add(body={"nbPages": 2, "hits": SEARCH_PAGE["hits"][:1]})
        transport.add(body={"nbPages": 2, "hits": SEARCH_PAGE["hits"][3:]})

        threads = hn.find_hiring_threads(fast_client(transport))

        self.assertEqual([t.id for t in threads], [300, 200, 100])
        self.assertEqual(transport.query(1)["page"], "1")


class FetchPostingsTest(unittest.TestCase):
    def test_yields_live_top_level_comments_with_their_own_timestamp(self):
        thread = hn.HiringThread(200, "Ask HN: Who is hiring? (October 2026)", datetime(2026, 10, 1, tzinfo=timezone.utc))
        transport = FakeTransport()
        transport.add(
            body={
                "id": 200,
                "children": [
                    {
                        "id": 201,
                        "author": "acme_hr",
                        "created_at_i": ts(2026, 10, 3),
                        "text": "Acme | Backend Engineer | Zurich | ONSITE",
                        "children": [{"id": 205, "author": "curious", "text": "Visa?"}],
                    },
                    {"id": 202, "author": None, "text": None, "children": []},
                ],
            }
        )

        items = list(hn.fetch_postings(fast_client(transport), thread))

        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item.source_id, "201")
        self.assertEqual(item.event_time, datetime(2026, 10, 3, 16, tzinfo=timezone.utc))
        self.assertEqual(item.payload["thread"]["id"], 200)
        self.assertEqual(item.payload["comment"]["text"], "Acme | Backend Engineer | Zurich | ONSITE")
        self.assertNotIn("children", item.payload["comment"])
        self.assertEqual(transport.urls(), ["https://hn.algolia.com/api/v1/items/200"])


class IngestTest(unittest.TestCase):
    def test_processes_threads_oldest_first(self):
        transport = FakeTransport()
        transport.add(body={"nbPages": 1, "hits": SEARCH_PAGE["hits"][3:]})
        transport.add(body={"children": []})
        transport.add(body={"children": []})

        list(hn.ingest(fast_client(transport)))

        self.assertEqual(
            transport.urls()[1:],
            ["https://hn.algolia.com/api/v1/items/100", "https://hn.algolia.com/api/v1/items/200"],
        )


if __name__ == "__main__":
    unittest.main()
