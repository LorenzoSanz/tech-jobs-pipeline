"""Postings added by hand: `jobpipe add`.

FAANG career sites have no public API and some forbid automated access
(ADR 0009), so a posting found there is pasted in instead. Nothing is
fetched. The id comes from the URL, or from company, title and location when
there is none, so adding the same posting twice stores a new snapshot of it,
not a second job.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from jobpipe.bronze import RawItem

SOURCE = "manual"


def posting(
    title: str,
    company: str,
    location: str | None = None,
    country: str | None = None,
    url: str | None = None,
    description: str = "",
    added_at: datetime | None = None,
) -> RawItem:
    key = url or f"{company}|{title}|{location or ''}"
    return RawItem(
        source_id=hashlib.sha256(key.strip().lower().encode("utf-8")).hexdigest()[:16],
        event_time=added_at or datetime.now(UTC),
        payload={
            "title": title.strip(),
            "company": company.strip(),
            "location": location,
            "country": country.lower() if country else None,
            "url": url,
            "description": description,
        },
    )
