"""Public job boards of applicant tracking systems.

Greenhouse, Lever, Ashby, SmartRecruiters, Workable, Recruitee and Personio.
These are the employers' own postings, served by the same public endpoints that
power their career pages. Each call returns every published job of one board,
so a snapshot of a board is complete: a job missing from tomorrow's snapshot
has been taken down. That is what makes first_seen/last_seen reliable later.
"""

from __future__ import annotations

import logging
import re
import urllib.parse
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from xml.etree import ElementTree

from jobpipe import roles, salary
from jobpipe.bronze import RawItem
from jobpipe.http import HttpClient, HttpError

logger = logging.getLogger(__name__)

GREENHOUSE_API = "https://boards-api.greenhouse.io/v1/boards"
LEVER_API = "https://api.lever.co/v0/postings"
ASHBY_API = "https://api.ashbyhq.com/posting-api/job-board"
SMARTRECRUITERS_API = "https://api.smartrecruiters.com/v1/companies"
WORKABLE_API = "https://apply.workable.com/api/v1/widget/accounts"
LEVER_PAGE_SIZE = 100
SMARTRECRUITERS_PAGE_SIZE = 100
HOST_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")


@dataclass(frozen=True)
class BoardFailure:
    ats: str
    board: str
    error: str


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _path(board: str) -> str:
    """Board names are user input; Ashby names may contain spaces ("Acme AI")."""
    return urllib.parse.quote(board, safe="")


def greenhouse_jobs(http: HttpClient, board: str) -> Iterator[RawItem]:
    data = http.get_json(f"{GREENHOUSE_API}/{_path(board)}/jobs", {"content": "true"})
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
            f"{LEVER_API}/{_path(board)}", {"mode": "json", "skip": skip, "limit": LEVER_PAGE_SIZE}
        )
        for job in page:
            created = job.get("createdAt")
            yield RawItem(
                source_id=f"{board}:{job['id']}",
                event_time=datetime.fromtimestamp(created / 1000, tz=UTC) if created else None,
                payload={"board": board, "job": job},
            )
        if len(page) < LEVER_PAGE_SIZE:
            return
        skip += LEVER_PAGE_SIZE


def ashby_jobs(http: HttpClient, board: str) -> Iterator[RawItem]:
    data = http.get_json(f"{ASHBY_API}/{_path(board)}", {"includeCompensation": "true"})
    for job in data.get("jobs", []):
        yield RawItem(
            source_id=f"{board}:{job['id']}",
            event_time=_parse_iso(job.get("publishedAt")),
            payload={"board": board, "job": job},
        )


def _host_label(board: str) -> str:
    """Recruitee and Personio put the board in the host name, so only a plain label is accepted."""
    if not HOST_LABEL.fullmatch(board):
        raise ValueError(f"not a valid board name: {board!r}")
    return board


def _wants_detail(job: Mapping[str, Any]) -> bool:
    """A SmartRecruiters posting worth a second request for its text: in the region and technical."""
    country = ((job.get("location") or {}).get("country") or "").lower()
    in_region = country in {"ch", "es"} | salary.EUROPE_ISO
    return in_region and roles.role_of(job.get("name")) != roles.OTHER.key


def smartrecruiters_jobs(http: HttpClient, board: str) -> Iterator[RawItem]:
    """Every posting of the company; the full text only for regional, technical ones.

    The list has no description and SmartRecruiters is used by large employers
    (thousands of postings, most of them outside tech or outside Europe), so the
    detail request is spent only where technologies will be looked for.
    """
    listing: list[dict[str, Any]] = []
    while True:
        page = http.get_json(
            f"{SMARTRECRUITERS_API}/{_path(board)}/postings",
            {"limit": SMARTRECRUITERS_PAGE_SIZE, "offset": len(listing)},
        )
        content = page.get("content") or []
        listing.extend(content)
        if not content or len(listing) >= page.get("totalFound", 0):
            break
    for job in listing:
        if _wants_detail(job):
            job = http.get_json(f"{SMARTRECRUITERS_API}/{_path(board)}/postings/{_path(job['id'])}")
        yield RawItem(
            source_id=f"{board}:{job['id']}",
            event_time=_parse_iso(job.get("releasedDate")),
            payload={"board": board, "job": job},
        )


def workable_jobs(http: HttpClient, board: str) -> Iterator[RawItem]:
    data = http.get_json(f"{WORKABLE_API}/{_path(board)}", {"details": "true"})
    for job in data.get("jobs", []):
        published = job.get("published_on") or job.get("created_at")
        yield RawItem(
            source_id=f"{board}:{job['shortcode']}",
            event_time=_parse_iso(f"{published}T00:00:00+00:00") if published else None,
            payload={"board": board, "job": job},
        )


def recruitee_jobs(http: HttpClient, board: str) -> Iterator[RawItem]:
    data = http.get_json(f"https://{_host_label(board)}.recruitee.com/api/offers/")
    for job in data.get("offers", []):
        published = job.get("published_at") or job.get("created_at")  # "2026-11-03 20:08:14 UTC"
        yield RawItem(
            source_id=f"{board}:{job['id']}",
            event_time=_parse_iso(published.replace(" UTC", "+00:00")) if published else None,
            payload={"board": board, "job": job},
        )


def _personio_position(position: ElementTree.Element) -> dict[str, Any]:
    def text(tag: str) -> str | None:
        value = position.findtext(tag)
        return value.strip() if value and value.strip() else None

    return {
        "id": text("id"),
        "name": text("name"),
        "office": text("office"),
        "additionalOffices": [o.text.strip() for o in position.iterfind("additionalOffices/office") if o.text],
        "department": text("department"),
        "subcompany": text("subcompany"),
        "employmentType": text("employmentType"),
        "seniority": text("seniority"),
        "schedule": text("schedule"),
        "keywords": text("keywords"),
        "createdAt": text("createdAt"),
        "descriptions": [
            {"name": (d.findtext("name") or "").strip(), "value": (d.findtext("value") or "").strip()}
            for d in position.iterfind("jobDescriptions/jobDescription")
        ],
    }


def personio_jobs(http: HttpClient, board: str) -> Iterator[RawItem]:
    """Personio only offers XML; each position becomes a plain dict so bronze stays JSON lines."""
    body = http.get(
        f"https://{_host_label(board)}.jobs.personio.de/xml",
        {"language": "en"},
        headers={"Accept": "application/xml"},
    )
    for position in ElementTree.fromstring(body).iterfind("position"):
        job = _personio_position(position)
        job["url"] = f"https://{board}.jobs.personio.de/job/{job['id']}"
        job["xml"] = ElementTree.tostring(position, encoding="unicode")  # the raw response, as ADR 0001 asks
        yield RawItem(
            source_id=f"{board}:{job['id']}",
            event_time=_parse_iso(job["createdAt"]),
            payload={"board": board, "job": job},
        )


FETCHERS: dict[str, Callable[[HttpClient, str], Iterator[RawItem]]] = {
    "greenhouse": greenhouse_jobs,
    "lever": lever_jobs,
    "ashby": ashby_jobs,
    "smartrecruiters": smartrecruiters_jobs,
    "workable": workable_jobs,
    "recruitee": recruitee_jobs,
    "personio": personio_jobs,
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
        except (HttpError, KeyError, TypeError, ValueError, ElementTree.ParseError) as error:
            logger.warning("%s board %r failed: %s", ats, board, error)
            failures.append(BoardFailure(ats, board, str(error)))
            continue
        logger.info("%s board %r: %d jobs", ats, board, len(items))
        yield from items
