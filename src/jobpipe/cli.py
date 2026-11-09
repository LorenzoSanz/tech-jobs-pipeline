"""Command line entry point: ``jobpipe ingest <source>`` and ``jobpipe discover-boards``.

Logs go to stderr; one JSON summary line per bronze write goes to stdout, so a
scheduler can parse the result of each run.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tomllib
from datetime import date
from pathlib import Path
from typing import Sequence

from jobpipe.bronze import BronzeWriter, WriteResult, read_records
from jobpipe.discovery import REGION_KEYWORDS, discover_from_hn, location_pattern
from jobpipe.http import HttpClient, HttpError
from jobpipe.sources import adzuna, ats, hn

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


def _ingest_adzuna(args: argparse.Namespace, http: HttpClient, writer: BronzeWriter) -> int:
    app_id = os.environ.get("ADZUNA_APP_ID")
    app_key = os.environ.get("ADZUNA_APP_KEY")
    if not app_id or not app_key:
        logging.error("set ADZUNA_APP_ID and ADZUNA_APP_KEY (free key at developer.adzuna.com)")
        return 2
    credentials = adzuna.AdzunaCredentials(app_id, app_key)
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
    return args.handler(args, http or HttpClient(), BronzeWriter(args.data_dir))


if __name__ == "__main__":
    sys.exit(main())
