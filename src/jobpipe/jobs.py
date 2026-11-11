"""One flat view of every collected posting, for browsing and searching.

Reads the newest snapshot of each posting in bronze and keeps only what a
person scanning offers needs: title, company, place, link, dates, region and
any salary range found for it. This is a read model for the UI, not the silver
layer: no deduplication across sources yet.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Mapping

from jobpipe import salary
from jobpipe.bronze import read_records

SOURCES = ("greenhouse", "lever", "ashby", "adzuna", "hn")


@dataclass(frozen=True)
class Posting:
    source: str
    source_id: str
    title: str
    company: str | None
    location: str | None
    country: str | None
    url: str | None
    published: str | None
    fetched_at: str | None
    regions: tuple[str, ...]
    salaries: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    description: str = field(default="", repr=False)  # plain text, for technology extraction

    def text(self) -> str:
        return " ".join(filter(None, [self.title, self.company, self.location])).lower()


def _greenhouse(record: Mapping[str, Any]) -> dict[str, Any]:
    job = record["payload"]["job"]
    return {
        "title": job.get("title"),
        "company": job.get("company_name") or record["payload"].get("board"),
        "location": (job.get("location") or {}).get("name"),
        "url": job.get("absolute_url"),
        "description": job.get("content"),
    }


def _lever(record: Mapping[str, Any]) -> dict[str, Any]:
    job = record["payload"]["job"]
    return {
        "title": job.get("text"),
        "company": record["payload"].get("board"),
        "location": (job.get("categories") or {}).get("location"),
        "country": job.get("country"),
        "url": job.get("hostedUrl"),
        "description": " ".join(
            [job.get("descriptionPlain") or "", job.get("additionalPlain") or ""]
            + [f"{item.get('text', '')} {item.get('content', '')}" for item in job.get("lists") or []]
        ),
    }


def _ashby(record: Mapping[str, Any]) -> dict[str, Any]:
    job = record["payload"]["job"]
    address = (job.get("address") or {}).get("postalAddress") or {}
    return {
        "title": job.get("title"),
        "company": record["payload"].get("board"),
        "location": job.get("location"),
        "country": address.get("addressCountry"),
        "url": job.get("jobUrl"),
        "description": job.get("descriptionPlain"),
    }


def _adzuna(record: Mapping[str, Any]) -> dict[str, Any]:
    job = record["payload"]["job"]
    return {
        "title": salary.plain_text(job.get("title") or ""),
        "company": (job.get("company") or {}).get("display_name"),
        "location": (job.get("location") or {}).get("display_name"),
        "country": record["payload"].get("country"),
        "url": job.get("redirect_url"),
        "description": job.get("description"),
    }


def _hn(record: Mapping[str, Any]) -> dict[str, Any]:
    comment = record["payload"]["comment"]
    header = salary.plain_text(comment["text"].split("<p>")[0]).strip()
    company = header.split("|")[0].strip() if "|" in header else None
    return {
        "title": header[:240],
        "company": company[:80] if company else None,
        "location": header,
        "url": f"https://news.ycombinator.com/item?id={comment['id']}",
        "description": comment["text"],
    }


FIELDS: dict[str, Callable[[Mapping[str, Any]], dict[str, Any]]] = {
    "greenhouse": _greenhouse,
    "lever": _lever,
    "ashby": _ashby,
    "adzuna": _adzuna,
    "hn": _hn,
}


def _salary_view(posted: salary.PostedSalary) -> dict[str, Any]:
    return {
        "currency": posted.currency,
        "min": posted.min_annual,
        "max": posted.max_annual,
        "period": posted.period,
        "predicted": posted.predicted,
        "tier": posted.tier,
    }


def load(data_dir: Path, sources: Iterable[str] = SOURCES, hn_days: int | None = 120) -> list[Posting]:
    """Every posting, newest first. HN is cut to the last ``hn_days`` (it goes back to 2011)."""
    cutoff = None
    if hn_days is not None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=hn_days)).isoformat()
    postings: list[Posting] = []
    for source in sources:
        records = salary.latest(read_records(data_dir, source))
        if source == "hn" and cutoff:
            records = [r for r in records if (r.get("event_time") or "") >= cutoff]
        for record in records:
            posting = to_posting(source, record)
            if posting is not None:
                postings.append(posting)
    postings.sort(key=lambda p: p.published or p.fetched_at or "", reverse=True)
    return postings


def to_posting(source: str, record: Mapping[str, Any]) -> Posting | None:
    try:
        fields = FIELDS[source](record)
        found = list(salary.EXTRACTORS[source](record))
    except (KeyError, TypeError, ValueError, AttributeError):
        return None
    if not fields.get("title"):
        return None
    location, country = fields.get("location"), fields.get("country")
    return Posting(
        source=source,
        source_id=record["source_id"],
        title=fields["title"],
        company=fields.get("company"),
        location=location if source != "hn" else None,
        country=country,
        url=fields.get("url"),
        published=record.get("event_time"),
        fetched_at=record.get("fetched_at"),
        regions=tuple(sorted(salary.regions_of(location, country))),
        salaries=tuple(_salary_view(s) for s in found),
        description=salary.plain_text(fields.get("description") or ""),
    )


def search(
    postings: Iterable[Posting],
    query: str = "",
    regions: Iterable[str] = (),
    sources: Iterable[str] = (),
    with_salary: bool = False,
) -> Iterator[Posting]:
    words = query.lower().split()
    wanted_regions, wanted_sources = set(regions), set(sources)
    for posting in postings:
        if wanted_sources and posting.source not in wanted_sources:
            continue
        if wanted_regions and not wanted_regions.intersection(posting.regions):
            continue
        if with_salary and not any(not s["predicted"] for s in posting.salaries):
            continue
        if words:
            text = posting.text()
            if not all(word in text for word in words):
                continue
        yield posting
