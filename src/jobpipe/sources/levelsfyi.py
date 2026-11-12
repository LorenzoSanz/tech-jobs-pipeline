"""Levels.fyi Compensation API: salary benchmarks by job family and location.

Only the official REST API is used. The Levels.fyi Terms of Use forbid
collecting any part of the site by automated means, public pages included,
unless Levels.fyi permits it in writing. See docs/adr/0004.

The API needs a key from a Levels.fyi employer account (``LEVELS_FYI_API_KEY``).
Without one, use the free Levels.fyi MCP server from an AI assistant for
personal lookups instead; that data is not stored here.

Amounts come back in USD unless stated otherwise. Data shown publicly must say
"Data source: Levels.fyi (https://www.levels.fyi)".
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any

from jobpipe.bronze import RawItem
from jobpipe.http import HttpClient

API = "https://api.levels.fyi/v1/api"
SOURCE = "levelsfyi"
ATTRIBUTION = "Data source: Levels.fyi (https://www.levels.fyi)"
MAX_COMPARED_LOCATIONS = 7


@dataclass(frozen=True)
class BenchmarkQuery:
    job_family: str = "software-engineer"
    locations: Sequence[str] = ()
    salary_type: str = "total_compensation"
    time_range: str = "0-12"
    focus_tags: Sequence[str] = field(default_factory=tuple)


def _headers(api_key: str) -> dict[str, str]:
    return {"x-api-key": api_key}


def _filters(query: BenchmarkQuery) -> dict[str, Any]:
    params: dict[str, Any] = {"salaryType": query.salary_type, "timeRange": query.time_range}
    if query.focus_tags:
        params["focusTagSlugs"] = list(query.focus_tags)
    return params


def lookup(http: HttpClient, api_key: str, kind: str, text: str) -> Any:
    """Resolve a human name ("Zurich", "data engineer") into Levels.fyi slugs."""
    return http.get_json(f"{API}/lookup/{kind}", {"q": text}, _headers(api_key))


def benchmarks(http: HttpClient, api_key: str, query: BenchmarkQuery) -> Iterator[RawItem]:
    """p10-p90 per location, then p25-p75 by years of experience in each location."""
    headers = _headers(api_key)
    base = f"{API}/benchmark/{query.job_family}"
    filters = _filters(query)
    locations = list(query.locations)
    tag = ",".join(query.focus_tags)
    context = {
        "job_family": query.job_family,
        "salary_type": query.salary_type,
        "time_range": query.time_range,
        "focus_tags": list(query.focus_tags),
        "currency": "USD",
    }

    for start in range(0, len(locations), MAX_COMPARED_LOCATIONS):
        chunk = locations[start : start + MAX_COMPARED_LOCATIONS]
        rows = http.get_json(
            f"{base}/locations/compare", {**filters, "compareToLocations": chunk}, headers
        )
        for row in rows:
            yield RawItem(
                source_id=f"{query.job_family}:{tag}:{query.salary_type}:location:{row['locationSlug']}",
                payload={**context, "kind": "location_percentiles", "data": row},
            )

    for location in locations:
        rows = http.get_json(
            f"{base}/by-experience", {**filters, "locationSlugs": [location]}, headers
        )
        for row in rows:
            yield RawItem(
                source_id=(
                    f"{query.job_family}:{tag}:{query.salary_type}:yoe:{location}:{row['yoeRange']}"
                ),
                payload={**context, "kind": "by_experience", "location": location, "data": row},
            )
