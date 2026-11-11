"""Command line entry point: ``jobpipe ingest <source>``, board discovery, ``salaries`` and ``feed``.

Logs go to stderr; one JSON summary line per bronze write goes to stdout, so a
scheduler can parse the result of each run.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import os
import re
import sys
import tomllib
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Sequence

from jobpipe.bronze import BronzeWriter, WriteResult, read_records
from jobpipe.discovery import REGION_KEYWORDS, discover_from_hn, location_pattern
from jobpipe.http import HttpClient, HttpError
from jobpipe import employers, match, salary, tech
from jobpipe.sources import adzuna, ats, hn, levelsfyi
from jobpipe.verification import render_toml, verify

DEFAULT_DATA_DIR = Path(os.environ.get("JOBPIPE_DATA_DIR", "data/bronze"))
DEFAULT_BOARDS_FILE = Path("config/boards.toml")
DEFAULT_PROFILE = Path("config/profile.toml")


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


def _profile(path: Path, required: bool) -> match.Profile | None:
    if not path.exists():
        if required:
            logging.error("no profile at %s: copy config/profile.example.toml and list your skills", path)
        return None
    return match.load_profile(path)


def _feed(args: argparse.Namespace) -> int:
    from jobpipe import warehouse

    try:
        profile = _profile(args.profile, required=True)
    except match.ProfileError as error:
        logging.error("%s", error)
        return 2
    if profile is None:
        return 2
    if args.tier:
        profile = dataclasses.replace(profile, company_tiers=frozenset(args.tier))
    since = (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat() if args.days else ""
    rows = []
    for current in warehouse.current_postings(args.data_dir):
        posting = current.posting
        employer = employers.employer_of(posting.company)
        m = match.match(profile, posting.title, current.role, posting.regions, current.technologies,
                        current.seniority, employer.tier)  # fmt: skip
        if current.is_open and current.job_rank == 0 and m.fits:
            rows.append((current, m, employer))
    gaps = match.gaps(m for _, m, _ in rows)
    shown = [
        (c, m, e) for c, m, e in rows
        if c.first_seen >= since and (m.score or 0) * 100 >= args.min_score
    ]  # fmt: skip
    shown.sort(key=lambda row: (row[1].rank, len(row[1].have), row[0].first_seen), reverse=True)
    shown = shown[: args.limit]
    label = {key: t.label for key, t in tech.BY_KEY.items()}

    if args.format == "json":
        print(json.dumps({
            "postings": [{
                "score": m.score, "title": c.posting.title, "company": c.posting.company,
                "employer": e.name, "company_tier": e.tier,
                "location": c.posting.location, "city": c.posting.place.city,
                "countries": list(c.posting.countries), "remote": c.posting.place.remote,
                "regions": list(c.posting.regions), "role": c.role, "seniority": c.seniority,
                "have": list(m.have), "missing": list(m.missing), "first_seen": c.first_seen,
                "url": c.posting.url, "source": c.posting.source,
            } for c, m, e in shown],
            "gaps": [{"technology": key, "postings": n, "share": share} for key, n, share in gaps],
        }, indent=2, ensure_ascii=False))  # fmt: skip
        return 0

    print(f"{len(rows)} open postings fit your profile; showing {len(shown)}.\n")
    tags = {employers.FAANG.key: "  [FAANG]", employers.BIG_TECH.key: "  [big tech]"}
    for c, m, e in shown:
        score = f"{m.score:4.0%}" if m.score is not None else "   -"
        place = ", ".join(filter(None, [c.posting.company, c.posting.location, "/".join(c.posting.regions)]))
        print(f"{score}  {c.posting.title}" + (f"  ({place})" if place else "") + tags.get(e.tier, ""))
        if m.have or m.missing:
            known = ", ".join(label[k] for k in m.have) or "-"
            print(f"      you know: {known}" + (f"  | lacks: {', '.join(label[k] for k in m.missing)}" if m.missing else ""))
        print(f"      {c.posting.url}  (first seen {c.first_seen[:10]})")
    if gaps:
        print("\nWhat you lack most often in these postings:")
        for key, n, share in gaps[:10]:
            print(f"  {label[key]:<16} {share:4.0%}  ({n})")
    return 0


def _discover_boards(args: argparse.Namespace) -> int:
    regions = args.region or ["ch"]
    counts = discover_from_hn(
        read_records(args.data_dir, hn.SOURCE), location_pattern(regions), since=args.since
    )
    print(f"# Boards linked from HN postings that mention a location in: {', '.join(regions)}.")
    print("# Review each one before adding it to config/boards.toml. Number = postings.")
    for name, counter in counts.items():
        print(f"\n[{name}]\nboards = [")
        for slug, count in counter.most_common():
            if count >= args.min_count:
                print(f'  "{slug}",  # {count}')
        print("]")
    return 0


def _verify_boards(args: argparse.Namespace, http: HttpClient) -> int:
    candidates = tomllib.loads(args.boards.read_text(encoding="utf-8-sig"))
    boards = {name: section.get("boards", []) for name, section in candidates.items()}
    checks = verify(http, boards, location_pattern(args.region or ["ch"]))
    print(render_toml(checks), end="")
    kept = sum(check.keep for check in checks)
    logging.info("kept %d of %d boards", kept, len(checks))
    return 0 if kept else 1


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

    ats_parser = sources.add_parser("ats", help="public ATS boards (Greenhouse, Lever, Ashby, SmartRecruiters, Workable, Recruitee, Personio)")
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
        "--since", type=date.fromisoformat, help="YYYY-MM-DD; ignore older HN postings"
    )
    discover.add_argument(
        "--region",
        action="append",
        choices=sorted(REGION_KEYWORDS),
        help="repeatable: --region ch --region es --region eu (default: ch)",
    )
    discover.set_defaults(handler=None)

    verify_parser = commands.add_parser(
        "verify-boards", help="keep only candidate boards that answer and hire in the region"
    )
    verify_parser.add_argument("--boards", type=Path, required=True, help="output of discover-boards")
    verify_parser.add_argument(
        "--region",
        action="append",
        choices=sorted(REGION_KEYWORDS),
        help="repeatable: --region ch --region es --region eu (default: ch)",
    )

    load = commands.add_parser("load", help="rebuild the PostgreSQL silver/gold layers from bronze")
    load.add_argument(
        "--dsn",
        default=os.environ.get("JOBPIPE_DATABASE_URL"),
        help="PostgreSQL URL (default: $JOBPIPE_DATABASE_URL or the docker compose database)",
    )
    load.add_argument(
        "--profile", type=Path, default=DEFAULT_PROFILE,
        help=f"your skills and filters, to score postings (default: {DEFAULT_PROFILE}; skipped if missing)",
    )  # fmt: skip

    feed = commands.add_parser("feed", help="open postings that fit your profile, best match first")
    feed.add_argument("--profile", type=Path, default=DEFAULT_PROFILE, help=f"default: {DEFAULT_PROFILE}")
    feed.add_argument("--days", type=int, help="only postings first seen in the last N days")
    feed.add_argument("--min-score", type=int, default=0, help="minimum match, 0-100")
    feed.add_argument("--tier", action="append", choices=[t.key for t in employers.TIERS],
                      help="only these company tiers (repeatable); overrides company_tiers in the profile")
    feed.add_argument("--limit", type=int, default=25)
    feed.add_argument("--format", choices=["text", "json"], default="text")

    return parser


def _load(args: argparse.Namespace) -> int:
    from jobpipe import warehouse

    try:
        profile = _profile(args.profile, required=False)
    except match.ProfileError as error:
        logging.error("%s", error)
        return 2
    if profile is None:
        logging.info("no profile at %s: postings are not scored", args.profile)
    tables = warehouse.build(args.data_dir, profile)
    try:
        counts = warehouse.write(args.dsn or warehouse.DEFAULT_DSN, tables)
    except RuntimeError as error:
        logging.error("%s", error)
        return 2
    except Exception as error:  # psycopg.OperationalError and friends
        logging.error("load failed: %s", error)
        return 1
    print(json.dumps({"loaded": counts}))
    return 0


def main(argv: Sequence[str] | None = None, http: HttpClient | None = None) -> int:
    args = build_parser().parse_args(argv)
    # Postings carry any script (Romanian, Czech...); on Windows a redirected
    # stdout defaults to the ANSI code page and cannot print them.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
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
    if args.command == "verify-boards":
        return _verify_boards(args, http or HttpClient())
    if args.command == "load":
        return _load(args)
    if args.command == "feed":
        return _feed(args)
    return args.handler(args, http or HttpClient(), BronzeWriter(args.data_dir))


if __name__ == "__main__":
    sys.exit(main())
