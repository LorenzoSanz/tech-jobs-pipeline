"""Property-based tests: rules that hold for any input, checked on generated ones.

The parsers here read free text written by thousands of employers, so the
example-based tests cannot cover what they will meet. Hypothesis generates
titles, places and salary texts and shrinks any failure to a minimal case.
"""

import json
import unittest
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

try:
    from hypothesis import given, settings
    from hypothesis import strategies as st
except ImportError:  # a dev dependency: pip install -e .[dev]
    raise unittest.SkipTest("hypothesis is not installed") from None

from jobpipe import bronze, cv, dedup, employers, jobs, match, places, roles, salary, seniority, tech

settings.register_profile("default", deadline=None, max_examples=200)
settings.load_profile("default")

TITLE_WORDS = [
    "Senior", "Sr.", "Junior", "Lead", "Staff", "Principal", "Head of", "Intern", "II", "III", "IV",
    "Data", "Software", "Backend", "Platform", "Machine Learning", "Engineer", "Developer", "Analyst",
    "Manager", "Ingeniero/a", "de", "Datos", "(m/w/d)", "(all genders)", "Remote", "Hybrid", "full_time",
    "Zürich", "Zurich", "Madrid", "Genève", "New York", "-", ",", "/", "|", "&", "Python", "Go", "Java",
    "JavaScript", "C++", "C#", ".NET", "React Native", "Kubernetes", "k8s", "Postgres", "Mid-Market",
]  # fmt: skip
PLACE_WORDS = [
    "Zürich", "Zurich, Switzerland", "Madrid", "Barcelona (HQ)", "Spain", "Germany", "Berlin", "Remote",
    "New York, NY", "London", "Lisbon", "CA", "Europe", "EMEA", "Home office", ";", "|", " / ", " - ", ", ",
]  # fmt: skip
TECH_WORDS = [
    "Python", "PYTHON", "Go", "golang", "Go deep", "C#", ".NET", "dotnet", "C++", "SwiftUI", "PySpark",
    "Big Query", "BigQuery", "Power BI", "Postgres", "PostgreSQL", "MariaDB", "Mongo", "Elastic Search",
    "OpenSearch", "Dynamo DB", "Amazon Web Services", "AWS", "Google Cloud", "GCP", "K8s", "OTel",
    "scikit-learn", "LLMs", "Large Language Model", "React", "React Native", "React.js", "Node.js",
    "Spring Boot", "Spring Framework", "Presto", "Trino", "LİNUX", "lınux", "Kubernetes", "ſql", "Kafka",
    " ", ", ", "/", "-", "\n",
]  # fmt: skip
COMPANY_FORMS = ["", " GmbH", " AG", " S.L.", " SA", " Inc.", " Ltd", " Switzerland GmbH", " EMEA", " Europe"]

BASE = datetime(2026, 1, 1, tzinfo=UTC)

text = st.text(max_size=200)
titles = st.one_of(text, st.lists(st.sampled_from(TITLE_WORDS), max_size=8).map(" ".join))
place_texts = st.one_of(text, st.lists(st.sampled_from(PLACE_WORDS), max_size=6).map("".join))


class TextProperties(unittest.TestCase):
    @given(text)
    def test_fold_is_idempotent(self, value):
        self.assertEqual(places.fold(places.fold(value)), places.fold(value))

    @given(place_texts)
    def test_parsed_countries_are_known_iso_codes(self, location):
        place = places.parse(location)
        self.assertLessEqual(set(place.countries), set(places.COUNTRIES))
        self.assertEqual(len(place.countries), len(set(place.countries)))
        self.assertEqual(place.country, place.countries[0] if place.countries else None)

    @given(titles)
    def test_every_title_gets_a_known_level_and_role(self, title):
        self.assertIn(seniority.seniority_of(title), seniority.ORDER)
        self.assertIn(roles.role_of(title), {family.key for family in roles.ALL})

    @given(titles, st.one_of(st.none(), text))
    def test_technologies_are_catalogued_once_in_catalogue_order(self, title, company):
        found = tech.technologies_in(title, company)
        order = [t.key for t in tech.CATALOGUE]
        self.assertEqual(list(found), sorted(set(found), key=order.index))

    @given(st.lists(st.one_of(st.sampled_from(TECH_WORDS), st.text(max_size=3)), max_size=12).map("".join))
    def test_needles_never_change_what_is_found(self, written):
        every_pattern = tuple(key for key, _, pattern in tech._COMPILED if pattern.search(written))
        self.assertEqual(tech.technologies_in(written), every_pattern)

    @given(titles)
    def test_title_key_is_idempotent(self, title):
        key = dedup.title_key(title)
        self.assertEqual(dedup.title_key(key), key)

    @given(titles)
    def test_title_terms_end_in_a_role(self, title):
        for term in cv.title_terms(title):
            words = term.split()
            self.assertTrue(words[-1] in cv.ROLE_NOUNS or words[0] in cv.ROLE_NOUNS_FIRST, term)


class EmployerProperties(unittest.TestCase):
    names = tuple(names.split("|")[0] for tier in employers.EMPLOYERS.values() for names in tier)

    @given(st.sampled_from(names), st.sampled_from(COMPANY_FORMS))
    def test_big_tech_is_found_under_any_legal_form(self, name, form):
        self.assertEqual(employers.employer_of(name + form).name, name)

    @given(text)
    def test_employer_key_is_idempotent(self, name):
        key = employers.employer_key(name)
        self.assertEqual(employers.employer_key(key), key)


@dataclass
class Item:
    posting: jobs.Posting
    first_seen: str
    last_seen: str
    is_open: bool


@st.composite
def postings(draw):
    """Postings that collide often: few companies, titles, countries and days."""
    items = []
    for n in range(draw(st.integers(0, 12))):
        posting = jobs.Posting(
            source=draw(st.sampled_from(["greenhouse", "adzuna", "hn", "lever"])), source_id=str(n),
            title=draw(st.sampled_from(["Data Engineer", "Data Engineer (m/w/d)", "SRE", ""])),
            company=draw(st.sampled_from(["Acme AG", "acme", "Google Switzerland GmbH", "Google", None])),
            location=None, country=None, url=None, published=None, fetched_at=None, regions=(),
            description=draw(st.sampled_from(["", "text"])),
            place=places.Place(None, draw(st.sampled_from([(), ("CH",), ("ES",), ("CH", "ES")]))),
        )  # fmt: skip
        start = BASE + timedelta(days=draw(st.integers(0, 120)))
        first, last = start.isoformat(), (start + timedelta(days=draw(st.integers(0, 40)))).isoformat()
        items.append(Item(posting, first, last, draw(st.booleans())))
    return items


class DedupProperties(unittest.TestCase):
    @given(postings())
    def test_each_job_has_one_rank_zero_posting_that_names_it(self, items):
        result = dedup.group(items)

        self.assertEqual(len(result), len(items))
        ids = {f"{i.posting.source}:{i.posting.source_id}": i for i in items}
        for job_id in {job for job, _ in result}:
            ranks = sorted(rank for job, rank in result if job == job_id)
            self.assertEqual(ranks, list(range(len(ranks))))  # 0, 1, 2... once each
            rank_zero = next(item for item, (job, rank) in zip(items, result, strict=True) if job == job_id and rank == 0)
            self.assertIs(ids[job_id], rank_zero)  # the job id is its rank 0 posting

    @given(postings(), st.randoms())
    def test_grouping_does_not_depend_on_input_order(self, items, rnd):
        shuffled = list(items)
        rnd.shuffle(shuffled)

        by_item = dict(zip(map(id, items), dedup.group(items), strict=True))
        self.assertEqual([by_item[id(i)] for i in shuffled], dedup.group(shuffled))

    @given(postings())
    def test_hn_postings_are_never_merged(self, items):
        for item, (job, _) in zip(items, dedup.group(items), strict=True):
            if item.posting.source == "hn":
                self.assertEqual(job, f"hn:{item.posting.source_id}")


class NumberProperties(unittest.TestCase):
    @given(st.integers(1, 400), st.integers(0, 400), st.sampled_from(["CHF", "EUR", "€", "$", "£"]),
           st.sampled_from(["k", "000", ""]), st.sampled_from(["", " per month", " per hour", " a year"]))  # fmt: skip
    def test_salary_ranges_are_ordered_and_plausible(self, low, extra, currency, unit, period):
        written = f"Salary: {currency}{low}{unit} - {currency}{low + extra}{unit}{period}. 5-10 years experience."
        for found_currency, low_annual, high_annual, _ in salary.ranges_in_text(written):
            self.assertIn(found_currency, {"CHF", "EUR", "USD", "GBP"})
            self.assertLessEqual(low_annual, high_annual)
            self.assertGreaterEqual(low_annual, salary.MIN_ANNUAL)
            self.assertLessEqual(high_annual, salary.MAX_ANNUAL)

    @given(st.dictionaries(st.text(max_size=5), st.recursive(
        st.none() | st.booleans() | st.integers() | st.text(max_size=10),
        lambda children: st.lists(children, max_size=3) | st.dictionaries(st.text(max_size=5), children, max_size=3),
        max_leaves=10)))  # fmt: skip
    def test_payload_hash_ignores_key_order(self, payload):
        reordered = dict(reversed(list(payload.items())))
        self.assertEqual(json.loads(bronze.canonical_json(payload)), payload)
        self.assertEqual(bronze.payload_hash(reordered), bronze.payload_hash(payload))

    @given(st.lists(st.sampled_from([t.key for t in tech.CATALOGUE]), unique=True, max_size=8),
           st.sets(st.sampled_from([t.key for t in tech.CATALOGUE]), min_size=1, max_size=8))  # fmt: skip
    def test_score_is_the_share_of_known_technologies(self, asked, skills):
        m = match.match(match.Profile(skills=frozenset(skills)), "Engineer", "engineering", ["ch"], asked)
        self.assertEqual(set(m.have) | set(m.missing), set(asked))
        self.assertFalse(set(m.have) & set(m.missing))
        if asked:
            self.assertAlmostEqual(m.score, len(m.have) / len(asked))
            self.assertTrue(0 < m.rank < 1)
        else:
            self.assertEqual((m.score, m.rank), (None, -1.0))


if __name__ == "__main__":
    unittest.main()
