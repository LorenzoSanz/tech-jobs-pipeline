import unittest

from datetime import date

from jobpipe.discovery import discover_from_hn, extract_boards, location_pattern


def hn_record(text: str, event_time: str = "2025-01-01T00:00:00+00:00") -> dict:
    return {"event_time": event_time, "payload": {"comment": {"text": text}}}


class ExtractBoardsTest(unittest.TestCase):
    def test_finds_boards_in_html_escaped_hn_text(self):
        text = (
            'Acme | Zurich | <a href="https:&#x2F;&#x2F;jobs.lever.co&#x2F;acme&#x2F;4f1c">apply</a>'
            " or https:&#x2F;&#x2F;boards.greenhouse.io&#x2F;acmecorp&#x2F;jobs&#x2F;123"
            " or https:&#x2F;&#x2F;jobs.ashbyhq.com&#x2F;Acme%20AI"
        )

        self.assertEqual(
            extract_boards(text),
            {"lever": {"acme"}, "greenhouse": {"acmecorp"}, "ashby": {"Acme AI"}},
        )

    def test_reads_the_token_of_embedded_greenhouse_boards(self):
        text = "https://boards.greenhouse.io/embed/job_board?for=widgets"

        self.assertEqual(extract_boards(text), {"greenhouse": {"widgets"}})

    def test_ignores_eu_hosted_boards_until_supported(self):
        text = "https://job-boards.eu.greenhouse.io/juaai and https://jobs.eu.lever.co/acme"

        self.assertEqual(extract_boards(text), {})

    def test_drops_sentence_punctuation(self):
        self.assertEqual(extract_boards("See jobs.lever.co/acme."), {"lever": {"acme"}})


class DiscoverFromHnTest(unittest.TestCase):
    def test_counts_only_postings_that_mention_switzerland(self):
        records = [
            hn_record("Acme | Zürich, Switzerland | https://jobs.lever.co/acme"),
            hn_record("Acme | Basel | https://jobs.lever.co/acme"),
            hn_record("Other | Berlin | https://jobs.lever.co/other"),
        ]

        counts = discover_from_hn(records)

        self.assertEqual(dict(counts["lever"]), {"acme": 2})
        self.assertEqual(dict(counts["greenhouse"]), {})

    def test_regions_can_be_combined(self):
        records = [
            hn_record("Uno | Madrid, España | https://jobs.lever.co/uno"),
            hn_record("Zwei | Berlin | https://jobs.lever.co/zwei"),
            hn_record("Drei | Zurich | https://jobs.lever.co/drei"),
        ]

        counts = discover_from_hn(records, location_pattern(["es", "eu"]))

        self.assertEqual(set(counts["lever"]), {"uno", "zwei"})

    def test_rejects_unknown_regions(self):
        with self.assertRaises(ValueError):
            location_pattern(["mars"])


if __name__ == "__main__":
    unittest.main()

    def test_since_ignores_older_postings(self):
        records = [
            hn_record("Old | Zurich | https://jobs.lever.co/old", "2014-03-01T10:00:00+00:00"),
            hn_record("New | Zurich | https://jobs.lever.co/new", "2024-01-01T00:00:00+00:00"),
        ]

        counts = discover_from_hn(records, since=date(2024, 1, 1))

        self.assertEqual(dict(counts["lever"]), {"new": 1})
