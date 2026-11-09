"""Public job boards of applicant tracking systems: Greenhouse, Lever and Ashby.

These are the employers' own postings, served by the same public endpoints that
power their career pages. Each call returns every published job of one board,
so a snapshot of a board is complete: a job missing from tomorrow's snapshot
has been taken down. That is what makes first_seen/last_seen reliable later.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Iterator

from jobpipe.bronze import RawItem
from jobpipe.http import HttpClient, HttpError

logger = logging.getLogger(__name__)

GREENHOUSE_API = "https://boards-api.greenhouse.io/v1/boards"
LEVER_API = "https://api.lever.co/v0/postings"
ASHBY_API = "https://api.ashbyhq.com/posting-api/job-board"
LEVER_PAGE_SIZE = 100


@dataclass(frozen=True)
class BoardFailure:
    ats: str
    board: str
    error: str


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def greenhouse_jobs(http: HttpClient, board: str) -> Iterator[RawItem]:
    data = http.get_json(f"{GREENHOUSE_API}/{board}/jobs", {"content": "true"})
    for job in data.get("jobs", []):
        yield RawItem(
            source_id=f"{board}:{job['id']}",
            event_time=_parse_iso(job.get("first_published")),
            payload={"board": board, "job": job},
        )


def lever_jobs(http: HttpClient, board: str) -> Iterator[RawItem]:
    skip = 0
    while True:
        page = http.get_json(
            f"{LEVER_API}/{board}", {"mode": "json", "skip": skip, "limit": LEVER_PAGE_SIZE}
        )
        for job in page:
            created = job.get("createdAt")
            yield RawItem(
                source_id=f"{board}:{job['id']}",
                event_time=datetime.fromtimestamp(created / 1000, tz=timezone.utc) if created else None,
                payload={"board": board, "job": job},
            )
        if len(page) < LEVER_PAGE_SIZE:
            return
        skip += LEVER_PAGE_SIZE


def ashby_jobs(http: HttpClient, board: str) -> Iterator[RawItem]:
    data = http.get_json(f"{ASHBY_API}/{board}", {"includeCompensation": "true"})
    for job in data.get("jobs", []):
        yield RawItem(
            source_id=f"{board}:{job['id']}",
            event_time=_parse_iso(job.get("publishedAt")),
            payload={"board": board, "job": job},
        )


FETCHERS: dict[str, Callable[[HttpClient, str], Iterator[RawItem]]] = {
    "greenhouse": greenhouse_jobs,
    "lever": lever_jobs,
    "ashby": ashby_jobs,
}


def ingest(
    http: HttpClient,
    ats: str,
    boards: Iterable[str],
    failures: list[BoardFailure],
) -> Iterator[RawItem]:
    """Snapshot every board; a broken board is recorded in ``failures`` and skipped.

    Items of one board are buffered until the board is read completely, so a
    board that fails halfway never contributes a partial snapshot.
    """
    fetch = FETCHERS[ats]
    for board in boards:
        try:
            items = list(fetch(http, board))
        except (HttpError, KeyError, TypeError, ValueError) as error:
            logger.warning("%s board %r failed: %s", ats, board, error)
            failures.append(BoardFailure(ats, board, str(error)))
            continue
        logger.info("%s board %r: %d jobs", ats, board, len(items))
        yield from items
