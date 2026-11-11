"""Command line entry point: ``jobpipe ingest <source>``, ``discover-boards`` and ``salaries``.

Logs go to stderr; one JSON summary line per bronze write goes to stdout, so a
scheduler can parse the result of each run.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import tomllib
from datetime import date
from pathlib import Path
from typing import Sequence

from jobpipe.bronze import BronzeWriter, WriteResult, read_records
from jobpipe.discovery import REGION_KEYWORDS, discover_from_hn, location_pattern
from jobpipe.http import HttpClient, HttpError
from jobpipe import salary
from jobpipe.sources import adzuna, ats, hn, levelsfyi

DEFAULT_DATA_DIR = Path(os.environ.get("JOBPIPE_DATA_DIR", "data/bronze"))
DEFAULT_BOARDS_FILE = Path("config/boards.toml")


def _summary(result: WriteResult, **extra: object) -> str:
    return json.dumps(
        {
            "source": result.source,
            "run_id": result.run_id,
            "records": result.records,
            "path": str(result.path) if result.path else None,
            **extra,
        }
    )


def _ingest_hn(args: argparse.Namespace, http: HttpClient, writer: BronzeWriter) -> int:
    result = writer.write(hn.SOURCE, hn.ingest(http, since=args.since))
    print(_summary(result))
    return 0


def _ingest_ats(args: argparse.Namespace, http: HttpClient, writer: BronzeWriter) -> int:
    config = tomllib.loads(args.boards.read_text(encoding="utf-8"))
    selected = [args.only] if args.only else list(ats.FETCHERS)
    attempted = 0
    failed = 0
    for name in selected:
        boards = config.get(name, {}).get("boards", [])
        if not boards:
            continue
        failures: list[ats.BoardFailure] = []
        result = writer.write(name, ats.ingest(http, name, boards, failures))
        attempted += len(boards)
        failed += len(failures)
        print(_summary(result, boards=len(boards), failed_boards=[f.board for f in failures]))
    if attempted == 0:
        logging.error("no boards configured in %s", args.boards)
        return 2
    return 1 if failed == attempted else 0


def _adzuna_credentials() -> adzuna.AdzunaCredentials | None:
    app_id = os.environ.get("ADZUNA_APP_ID")
    app_key = os.environ.get("ADZUNA_APP_KEY")
    if not app_id or not app_key:
        logging.error("set ADZUNA_APP_ID and ADZUNA_APP_KEY (free key at developer.adzuna.com)")
        return None
    return adzuna.AdzunaCredentials(app_id, app_key)


def _ingest_adzuna(args: argparse.Namespace, http: HttpClient, writer: BronzeWriter) -> int:
    credentials = _adzuna_credentials()
    if credentials is None:
        return 2
    countries = args.country or ["ch"]
    failed = 0
    for country in countries:
        query = adzuna.AdzunaQuery(
            country=country,
            category=args.category or None,
            what=args.what,
            max_days_old=args.max_days_old,
            max_pages=args.max_pages,
        )
        try:
            result = writer.write("adzuna", adzuna.ingest(http, credentials, query))
        except HttpError as error:
            logging.error("adzuna %s failed: %s", country, error)
            failed += 1
            continue
        print(_summary(result, country=country))
    return 1 if failed == len(countries) else 0


def _ingest_adzuna_salaries(args: argparse.Namespace, http: HttpClient, writer: BronzeWriter) -> int:
    credentials = _adzuna_credentials()
    if credentials is None:
        return 2
    countries = args.country or ["ch"]
    searches = args.what or [None]
    queries = [
        adzuna.SalaryQuery(
            country=country,
            what=what,
            category=args.category or None,
            history_months=args.history_months if index == 0 else 0,
        )
        for country in countries
        for index, what in enumerate(searches)
    ]
    failed = 0
    for query in queries:
        try:
            result = writer.write(adzuna.SALARY_SOURCE, adzuna.salary_benchmarks(http, credentials, query))
        except HttpError as error:
            logging.error("adzuna salaries %s %r failed: %s", query.country, query.what, error)
            failed += 1
            continue
        print(_summary(result, country=query.country, what=query.what))
    return 1 if failed == len(queries) else 0


def _levelsfyi_key() -> str | None:
    key = os.environ.get("LEVELS_FYI_API_KEY")
    if not key:
        logging.error(
            "set LEVELS_FYI_API_KEY (employer key: levels.fyi/api-access). Without one, look up "
            "Levels.fyi by hand or through its free MCP server; scraping the site breaks its terms."
        )
    return key


def _ingest_levelsfyi(args: argparse.Namespace, http: HttpClient, writer: BronzeWriter) -> int:
    key = _levelsfyi_key()
    if key is None:
        return 2
    query = levelsfyi.BenchmarkQuery(
        job_family=args.job_family,
        locations=tuple(args.location),
        salary_type=args.salary_type,
        time_range=args.time_range,
        focus_tags=tuple(args.focus_tag or ()),
    )
    result = writer.write(levelsfyi.SOURCE, levelsfyi.benchmarks(http, key, query))
    print(_summary(result, job_family=query.job_family, locations=list(query.locations)))
    return 0


def _levelsfyi_lookup(args: argparse.Namespace, http: HttpClient) -> int:
    key = _levelsfyi_key()
    if key is None:
        return 2
    print(json.dumps(levelsfyi.lookup(http, key, args.kind, args.text), indent=2, ensure_ascii=False))
    return 0


def _salaries(args: argparse.Namespace) -> int:
    title = re.compile(args.title, re.IGNORECASE) if args.title else None
    postings = salary.filter_salaries(
        salary.posted_salaries(args.data_dir, args.source or list(salary.EXTRACTORS)),
        regions=args.region or (),
        title=title,
        include_predicted=args.include_predicted,
    )
    summary = salary.summarise(postings)
    histograms = salary.benchmark_records(args.data_dir, adzuna.SALARY_SOURCE)
    levels = salary.benchmark_records(args.data_dir, levelsfyi.SOURCE)
    if args.format == "json":
        report = {
            "postings": summary,
            "adzuna": [record["payload"] for record in histograms],
            "levelsfyi": [record["payload"] for record in levels],
        }
        print(json.dumps(salary.to_jsonable(report), indent=2, ensure_ascii=False))
    else:
        sys.stdout.write(salary.render_text(summary, histograms, levels))
    return 0


def _discover_boards(args: argparse.Namespace) -> int:
    regions = args.region or ["ch"]
    counts = discover_from_hn(read_records(args.data_dir, hn.SOURCE), location_pattern(regions))
    print(f"# Boards linked from HN postings that mention a location in: {', '.join(regions)}.")
    print("# Review each one before adding it to config/boards.toml. Number = postings.")
    for name, counter in counts.items():
        print(f"\n[{name}]\nboards = [")
        for slug, count in counter.most_common():
            if count >= args.min_count:
                print(f'  "{slug}",  # {count}')
        print("]")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jobpipe", description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR, help="bronze root directory")
    parser.add_argument("-v", "--verbose", action="store_true")
    commands = parser.add_subparsers(dest="command", required=True)

    ingest = commands.add_parser("ingest", help="collect one source into the bronze layer")
    sources = ingest.add_subparsers(dest="source", required=True)

    hn_parser = sources.add_parser("hn", help='HN "Who is hiring?" threads')
    hn_parser.add_argument("--since", type=date.fromisoformat, help="YYYY-MM-DD; default: all since 2011")
    hn_parser.set_defaults(handler=_ingest_hn)

    ats_parser = sources.add_parser("ats", help="Greenhouse, Lever and Ashby boards")
    ats_parser.add_argument("--boards", type=Path, default=DEFAULT_BOARDS_FILE)
    ats_parser.add_argument("--only", choices=sorted(ats.FETCHERS))
    ats_parser.set_defaults(handler=_ingest_ats)

    adzuna_parser = sources.add_parser("adzuna", help="Adzuna search API (needs a free key)")
    adzuna_parser.add_argument(
        "--country",
        action="append",
        help="ISO country code, repeatable: --country ch --country es (default: ch)",
    )
    adzuna_parser.add_argument(
        "--category",
        default="it-jobs",
        help="Adzuna category tag (country-specific); empty string for all categories",
    )
    adzuna_parser.add_argument("--what", help="keywords, e.g. 'kubernetes'")
    adzuna_parser.add_argument("--max-days-old", type=int)
    adzuna_parser.add_argument("--max-pages", type=int, default=20)
    adzuna_parser.set_defaults(handler=_ingest_adzuna)

    adzuna_salary_parser = sources.add_parser(
        "adzuna-salaries", help="Adzuna salary histogram per search, and category trend (free key)"
    )
    adzuna_salary_parser.add_argument("--country", action="append", help="repeatable; default: ch")
    adzuna_salary_parser.add_argument(
        "--what", action="append", help="repeatable search, e.g. --what 'data engineer'"
    )
    adzuna_salary_parser.add_argument("--category", default="it-jobs")
    adzuna_salary_parser.add_argument("--history-months", type=int, default=12)
    adzuna_salary_parser.set_defaults(handler=_ingest_adzuna_salaries)

    levels_parser = sources.add_parser(
        "levelsfyi", help="Levels.fyi Compensation API benchmarks (needs LEVELS_FYI_API_KEY)"
    )
    levels_parser.add_argument("--job-family", default="software-engineer")
    levels_parser.add_argument(
        "--location",
        action="append",
        required=True,
        help="Levels.fyi location slug, repeatable (find it: jobpipe levelsfyi-lookup locations zurich)",
    )
    levels_parser.add_argument(
        "--salary-type",
        default="total_compensation",
        choices=["total_compensation", "base_salary", "total_cash"],
    )
    levels_parser.add_argument("--time-range", default="0-12", help="months back: 0-12, 0-24, ...")
    levels_parser.add_argument("--focus-tag", action="append", help="repeatable, e.g. backend")
    levels_parser.set_defaults(handler=_ingest_levelsfyi)

    lookup = commands.add_parser(
        "levelsfyi-lookup", help="find Levels.fyi slugs (needs LEVELS_FYI_API_KEY)"
    )
    lookup.add_argument(
        "kind", choices=["locations", "job-families", "focus-tags", "titles", "companies"]
    )
    lookup.add_argument("text")

    report = commands.add_parser("salaries", help="salary report from collected data, for negotiating")
    report.add_argument(
        "--region",
        action="append",
        choices=sorted(salary.REGION_PATTERNS),
        help="repeatable: --region ch --region es (default: everywhere)",
    )
    report.add_argument("--title", help="regex on the job title, e.g. 'data|backend'")
    report.add_argument("--source", action="append", choices=sorted(salary.EXTRACTORS))
    report.add_argument(
        "--include-predicted",
        action="store_true",
        help="include salaries Adzuna estimated instead of the employer stating them",
    )
    report.add_argument("--format", choices=["text", "json"], default="text")

    discover = commands.add_parser("discover-boards", help="suggest ATS boards from collected HN data")
    discover.add_argument("--min-count", type=int, default=1)
    discover.add_argument(
        "--region",
        action="append",
        choices=sorted(REGION_KEYWORDS),
        help="repeatable: --region ch --region es --region eu (default: ch)",
    )
    discover.set_defaults(handler=None)

    return parser


def main(argv: Sequence[str] | None = None, http: HttpClient | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    if args.command == "discover-boards":
        return _discover_boards(args)
    if args.command == "salaries":
        return _salaries(args)
    if args.command == "levelsfyi-lookup":
        return _levelsfyi_lookup(args, http or HttpClient())
    return args.handler(args, http or HttpClient(), BronzeWriter(args.data_dir))


if __name__ == "__main__":
    sys.exit(main())
