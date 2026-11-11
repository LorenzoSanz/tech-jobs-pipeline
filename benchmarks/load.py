"""How long ``jobpipe load`` takes as bronze grows, on synthetic postings.

Writes a bronze layer of ``--postings`` open postings collected over ``--runs``
daily runs (a tenth of the postings close and are replaced between runs, and a
quarter of the board postings show up again on Adzuna), then times the two
halves of a load:

- build: read every bronze record, clean it (places, seniority, technologies),
  group postings into jobs and score them against a profile; pure Python.
- write: COPY the rows into PostgreSQL and rebuild the gold views; only with
  ``--dsn``. Use a scratch database: the load replaces silver.

    PYTHONPATH=src python benchmarks/load.py --postings 2000 10000 50000
    PYTHONPATH=src python benchmarks/load.py --postings 10000 \
        --dsn postgresql://jobpipe:jobpipe@127.0.0.1:55432/jobpipe_test

Prints one JSON line per size.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import tempfile
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

from jobpipe import match, warehouse
from jobpipe.bronze import BronzeWriter, RawItem

TITLES = [
    "Data Engineer", "Senior Data Engineer", "Backend Engineer (m/w/d)", "Software Engineer III",
    "Site Reliability Engineer", "Staff Platform Engineer", "Machine Learning Engineer", "Data Analyst",
    "Frontend Developer", "Engineering Manager", "Ingeniero/a de Datos", "DevOps Engineer - Remote",
]  # fmt: skip
COMPANIES = ["Acme AG", "Google Switzerland GmbH", "Datadog", "Globex S.L.", "Initech GmbH", "Stripe, Inc.",
             "Umbrella SA", "Amazon Web Services EMEA SARL", "Hooli", "Vandelay Industries"]  # fmt: skip
PLACES = ["Zürich, Switzerland", "Madrid, Spain", "Berlin, Germany", "Remote - Europe", "Barcelona",
          "Geneva; Lausanne", "London, United Kingdom", "Amsterdam, Netherlands", "New York, NY"]  # fmt: skip
WORDS = ["Python", "SQL", "Kafka", "Kubernetes", "AWS", "Terraform", "PostgreSQL", "Spark", "Go", "React",
         "dbt", "Airflow", "Docker", "Grafana", "Java", "TypeScript"]  # fmt: skip
FILLER = "You will design, build and run services used by millions of people across Europe. " * 12


def _description(rnd: random.Random) -> str:
    return f"<p>{FILLER}</p><ul>" + "".join(f"<li>{w}</li>" for w in rnd.sample(WORDS, 5)) + "</ul>"


def _job(rnd: random.Random, n: int) -> dict[str, object]:
    return {
        "id": n, "title": rnd.choice(TITLES), "company_name": rnd.choice(COMPANIES),
        "location": {"name": rnd.choice(PLACES)}, "absolute_url": f"https://example.com/jobs/{n}",
        "content": _description(rnd),
    }  # fmt: skip


def write_bronze(root: Path, postings: int, runs: int, seed: int = 0) -> int:
    """Synthetic bronze; returns the number of records written."""
    rnd = random.Random(seed)
    open_jobs = {n: _job(rnd, n) for n in range(postings)}
    next_id, records = postings, 0
    start = datetime(2026, 10, 1, 6, tzinfo=UTC)
    for run in range(runs):
        def clock(day: int = run) -> datetime:
            return start + timedelta(days=day)

        writer = BronzeWriter(root, clock=clock)

        def board(jobs: dict[int, dict[str, object]]) -> Iterator[RawItem]:
            for n, job in jobs.items():
                yield RawItem(f"acme:{n}", {"board": "acme", "job": job})

        def adzuna(jobs: dict[int, dict[str, object]]) -> Iterator[RawItem]:
            for n, job in list(jobs.items())[::4]:  # the same job, posted again by an aggregator
                yield RawItem(f"ch:{n}", {"country": "ch", "job": {
                    "id": n, "title": job["title"], "company": {"display_name": job["company_name"]},
                    "location": {"display_name": job["location"]["name"]},  # type: ignore[index]
                    "redirect_url": f"https://example.com/adzuna/{n}", "description": FILLER[:500],
                }})  # fmt: skip

        records += writer.write("greenhouse", board(open_jobs)).records
        records += writer.write("adzuna", adzuna(open_jobs)).records
        for n in rnd.sample(sorted(open_jobs), postings // 10):
            del open_jobs[n]
            open_jobs[next_id] = _job(rnd, next_id)
            next_id += 1
    return records


def bench(postings: int, runs: int, dsn: str | None) -> dict[str, object]:
    profile = match.Profile(skills=frozenset({"python", "sql", "postgresql", "docker"}))
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        started = time.perf_counter()
        records = write_bronze(root, postings, runs)
        generated = time.perf_counter() - started

        started = time.perf_counter()
        tables = warehouse.build(root, profile)
        built = time.perf_counter() - started

        written = None
        if dsn:
            started = time.perf_counter()
            warehouse.write(dsn, tables)
            written = time.perf_counter() - started
    return {
        "postings": postings, "runs": runs, "bronze_records": records, "silver_postings": len(tables.postings),
        "generate_s": round(generated, 2), "build_s": round(built, 2),
        "build_records_per_s": round(records / built), "write_s": round(written, 2) if written else None,
    }  # fmt: skip


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--postings", type=int, nargs="+", default=[2000, 10000])
    parser.add_argument("--runs", type=int, default=3, help="daily runs; each snapshots every open posting")
    parser.add_argument("--dsn", help="also time the write into this PostgreSQL database (a scratch one)")
    args = parser.parse_args(argv)
    for size in args.postings:
        print(json.dumps(bench(size, args.runs, args.dsn)), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
