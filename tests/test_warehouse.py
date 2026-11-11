import json
import os
import re
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from jobpipe import warehouse
from jobpipe.bronze import BronzeWriter, RawItem

DASHBOARDS = Path(__file__).resolve().parent.parent / "grafana" / "dashboards"
TEST_DSN = os.environ.get("JOBPIPE_TEST_DATABASE_URL")


def clock(day: int, hour: int = 8):
    return lambda: datetime(2026, 11, day, hour, tzinfo=timezone.utc)


def ashby_job(job_id: str = "a1", low: int = 120000, title: str = "Backend Engineer") -> dict:
    return {
        "id": job_id, "title": title, "location": "Zurich", "publishedAt": "2026-10-01T00:00:00Z",
        "address": {"postalAddress": {"addressCountry": "Switzerland"}},
        "jobUrl": f"https://jobs.ashbyhq.com/acme/{job_id}",
        "compensation": {"summaryComponents": [
            {"compensationType": "Salary", "currencyCode": "CHF", "interval": "1 YEAR",
             "minValue": low, "maxValue": low + 30000}]},
    }  # fmt: skip


def write_fixture(root: Path) -> None:
    """Two snapshots of one Swiss posting, one Spanish HN posting, and salary benchmarks."""
    BronzeWriter(root, clock(1)).write("ashby", [RawItem("acme:a1", {"board": "acme", "job": ashby_job(low=110000)})])
    BronzeWriter(root, clock(9)).write("ashby", [RawItem("acme:a1", {"board": "acme", "job": ashby_job()})])
    comment = {"id": 7, "author": "x", "text": "Acme | Madrid | Data Engineer<p>€55k - €70k", "created_at": None}
    BronzeWriter(root, clock(9)).write(
        "hn", [RawItem("7", {"comment": comment}, datetime(2026, 11, 2, tzinfo=timezone.utc))]
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
        self.tables = warehouse.build(self.root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_postings_keep_newest_snapshot_and_lifetime(self):
        rows = {row[1]: dict(zip(warehouse.POSTING_COLUMNS, row)) for row in self.tables.postings}
        swiss = rows["acme:a1"]

        self.assertEqual(swiss["first_seen"], datetime(2026, 11, 1, 8, tzinfo=timezone.utc))
        self.assertEqual(swiss["last_seen"], datetime(2026, 11, 9, 8, tzinfo=timezone.utc))
        self.assertEqual(swiss["snapshots"], 2)
        self.assertEqual(swiss["regions"], ["ch"])
        self.assertEqual(swiss["role"], "Backend")
        self.assertEqual(rows["7"]["regions"], ["es"])

    def test_salaries_come_from_the_newest_snapshot(self):
        by_id = {row[1]: dict(zip(warehouse.SALARY_COLUMNS, row)) for row in self.tables.posted_salaries}

        self.assertEqual((by_id["acme:a1"]["currency"], by_id["acme:a1"]["min_annual"]), ("CHF", 120000))
        self.assertEqual((by_id["7"]["currency"], by_id["7"]["max_annual"]), ("EUR", 70000))

    def test_benchmarks_and_runs(self):
        self.assertEqual(sorted(r[3] for r in self.tables.adzuna_salary_histogram), [100000, 120000])
        self.assertEqual([r[2] for r in self.tables.adzuna_salary_history], [date(2026, 9, 1), date(2026, 10, 1)])
        self.assertEqual(self.tables.levelsfyi_benchmarks[0][3], "zurich-area")
        self.assertEqual(sorted((r[0], r[3]) for r in self.tables.ingest_runs),
                         [("adzuna_salary", 2), ("ashby", 1), ("ashby", 1), ("hn", 1), ("levelsfyi", 1)])  # fmt: skip

    def test_write_explains_a_missing_driver(self):
        try:
            import psycopg  # noqa: F401
        except ImportError:
            with self.assertRaisesRegex(RuntimeError, "pip install"):
                warehouse.write("postgresql://nowhere/db", self.tables)
        else:
            self.skipTest("psycopg is installed")


def panel_sql(dashboard: dict) -> list[tuple[str, str]]:
    """Every panel and variable query, with Grafana's macros and variables filled in."""
    queries = [(p["title"], t["rawSql"]) for p in dashboard["panels"] for t in p.get("targets", [])]
    queries += [(f"variable {v['name']}", v["query"]) for v in dashboard["templating"]["list"] if v["type"] == "query"]
    values = {
        "region": "'ch','es','eu','other'", "currency:sqlstring": "'CHF'", "role": "'__all'",
        "company": "'Acme','acme'", "predicted:raw": "false", "offer:sqlstring": "'100000'",
        "adzuna:sqlstring": "'ch | data engineer'", "with_salary:raw": "true",
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
        cls.counts = warehouse.write(TEST_DSN, warehouse.build(root))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def query(self, sql: str):
        with self.psycopg.connect(TEST_DSN) as conn:
            return conn.execute(sql).fetchall()

    def test_load_is_repeatable(self):
        root = Path(self.tmp.name)
        warehouse.write(TEST_DSN, warehouse.build(root))

        self.assertEqual(self.query("SELECT count(*) FROM silver.postings"), [(2,)])
        self.assertEqual(self.query("SELECT count(*) FROM silver.load_log"), [(1,)])

    def test_gold_views(self):
        regions = dict(self.query("SELECT source_id, region FROM gold.posting_regions"))
        midpoint = self.query("SELECT midpoint FROM gold.salaries WHERE source = 'ashby'")

        self.assertEqual(regions, {"acme:a1": "ch", "7": "es"})
        self.assertEqual(float(midpoint[0][0]), 135000)

    def test_every_dashboard_query_runs(self):
        for path in sorted(DASHBOARDS.glob("*.json")):
            dashboard = json.loads(path.read_text(encoding="utf-8"))
            for title, sql in panel_sql(dashboard):
                with self.subTest(dashboard=path.name, panel=title):
                    self.assertNotIn("$", re.sub(r"\$\$", "", sql), "unfilled Grafana variable")
                    self.query(sql)

    def test_offer_percentile_on_the_salary_dashboard(self):
        dashboard = json.loads((DASHBOARDS / "salaries.json").read_text(encoding="utf-8"))
        [(_, sql)] = [q for q in panel_sql(dashboard) if q[0] == "Tu oferta supera al"]

        self.assertEqual(float(self.query(sql)[0][0]), 0.0)  # 100k is below the CHF 120-150k posting


class DashboardFilesTest(unittest.TestCase):
    def test_dashboards_are_valid_and_use_the_provisioned_datasource(self):
        uids = set()
        for path in sorted(DASHBOARDS.glob("*.json")):
            dashboard = json.loads(path.read_text(encoding="utf-8"))
            uids.add(dashboard["uid"])
            for panel in dashboard["panels"]:
                if panel["type"] == "row":
                    continue
                self.assertEqual(panel["datasource"]["uid"], "jobpipe-pg", f"{path.name}: {panel['title']}")
        self.assertEqual(uids, {"jobpipe-salaries", "jobpipe-market", "jobpipe-pipeline"})

    def test_every_filter_is_a_dropdown(self):
        for path in sorted(DASHBOARDS.glob("*.json")):
            for variable in json.loads(path.read_text(encoding="utf-8"))["templating"]["list"]:
                self.assertIn(variable["type"], {"custom", "query"}, f"{path.name}: {variable['name']}")

    def test_panels_fill_whole_rows(self):
        for path in sorted(DASHBOARDS.glob("*.json")):
            rows: dict[int, int] = {}
            for panel in json.loads(path.read_text(encoding="utf-8"))["panels"]:
                rows[panel["gridPos"]["y"]] = rows.get(panel["gridPos"]["y"], 0) + panel["gridPos"]["w"]
            self.assertEqual(set(rows.values()), {24}, path.name)


if __name__ == "__main__":
    unittest.main()
