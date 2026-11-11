"""Adzuna job search API, per country (ch, es, de, nl, ...).

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


SALARY_SOURCE = "adzuna_salary"


@dataclass(frozen=True)
class SalaryQuery:
    """A salary benchmark: Adzuna's distribution of advertised salaries for a search."""

    country: str = "ch"
    what: str | None = None
    category: str | None = "it-jobs"
    history_months: int = 12


def _auth(credentials: AdzunaCredentials) -> dict[str, object]:
    return {
        "app_id": credentials.app_id,
        "app_key": credentials.app_key,
        "content-type": "application/json",
    }


def salary_benchmarks(
    http: HttpClient, credentials: AdzunaCredentials, query: SalaryQuery
) -> Iterator[RawItem]:
    """The salary histogram for a search, and the category's monthly average salary.

    Both are official Adzuna endpoints. The histogram answers "how many current
    postings advertise 60-70k for 'data engineer' in Switzerland", which is the
    market range to anchor a negotiation on. ``history`` takes a category, not
    keywords, so it is the trend of the whole category.
    """
    params = _auth(credentials)
    histogram_params = dict(params)
    if query.what:
        histogram_params["what"] = query.what
    if query.category:
        histogram_params["category"] = query.category
    histogram = http.get_json(f"{API}/{query.country}/histogram", histogram_params)
    key = f"{query.country}:histogram:{query.category or ''}:{query.what or ''}"
    yield RawItem(
        source_id=key,
        payload={
            "kind": "histogram",
            "country": query.country,
            "what": query.what,
            "category": query.category,
            "histogram": histogram.get("histogram") or {},
        },
    )

    if query.history_months > 0 and query.category:
        history_params = dict(params, category=query.category, months=query.history_months)
        history = http.get_json(f"{API}/{query.country}/history", history_params)
        yield RawItem(
            source_id=f"{query.country}:history:{query.category}",
            payload={
                "kind": "history",
                "country": query.country,
                "category": query.category,
                "month": history.get("month") or {},
            },
        )
