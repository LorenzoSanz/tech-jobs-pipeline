import unittest
from dataclasses import dataclass

from jobpipe import dedup, employers, jobs, places


@dataclass
class Item:
    posting: jobs.Posting
    first_seen: str
    last_seen: str
    is_open: bool = True


def item(source, source_id, title, company="Acme AG", country="CH", seen="2026-11-01", last="2026-11-10",
         is_open=True, description="text") -> Item:  # fmt: skip
    posting = jobs.Posting(
        source=source, source_id=source_id, title=title, company=company, location=None, country=None, url=None,
        published=None, fetched_at=None, regions=(), description=description,
        place=places.Place(None, (country,) if country else ()),
    )  # fmt: skip
    return Item(posting, f"{seen}T08:00:00+00:00", f"{last}T08:00:00+00:00", is_open)


class KeyTest(unittest.TestCase):
    def test_company(self):
        self.assertEqual(employers.company_key("SOPHiA GENETICS SA"), employers.company_key("sophia-genetics"))
        self.assertEqual(employers.company_key("Proxima Fusion GmbH"), "proxima fusion")
        self.assertEqual(employers.company_key("Acme S.L."), "acme")
        self.assertEqual(employers.company_key("The Company"), "the company")  # nothing left: keep everything

    def test_title(self):
        same = ["Data Engineer (m/w/d)", "Data Engineer - Zürich", "Data Engineer, Remote", "DATA ENGINEER",
                "Data Engineer, FULL:TIME"]  # fmt: skip
        self.assertEqual({dedup.title_key(t) for t in same}, {"data engineer"})
        self.assertNotEqual(dedup.title_key("Senior Data Engineer"), dedup.title_key("Data Engineer"))
        self.assertNotEqual(dedup.title_key("Account Executive (Malaysia Market)"),
                            dedup.title_key("Account Executive (Philippines Market)"))  # fmt: skip


class GroupTest(unittest.TestCase):
    def test_same_job_on_the_board_and_on_adzuna(self):
        items = [
            item("adzuna", "ch:9", "Data Engineer (m/w/d)", company="ACME AG"),
            item("greenhouse", "acme:1", "Data Engineer - Zurich", company="acme"),
            item("greenhouse", "acme:2", "Data Engineer", country="ES"),  # another country
            item("greenhouse", "acme:3", "Senior Data Engineer"),  # another title
        ]

        groups = dedup.group(items)

        self.assertEqual(groups[0], ("greenhouse:acme:1", 1))  # the employer's board stands for the job
        self.assertEqual(groups[1], ("greenhouse:acme:1", 0))
        self.assertEqual(groups[2], ("greenhouse:acme:2", 0))
        self.assertEqual(groups[3], ("greenhouse:acme:3", 0))

    def test_big_tech_names_are_one_company(self):
        items = [
            item("adzuna", "ch:1", "Software Engineer III", company="Google Switzerland GmbH"),
            item("greenhouse", "x:1", "Software Engineer III, Google Cloud", company="Google"),  # another title
            item("adzuna", "ch:2", "Software Engineer III", company="Google DeepMind"),
        ]

        self.assertEqual([job for job, _ in dedup.group(items)], ["adzuna:ch:1", "greenhouse:x:1", "adzuna:ch:1"])

    def test_an_open_posting_stands_for_the_job(self):
        items = [item("greenhouse", "acme:1", "SRE", is_open=False), item("adzuna", "ch:1", "SRE")]

        self.assertEqual(dedup.group(items), [("adzuna:ch:1", 1), ("adzuna:ch:1", 0)])

    def test_the_same_title_months_later_is_a_new_job(self):
        items = [
            item("greenhouse", "acme:1", "SRE", seen="2026-01-01", last="2026-02-01"),
            item("greenhouse", "acme:2", "SRE", seen="2026-02-20", last="2026-03-01"),  # within GAP: same job
            item("greenhouse", "acme:3", "SRE", seen="2026-09-01", last="2026-10-01"),
        ]

        self.assertEqual([job for job, _ in dedup.group(items)],
                         ["greenhouse:acme:1", "greenhouse:acme:1", "greenhouse:acme:3"])  # fmt: skip

    def test_hn_and_postings_without_company_are_never_merged(self):
        items = [item("hn", "1", "Acme | Engineer"), item("hn", "2", "Acme | Engineer"),
                 item("lever", "x:1", "Engineer", company=None), item("lever", "x:2", "Engineer", company=None)]  # fmt: skip

        self.assertEqual([rank for _, rank in dedup.group(items)], [0, 0, 0, 0])


if __name__ == "__main__":
    unittest.main()
