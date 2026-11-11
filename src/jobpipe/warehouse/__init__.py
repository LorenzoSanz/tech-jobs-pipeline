"""Load bronze into PostgreSQL: the silver tables and gold views Grafana reads.

Building the rows is pure Python over the bronze files (``build``), so it is
tested without a database. Writing them (``write``) needs psycopg, an optional
dependency: ``pip install -e .[db]``.

Silver is rebuilt from scratch on every load, inside one transaction: bronze
is the source of truth, so there is nothing in silver worth migrating, and a
reader never sees a half-loaded state.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from importlib import resources
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping

from jobpipe import jobs, roles
from jobpipe.bronze import read_records
from jobpipe.sources import adzuna, levelsfyi

logger = logging.getLogger(__name__)

# 127.0.0.1, not localhost: on Windows "localhost" tries ::1 first, which Docker
# Desktop does not answer, so the connection hangs instead of failing.
DEFAULT_DSN = "postgresql://jobpipe:jobpipe@127.0.0.1:55432/jobpipe"

POSTING_COLUMNS = (
    "source", "source_id", "title", "company", "location", "country", "url",
    "published", "first_seen", "last_seen", "snapshots", "regions", "role",
)  # fmt: skip
SALARY_COLUMNS = ("source", "source_id", "n", "currency", "min_annual", "max_annual", "period", "predicted", "tier")
HISTOGRAM_COLUMNS = ("country", "category", "what", "bucket_from", "postings", "fetched_at")
HISTORY_COLUMNS = ("country", "category", "month", "avg_salary", "fetched_at")
LEVELS_COLUMNS = (
    "job_family", "salary_type", "focus_tags", "location", "kind", "yoe_range",
    "p10", "p25", "p50", "p75", "p90", "sample_size", "fetched_at",
)  # fmt: skip
RUN_COLUMNS = ("source", "run_id", "ingest_date", "records", "first_fetched", "last_fetched")


@dataclass
class Tables:
    postings: list[tuple] = field(default_factory=list)
    posted_salaries: list[tuple] = field(default_factory=list)
    adzuna_salary_histogram: list[tuple] = field(default_factory=list)
    adzuna_salary_history: list[tuple] = field(default_factory=list)
    levelsfyi_benchmarks: list[tuple] = field(default_factory=list)
    ingest_runs: list[tuple] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        return {name: len(rows) for name, rows in vars(self).items()}


@dataclass
class _Seen:
    record: Mapping[str, Any]
    first: str
    last: str
    snapshots: int = 1


def _ts(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _lifetimes(records: Iterable[Mapping[str, Any]]) -> Iterator[_Seen]:
    """Newest snapshot of each posting, with when it was first and last seen."""
    seen: dict[str, _Seen] = {}
    for record in records:
        fetched = record.get("fetched_at") or ""
        current = seen.get(record["source_id"])
        if current is None:
            seen[record["source_id"]] = _Seen(record, fetched, fetched)
            continue
        current.snapshots += 1
        current.first = min(current.first, fetched)
        if fetched >= current.last:
            current.last, current.record = fetched, record
    yield from seen.values()


def _postings(data_dir: Path, tables: Tables) -> None:
    for source in jobs.SOURCES:
        for seen in _lifetimes(read_records(data_dir, source)):
            posting = jobs.to_posting(source, seen.record)
            if posting is None:
                continue
            tables.postings.append((
                source, posting.source_id, posting.title, posting.company, posting.location,
                posting.country, posting.url, _ts(posting.published), _ts(seen.first),
                _ts(seen.last), seen.snapshots, list(posting.regions), roles.role_of(posting.title),
            ))  # fmt: skip
            for n, s in enumerate(dict.fromkeys(map(_salary_key, posting.salaries))):
                tables.posted_salaries.append((source, posting.source_id, n, *s))


def _salary_key(salary: Mapping[str, Any]) -> tuple:
    return (salary["currency"], salary["min"], salary["max"], salary["period"], salary["predicted"], salary["tier"])


def _adzuna_salaries(data_dir: Path, tables: Tables) -> None:
    for seen in _lifetimes(read_records(data_dir, adzuna.SALARY_SOURCE)):
        payload, fetched = seen.record["payload"], _ts(seen.last)
        if payload["kind"] == "histogram":
            for bucket, count in payload["histogram"].items():
                tables.adzuna_salary_histogram.append((
                    payload["country"], payload.get("category"), payload.get("what"),
                    float(bucket), int(float(count)), fetched,
                ))  # fmt: skip
        elif payload["kind"] == "history":
            for month, value in payload["month"].items():
                tables.adzuna_salary_history.append((
                    payload["country"], payload["category"], date.fromisoformat(f"{month}-01"),
                    float(value), fetched,
                ))  # fmt: skip


def _levelsfyi(data_dir: Path, tables: Tables) -> None:
    for seen in _lifetimes(read_records(data_dir, levelsfyi.SOURCE)):
        payload, data = seen.record["payload"], seen.record["payload"]["data"]
        location = payload.get("location") or data.get("locationSlug")
        tables.levelsfyi_benchmarks.append((
            payload["job_family"], payload["salary_type"], ",".join(payload.get("focus_tags") or []),
            location, payload["kind"], data.get("yoeRange"),
            data.get("p10"), data.get("p25"), data.get("p50"), data.get("p75"), data.get("p90"),
            data.get("sampleSize"), _ts(seen.last),
        ))  # fmt: skip


def _runs(data_dir: Path, tables: Tables) -> None:
    for path in sorted(Path(data_dir).glob("source=*/ingest_date=*/run=*.jsonl")):
        source = path.parent.parent.name.removeprefix("source=")
        ingest_date = date.fromisoformat(path.parent.name.removeprefix("ingest_date="))
        run_id = path.stem.removeprefix("run=")
        records, first, last = 0, None, None
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                records += 1
                fetched = json.loads(line).get("fetched_at")
                if fetched:
                    first = min(first or fetched, fetched)
                    last = max(last or fetched, fetched)
        tables.ingest_runs.append((source, run_id, ingest_date, records, _ts(first), _ts(last)))


def build(data_dir: Path) -> Tables:
    tables = Tables()
    _postings(data_dir, tables)
    _adzuna_salaries(data_dir, tables)
    _levelsfyi(data_dir, tables)
    _runs(data_dir, tables)
    return tables


def schema_sql() -> str:
    return resources.files("jobpipe.warehouse").joinpath("schema.sql").read_text(encoding="utf-8")


def write(dsn: str, tables: Tables) -> dict[str, int]:
    """Rebuild silver and gold from ``tables`` in a single transaction."""
    try:
        import psycopg
    except ImportError as error:
        raise RuntimeError("psycopg is not installed: pip install -e .[db]") from error

    columns = {
        "postings": POSTING_COLUMNS,
        "posted_salaries": SALARY_COLUMNS,
        "adzuna_salary_histogram": HISTOGRAM_COLUMNS,
        "adzuna_salary_history": HISTORY_COLUMNS,
        "levelsfyi_benchmarks": LEVELS_COLUMNS,
        "ingest_runs": RUN_COLUMNS,
    }
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(schema_sql())
        for table, names in columns.items():
            rows = getattr(tables, table)
            with cur.copy(f"COPY silver.{table} ({', '.join(names)}) FROM STDIN") as copy:
                for row in rows:
                    copy.write_row(row)
        cur.execute(
            "INSERT INTO silver.load_log (postings, salaries, runs) VALUES (%s, %s, %s)",
            (len(tables.postings), len(tables.posted_salaries), len(tables.ingest_runs)),
        )
    return tables.counts()
