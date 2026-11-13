import json
import os
import re
import tempfile
import unittest
from datetime import UTC, date, datetime
from pathlib import Path

from jobpipe import match, warehouse
from jobpipe.bronze import BronzeWriter, RawItem

DASHBOARDS = Path(__file__).resolve().parent.parent / "grafana" / "dashboards"
DASHBOARD_FILES = sorted(DASHBOARDS.glob("*/*.json"))
TEST_DSN = os.environ.get("JOBPIPE_TEST_DATABASE_URL")
PROFILE = match.Profile(skills=frozenset({"python", "postgresql"}), roles=frozenset({"backend", "data"}),
                        regions=frozenset({"ch", "es"}))  # fmt: skip


def clock(day: int, hour: int = 8):
    return lambda: datetime(2026, 11, day, hour, tzinfo=UTC)


def ashby_job(job_id: str = "a1", low: int = 120000, title: str = "Backend Engineer") -> dict:
    return {
        "id": job_id, "title": title, "location": "Zurich", "publishedAt": "2026-10-01T00:00:00Z",
        "address": {"postalAddress": {"addressCountry": "Switzerland"}},
        "jobUrl": f"https://jobs.ashbyhq.com/acme/{job_id}",
        "descriptionPlain": "Python and Kafka services on PostgreSQL.",
        "compensation": {"summaryComponents": [
            {"compensationType": "Salary", "currencyCode": "CHF", "interval": "1 YEAR",
             "minValue": low, "maxValue": low + 30000}]},
    }  # fmt: skip


def write_fixture(root: Path) -> None:
    """Two snapshots of a Swiss board (a2 is gone from the second), one Spanish HN posting, and benchmarks."""
    BronzeWriter(root, clock(1)).write("ashby", [
        RawItem("acme:a1", {"board": "acme", "job": ashby_job(low=110000)}),
        RawItem("acme:a2", {"board": "acme", "job": ashby_job("a2", title="Senior Backend Engineer")}),
    ])  # fmt: skip
    BronzeWriter(root, clock(9)).write("ashby", [RawItem("acme:a1", {"board": "acme", "job": ashby_job()})])
    # a1 again, on Adzuna: the same job, so it must count once
    adzuna_job = {"id": "9", "title": "Backend Engineer (m/w/d)", "company": {"display_name": "Acme AG"},
                  "location": {"display_name": "Zürich"}, "redirect_url": "https://www.adzuna.ch/details/9",
                  "salary_min": 100000, "salary_max": 110000, "salary_is_predicted": "0"}  # fmt: skip
    BronzeWriter(root, clock(9)).write(
        "adzuna", [RawItem("ch:9", {"country": "ch", "job": adzuna_job}, datetime(2026, 11, 5, tzinfo=UTC))]
    )
    comment = {"id": 7, "author": "x", "text": "Acme | Madrid | Data Engineer<p>€55k - €70k<p>Python and dbt", "created_at": None}
    BronzeWriter(root, clock(9)).write(
        "hn", [RawItem("7", {"comment": comment}, datetime(2026, 11, 2, tzinfo=UTC))]
    )
    BronzeWriter(root, clock(9)).write("adzuna_salary", [
        RawItem("ch:histogram:it-jobs:data engineer", {"kind": "histogram", "country": "ch", "what": "data engineer",
                "category": "it-jobs", "histogram": {"100000": "4", "120000": "2"}}),
        RawItem("ch:history:it-jobs", {"kind": "history", "country": "ch", "category": "it-jobs",
                "month": {"2026-09": 101000.5, "2026-10": 102000}}),
    ])  # fmt: skip
    BronzeWriter(root, clock(9)).write("levelsfyi", [
        RawItem("x", {"kind": "location_percentiles", "job_family": "software-engineer",
                      "salary_type": "total_compensation", "focus_tags": [], "currency": "USD",
                      "data": {"locationName": "Zurich", "locationSlug": "zurich-area", "p10": 1, "p25": 2,
                               "p50": 3, "p75": 4, "p90": 5, "sampleSize": 9}}),
    ])  # fmt: skip


class BuildTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        write_fixture(self.root)
        self.tables = warehouse.build(self.root, PROFILE)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_postings_keep_newest_snapshot_and_lifetime(self):
        rows = {row[1]: dict(zip(warehouse.POSTING_COLUMNS, row, strict=True)) for row in self.tables.postings}
        swiss = rows["acme:a1"]

        self.assertEqual(swiss["first_seen"], datetime(2026, 11, 1, 8, tzinfo=UTC))
        self.assertEqual(swiss["last_seen"], datetime(2026, 11, 9, 8, tzinfo=UTC))
        self.assertEqual(swiss["snapshots"], 2)
        self.assertEqual(swiss["regions"], ["ch"])
        self.assertEqual(swiss["role"], "backend")
        self.assertEqual(swiss["technologies"], ["python", "kafka", "postgresql"])
        self.assertEqual(rows["7"]["regions"], ["es"])
        self.assertEqual(rows["7"]["technologies"], ["python", "dbt"])

    def test_open_means_in_the_newest_snapshot_of_its_board(self):
        rows = {row[1]: dict(zip(warehouse.POSTING_COLUMNS, row, strict=True)) for row in self.tables.postings}

        self.assertEqual({key: row["is_open"] for key, row in rows.items()},
                         {"acme:a1": True, "acme:a2": False, "7": True, "ch:9": True})  # fmt: skip

    def test_places_seniority_and_jobs(self):
        rows = {row[1]: dict(zip(warehouse.POSTING_COLUMNS, row, strict=True)) for row in self.tables.postings}

        self.assertEqual({k: (r["city"], r["country"], r["countries"]) for k, r in rows.items()}, {
            "acme:a1": ("Zurich", "CH", ["CH"]), "acme:a2": ("Zurich", "CH", ["CH"]),
            "ch:9": ("Zurich", "CH", ["CH"]), "7": ("Madrid", "ES", ["ES"]),
        })  # fmt: skip
        self.assertEqual((rows["acme:a1"]["seniority"], rows["acme:a2"]["seniority"]), ("unspecified", "senior"))
        self.assertEqual({k: (r["job_id"], r["job_rank"]) for k, r in rows.items()}, {
            "acme:a1": ("ashby:acme:a1", 0), "ch:9": ("ashby:acme:a1", 1),
            "acme:a2": ("ashby:acme:a2", 0), "7": ("hn:7", 0),
        })  # fmt: skip

    def test_matches_against_the_profile(self):
        matches = {row[1]: dict(zip(warehouse.MATCH_COLUMNS, row, strict=True)) for row in self.tables.posting_matches}

        self.assertAlmostEqual(matches["acme:a1"]["score"], 2 / 3)
        self.assertEqual(matches["acme:a1"]["missing"], ["kafka"])
        self.assertEqual((matches["7"]["fits"], matches["7"]["have"]), (True, ["python"]))
        self.assertEqual(warehouse.build(self.root).posting_matches, [])

    def test_salaries_come_from_the_newest_snapshot(self):
        by_id = {row[1]: dict(zip(warehouse.SALARY_COLUMNS, row, strict=True)) for row in self.tables.posted_salaries}

        self.assertEqual((by_id["acme:a1"]["currency"], by_id["acme:a1"]["min_annual"]), ("CHF", 120000))
        self.assertEqual((by_id["7"]["currency"], by_id["7"]["max_annual"]), ("EUR", 70000))

    def test_benchmarks_and_runs(self):
        self.assertEqual(sorted(r[3] for r in self.tables.adzuna_salary_histogram), [100000, 120000])
        self.assertEqual([r[2] for r in self.tables.adzuna_salary_history], [date(2026, 9, 1), date(2026, 10, 1)])
        self.assertEqual(self.tables.levelsfyi_benchmarks[0][3], "zurich-area")
        self.assertEqual(sorted((r[0], r[3]) for r in self.tables.ingest_runs),
                         [("adzuna", 1), ("adzuna_salary", 2), ("ashby", 1), ("ashby", 2), ("hn", 1),
                          ("levelsfyi", 1)])  # fmt: skip

    def test_write_explains_a_missing_driver(self):
        try:
            import psycopg  # noqa: F401
        except ImportError:
            with self.assertRaisesRegex(RuntimeError, "pip install"):
                warehouse.write("postgresql://nowhere/db", self.tables)
        else:
            self.skipTest("psycopg is installed")


def panel_name(panel: dict) -> str:
    """Title, or the name shown inside a KPI card, which has no header."""
    return panel["title"] or panel["fieldConfig"]["defaults"].get("displayName", "")


def panel_sql(dashboard: dict) -> list[tuple[str, str]]:
    """Every panel and variable query, with Grafana's macros and variables filled in."""
    queries = [(panel_name(p), t["rawSql"]) for p in dashboard["panels"] for t in p.get("targets", [])]
    queries += [(f"variable {v['name']}", v["query"]) for v in dashboard["templating"]["list"] if v["type"] == "query"]
    values = {
        "region": "'ch','es','eu','other'", "currency:sqlstring": "'CHF'", "role": "'__all'", "seniority": "'__all'",
        "tier": "'faang','big_tech','other'",
        "company": "'Acme','acme'", "predicted:raw": "false", "offer:sqlstring": "'100000'",
        "adzuna:sqlstring": "'ch | data engineer'", "with_salary:raw": "true", "technology": "'python','dbt'",
        "min_match:raw": "0", "new:raw": "36500",
    }  # fmt: skip
    filled = []
    for title, sql in queries:
        sql = re.sub(r"\$__timeFilter\((.+?)\)(?=\s*(AND|ORDER|GROUP|$|\n))",
                     r"(\1 BETWEEN now() - interval '20 years' AND now())", sql)  # fmt: skip
        for name, value in values.items():
            sql = sql.replace("${" + name + "}", value).replace("$" + name, value)
        filled.append((title, sql))
    return filled


@unittest.skipUnless(TEST_DSN, "set JOBPIPE_TEST_DATABASE_URL to run against PostgreSQL")
class PostgresTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import psycopg

        cls.psycopg = psycopg
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        write_fixture(root)
        cls.counts = warehouse.write(TEST_DSN, warehouse.build(root, PROFILE))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def query(self, sql: str):
        with self.psycopg.connect(TEST_DSN) as conn:
            return conn.execute(sql).fetchall()

    def test_load_is_repeatable(self):
        root = Path(self.tmp.name)
        warehouse.write(TEST_DSN, warehouse.build(root, PROFILE))

        self.assertEqual(self.query("SELECT count(*) FROM silver.postings"), [(4,)])
        self.assertEqual(self.query("SELECT count(*) FROM gold.jobs"), [(3,)])
        self.assertEqual(self.query("SELECT count(*) FROM silver.load_log"), [(1,)])

    def test_gold_views(self):
        regions = dict(self.query("SELECT source_id, region FROM gold.job_regions"))
        midpoint = self.query("SELECT midpoint FROM gold.salaries WHERE source_id = 'acme:a1'")
        salary_sources = self.query("SELECT DISTINCT source FROM gold.salaries ORDER BY 1")
        job = self.query("SELECT postings, sources, place FROM gold.jobs WHERE source_id = 'acme:a1'")
        feed = self.query("SELECT source_id FROM gold.feed ORDER BY rank DESC")
        demand = self.query("SELECT technology, count(*) FROM gold.posting_technologies GROUP BY 1 ORDER BY 1")

        self.assertEqual(regions, {"acme:a1": "ch", "acme:a2": "ch", "7": "es"})
        self.assertEqual(feed, [("acme:a1",), ("7",)])  # a2 is closed; 2 of 3 known ranks above 1 of 2
        self.assertEqual(demand, [("dbt", 1), ("kafka", 2), ("postgresql", 2), ("python", 3)])
        self.assertEqual(float(midpoint[0][0]), 135000)
        self.assertEqual(salary_sources, [("ashby",), ("hn",)])  # Adzuna's copy of a1 is not counted again
        self.assertEqual(job, [(2, ["adzuna", "ashby"], "Zurich · CH")])

    def test_every_dashboard_query_runs(self):
        for path in DASHBOARD_FILES:
            dashboard = json.loads(path.read_text(encoding="utf-8"))
            for title, sql in panel_sql(dashboard):
                with self.subTest(dashboard=f"{path.parent.name}/{path.name}", panel=title):
                    self.assertNotIn("$", re.sub(r"\$\$", "", sql), "unfilled Grafana variable")
                    self.query(sql)

    def test_offer_percentile_on_the_salary_dashboard(self):
        for lang, title in [("en", "Your offer beats"), ("es", "Tu oferta supera al")]:
            dashboard = json.loads((DASHBOARDS / lang / "salaries.json").read_text(encoding="utf-8"))
            [(_, sql)] = [q for q in panel_sql(dashboard) if q[0] == title]

            self.assertEqual(float(self.query(sql)[0][0]), 0.0)  # 100k is below the CHF 120-150k posting

    def test_feed_dashboard_lists_open_matches_with_labels(self):
        dashboard = json.loads((DASHBOARDS / "en" / "feed.json").read_text(encoding="utf-8"))
        [(_, sql)] = [q for q in panel_sql(dashboard) if q[0] == "Click the title to open the posting"]

        rows = self.query(sql)
        self.assertEqual([(r[0], r[1], r[3], r[4], r[5], r[6]) for r in rows],
                         [(67, "Backend Engineer", "Zurich · CH", "Not stated", "Python, PostgreSQL", "Kafka"),
                          (50, rows[1][1], "Madrid · ES", "Not stated", "Python", "dbt")])  # fmt: skip

    def test_role_labels_follow_the_language(self):
        for lang, data in [("en", "Data"), ("es", "Datos")]:
            dashboard = json.loads((DASHBOARDS / lang / "market.json").read_text(encoding="utf-8"))
            [(_, sql)] = [q for q in panel_sql(dashboard) if q[0] == "variable role"]

            self.assertEqual(sorted(self.query(sql)), [("backend", "Backend"), ("data", data)])


class DashboardFilesTest(unittest.TestCase):
    def test_dashboards_are_valid_and_use_the_provisioned_datasource(self):
        uids = set()
        for path in DASHBOARD_FILES:
            dashboard = json.loads(path.read_text(encoding="utf-8"))
            uids.add(dashboard["uid"])
            for panel in dashboard["panels"]:
                if panel["type"] == "row":
                    continue
                self.assertEqual(panel["datasource"]["uid"], "jobpipe-pg", f"{path}: {panel_name(panel)}")
        names = {"jobpipe-feed", "jobpipe-salaries", "jobpipe-market", "jobpipe-pipeline"}
        self.assertEqual(uids, names | {f"{uid}-es" for uid in names})

    def test_languages_have_the_same_layout_and_filters(self):
        for name in ("feed", "salaries", "market", "pipeline"):
            en, es = (json.loads((DASHBOARDS / lang / f"{name}.json").read_text(encoding="utf-8")) for lang in ("en", "es"))
            with self.subTest(dashboard=name):
                self.assertEqual([p["gridPos"] for p in en["panels"]], [p["gridPos"] for p in es["panels"]])
                self.assertEqual([v["name"] for v in en["templating"]["list"]], [v["name"] for v in es["templating"]["list"]])
                self.assertNotEqual(en["title"], es["title"])
                switch, add = [link for link in en["links"] if link["type"] == "link"]
                self.assertEqual(switch["url"], f"/d/{es['uid']}")
                self.assertTrue(switch["includeVars"])
                self.assertEqual(add["url"], "http://localhost:8100/?lang=en")

    def test_every_filter_is_a_dropdown(self):
        for path in DASHBOARD_FILES:
            for variable in json.loads(path.read_text(encoding="utf-8"))["templating"]["list"]:
                self.assertIn(variable["type"], {"custom", "query"}, f"{path.name}: {variable['name']}")

    def test_panels_fill_whole_rows(self):
        for path in DASHBOARD_FILES:
            rows: dict[int, int] = {}
            for panel in json.loads(path.read_text(encoding="utf-8"))["panels"]:
                rows[panel["gridPos"]["y"]] = rows.get(panel["gridPos"]["y"], 0) + panel["gridPos"]["w"]
            self.assertEqual(set(rows.values()), {24}, path.name)


if __name__ == "__main__":
    unittest.main()
