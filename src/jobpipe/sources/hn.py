"""Hacker News "Ask HN: Who is hiring?" threads, through the Algolia HN API.

The monthly threads go back to 2011, which makes them the longest consistent
history of tech hiring available for free. Each top-level comment is one
posting. Replies are dropped: they are questions to the poster, not postings.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Iterator

from jobpipe.bronze import RawItem
from jobpipe.http import HttpClient

logger = logging.getLogger(__name__)

API = "https://hn.algolia.com/api/v1"
THREAD_TITLE_PREFIX = "Ask HN: Who is hiring?"
SOURCE = "hn"


@dataclass(frozen=True)
class HiringThread:
    id: int
    title: str
    created_at: datetime


def _timestamp(item: dict[str, Any]) -> datetime | None:
    if item.get("created_at_i") is not None:
        return datetime.fromtimestamp(int(item["created_at_i"]), tz=timezone.utc)
    if item.get("created_at"):
        return datetime.fromisoformat(item["created_at"].replace("Z", "+00:00"))
    return None


def find_hiring_threads(http: HttpClient, since: date | None = None) -> list[HiringThread]:
    """All monthly hiring threads, newest first, optionally stopping at ``since``."""
    threads: list[HiringThread] = []
    page = 0
    while True:
        data = http.get_json(
            f"{API}/search_by_date",
            {"tags": "story,author_whoishiring", "hitsPerPage": 100, "page": page},
        )
        for hit in data.get("hits", []):
            created = _timestamp(hit)
            if created is None:
                continue
            if since is not None and created.date() < since:
                return threads
            title = hit.get("title") or ""
            if title.startswith(THREAD_TITLE_PREFIX):
                threads.append(HiringThread(int(hit["objectID"]), title, created))
        page += 1
        if page >= int(data.get("nbPages", 0)):
            return threads


def fetch_postings(http: HttpClient, thread: HiringThread) -> Iterator[RawItem]:
    """One RawItem per live top-level comment of a thread."""
    story = http.get_json(f"{API}/items/{thread.id}")
    for comment in story.get("children") or []:
        if not comment.get("text") or not comment.get("author"):
            continue  # deleted or dead comment
        created = _timestamp(comment)
        yield RawItem(
            source_id=str(comment["id"]),
            event_time=created,
            payload={
                "thread": {
                    "id": thread.id,
                    "title": thread.title,
                    "created_at": thread.created_at.isoformat(),
                },
                "comment": {
                    "id": comment["id"],
                    "author": comment["author"],
                    "created_at": created.isoformat() if created else None,
                    "text": comment["text"],
                },
            },
        )


def ingest(http: HttpClient, since: date | None = None) -> Iterator[RawItem]:
    threads = find_hiring_threads(http, since)
    logger.info("found %d hiring threads", len(threads))
    for thread in reversed(threads):  # oldest first: the bronze file reads chronologically
        logger.info("fetching %s", thread.title)
        yield from fetch_postings(http, thread)
