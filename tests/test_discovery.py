import unittest

from jobpipe.discovery import discover_from_hn, extract_boards


def hn_record(text: str) -> dict:
    return {"payload": {"comment": {"text": text}}}


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


if __name__ == "__main__":
    unittest.main()
