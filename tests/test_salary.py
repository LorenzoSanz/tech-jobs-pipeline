import re
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from jobpipe import salary
from jobpipe.bronze import BronzeWriter, RawItem


def write(root: Path, source: str, items: list[RawItem], day: int = 10) -> None:
    clock = lambda: datetime(2026, 11, day, 8, tzinfo=UTC)  # noqa: E731
    BronzeWriter(root, clock=clock).write(source, items)


def ashby_job(**overrides) -> dict:
    job = {
        "id": "a1",
        "title": "Backend Engineer",
        "location": "Zurich",
        "address": {"postalAddress": {"addressCountry": "Switzerland"}},
        "jobUrl": "https://jobs.ashbyhq.com/acme/a1",
        "compensation": {
            "compensationTiers": [],
            "summaryComponents": [
                {"compensationType": "Salary", "currencyCode": "CHF", "interval": "1 YEAR",
                 "minValue": 120000, "maxValue": 150000},
                {"compensationType": "EquityPercentage", "currencyCode": None, "interval": "NONE"},
            ],
        },
    }  # fmt: skip
    job.update(overrides)
    return job


class RangesInTextTest(unittest.TestCase):
    def test_reads_common_ways_of_writing_a_range(self):
        cases = {
            "Pay: $120k–$170k + equity": ("USD", 120_000, 170_000),
            "CHF 110'000 - 140'000 per year": ("CHF", 110_000, 140_000),
            "€60.000 - €80.000": ("EUR", 60_000, 80_000),
            "salary 70k - 100k EUR, on-site": ("EUR", 70_000, 100_000),
            "$150–200k base": ("USD", 150_000, 200_000),
            "&lt;p&gt;£80,000 &amp;mdash; £95,000&lt;/p&gt;": ("GBP", 80_000, 95_000),
        }
        for text, (currency, low, high) in cases.items():
            with self.subTest(text=text):
                [(got_currency, got_low, got_high, period)] = salary.ranges_in_text(text)
                self.assertEqual((got_currency, got_low, got_high, period), (currency, low, high, "year"))

    def test_annualises_hourly_and_monthly_ranges(self):
        [hourly] = salary.ranges_in_text("$70-150/hr")
        [monthly] = salary.ranges_in_text("$3,500-$5,000 USD/month")
        self.assertEqual(hourly[1:], (70 * 2080, 150 * 2080, "hour"))
        self.assertEqual(monthly[1:], (42_000, 60_000, "month"))

    def test_ignores_ranges_without_currency_or_implausible_ones(self):
        for text in ["5-10 years of experience", "teams of 10-20 people", "raised $5-10M", "$1 - $2"]:
            with self.subTest(text=text):
                self.assertEqual(salary.ranges_in_text(text), [])


class ExtractorsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_ashby_structured_compensation(self):
        write(self.root, "ashby", [RawItem("acme:a1", {"board": "acme", "job": ashby_job()})])

        [posted] = salary.posted_salaries(self.root, ["ashby"])

        self.assertEqual((posted.currency, posted.min_annual, posted.max_annual), ("CHF", 120_000, 150_000))
        self.assertEqual(posted.company, "acme")
        self.assertEqual(posted.regions(), {"ch"})

    def test_ashby_market_tiers_are_kept_apart(self):
        tiers = [
            {"title": "Spain, Poland", "components": [
                {"compensationType": "Salary", "currencyCode": "EUR", "interval": "1 YEAR",
                 "minValue": 60000, "maxValue": 75000}]},
            {"title": "UK, Germany", "components": [
                {"compensationType": "Salary", "currencyCode": "EUR", "interval": "1 YEAR",
                 "minValue": 80000, "maxValue": 95000}]},
        ]  # fmt: skip
        job = ashby_job(compensation={"compensationTiers": tiers, "summaryComponents": []})
        write(self.root, "ashby", [RawItem("acme:a1", {"board": "acme", "job": job})])

        posted = list(salary.posted_salaries(self.root, ["ashby"]))

        self.assertEqual([(p.tier, p.min_annual) for p in posted], [("Spain, Poland", 60_000), ("UK, Germany", 80_000)])

    def test_lever_salary_range_and_text_fallback(self):
        structured = {
            "id": "l1", "text": "Data Engineer", "country": "ES", "categories": {"location": "Madrid"},
            "salaryRange": {"currency": "EUR", "interval": "per-month-salary", "min": 4000, "max": 5000},
        }  # fmt: skip
        prose = {"id": "l2", "text": "SRE", "country": "CH", "categories": {"location": "Zürich"},
                 "descriptionPlain": "We pay CHF 130k - 160k."}  # fmt: skip
        write(self.root, "lever", [
            RawItem("acme:l1", {"board": "acme", "job": structured}),
            RawItem("acme:l2", {"board": "acme", "job": prose}),
        ])  # fmt: skip

        by_title = {p.title: p for p in salary.posted_salaries(self.root, ["lever"])}

        self.assertEqual((by_title["Data Engineer"].min_annual, by_title["Data Engineer"].period), (48_000, "month"))
        self.assertEqual(by_title["Data Engineer"].regions(), {"es"})
        self.assertEqual((by_title["SRE"].currency, by_title["SRE"].max_annual), ("CHF", 160_000))
        self.assertEqual(by_title["SRE"].regions(), {"ch"})

    def test_recruitee_structured_salary_and_text_fallback(self):
        structured = {"id": 1, "title": "Backend Developer", "location": "Zürich", "country_code": "CH",
                      "salary": {"min": "8000", "max": "10000", "period": "month", "currency": "CHF"}}
        prose = {"id": 2, "title": "Data Engineer", "location": "Madrid", "country_code": "ES",
                 "salary": {"min": None, "max": None, "period": None, "currency": None},
                 "description": "<p>Salary: €50k - €65k</p>"}  # fmt: skip
        write(self.root, "recruitee", [
            RawItem("acme:1", {"board": "acme", "job": structured}),
            RawItem("acme:2", {"board": "acme", "job": prose}),
        ])  # fmt: skip

        by_title = {p.title: p for p in salary.posted_salaries(self.root, ["recruitee"])}

        self.assertEqual((by_title["Backend Developer"].min_annual, by_title["Backend Developer"].currency), (96_000, "CHF"))
        self.assertEqual(by_title["Backend Developer"].regions(), {"ch"})
        self.assertEqual((by_title["Data Engineer"].max_annual, by_title["Data Engineer"].currency), (65_000, "EUR"))

    def test_adzuna_marks_predicted_salaries(self):
        job = {"id": "1", "title": "DevOps", "salary_min": 100000, "salary_max": 120000,
               "salary_is_predicted": "1", "location": {"display_name": "Bern"}}  # fmt: skip
        write(self.root, "adzuna", [RawItem("ch:1", {"country": "ch", "job": job})])

        everything = list(salary.posted_salaries(self.root, ["adzuna"]))
        stated = salary.filter_salaries(everything)

        self.assertEqual(everything[0].currency, "CHF")
        self.assertTrue(everything[0].predicted)
        self.assertEqual(stated, [])

    def test_only_the_latest_snapshot_of_a_posting_counts(self):
        old = ashby_job()
        new = ashby_job(compensation={"summaryComponents": [
            {"compensationType": "Salary", "currencyCode": "CHF", "interval": "1 YEAR",
             "minValue": 130000, "maxValue": 160000}]})  # fmt: skip
        write(self.root, "ashby", [RawItem("acme:a1", {"board": "acme", "job": old})], day=1)
        write(self.root, "ashby", [RawItem("acme:a1", {"board": "acme", "job": new})], day=9)

        [posted] = salary.posted_salaries(self.root, ["ashby"])

        self.assertEqual(posted.min_annual, 130_000)

    def test_hn_ranges_link_back_to_the_comment(self):
        comment = {"id": 42, "author": "x", "text": "Acme | Barcelona | Backend<p>€55k - €70k"}
        write(self.root, "hn", [RawItem("42", {"comment": comment})])

        [posted] = salary.posted_salaries(self.root, ["hn"])

        self.assertEqual(posted.company, "Acme")
        self.assertEqual(posted.regions(), {"es"})
        self.assertEqual(posted.url, "https://news.ycombinator.com/item?id=42")


class SummaryTest(unittest.TestCase):
    def posted(self, low: float, high: float, currency: str = "CHF", title: str = "Backend") -> salary.PostedSalary:
        return salary.PostedSalary("ashby", f"x:{low}", "acme", title, "Zurich", "Switzerland", currency,
                                   low, high, "year", False, None, None, None)  # fmt: skip

    def test_spreads_per_currency_never_mixed(self):
        items = [self.posted(100_000, 120_000), self.posted(120_000, 140_000), self.posted(140_000, 160_000),
                 self.posted(50_000, 60_000, currency="EUR")]  # fmt: skip

        summary = salary.summarise(items)

        self.assertEqual(list(summary), ["CHF", "EUR"])
        self.assertEqual(summary["CHF"]["midpoint"].p50, 130_000)
        self.assertEqual(summary["EUR"]["max"], salary.Spread(1, 60_000, 60_000, 60_000))

    def test_filters_by_region_and_title(self):
        items = [self.posted(1e5, 1.2e5, title="Data Engineer"), self.posted(1e5, 1.2e5, title="Designer")]

        kept = salary.filter_salaries(items, regions=["ch"], title=re.compile("engineer", re.I))
        elsewhere = salary.filter_salaries(items, regions=["es"])

        self.assertEqual([p.title for p in kept], ["Data Engineer"])
        self.assertEqual(elsewhere, [])

    def test_histogram_median(self):
        self.assertEqual(salary.histogram_median({"80000": "5", "60000": "3", "100000": "2"}), (80_000, 10))
        self.assertIsNone(salary.histogram_median({}))


if __name__ == "__main__":
    unittest.main()
