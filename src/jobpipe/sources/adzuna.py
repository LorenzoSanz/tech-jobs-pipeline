"""Adzuna job search API for Switzerland.

An aggregator: it adds breadth (many employers that do not use a public ATS)
at the cost of truncated descriptions and duplicates across boards, which the
silver layer has to resolve. Requires a free key from developer.adzuna.com.
Adzuna's terms require attribution when its data is shown publicly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterator

from jobpipe.bronze import RawItem
from jobpipe.http import HttpClient

API = "https://api.adzuna.com/v1/api/jobs"
RESULTS_PER_PAGE = 50


@dataclass(frozen=True)
class AdzunaCredentials:
    app_id: str
    app_key: str


@dataclass(frozen=True)
class AdzunaQuery:
    country: str = "ch"
    category: str | None = "it-jobs"
    what: str | None = None
    max_days_old: int | None = None
    max_pages: int = 20


def _parse_created(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def ingest(http: HttpClient, credentials: AdzunaCredentials, query: AdzunaQuery) -> Iterator[RawItem]:
    params: dict[str, object] = {
        "app_id": credentials.app_id,
        "app_key": credentials.app_key,
        "results_per_page": RESULTS_PER_PAGE,
        "sort_by": "date",
        "content-type": "application/json",
    }
    if query.category:
        params["category"] = query.category
    if query.what:
        params["what"] = query.what
    if query.max_days_old is not None:
        params["max_days_old"] = query.max_days_old

    for page in range(1, query.max_pages + 1):
        data = http.get_json(f"{API}/{query.country}/search/{page}", params)
        results = data.get("results") or []
        for job in results:
            yield RawItem(
                source_id=f"{query.country}:{job['id']}",
                event_time=_parse_created(job.get("created")),
                payload={"country": query.country, "job": job},
            )
        if len(results) < RESULTS_PER_PAGE:
            return
