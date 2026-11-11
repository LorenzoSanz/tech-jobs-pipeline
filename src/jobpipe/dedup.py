"""Postings that advertise the same job, so it counts once.

One job often shows up several times: on the employer's board and on Adzuna,
or on one board once per city. Two postings are the same job when they have

- the same company, once legal forms, places and punctuation are dropped
  ("SOPHiA GENETICS SA" and the board "sophia-genetics", "Google Switzerland
  GmbH" and "Google"; see employers.py);
- the same title, once gender markers ("(m/w/d)"), city names and
  punctuation are dropped ("Data Engineer - Zürich" and "Data Engineer");
- the same first country, so "Data Engineer" in Zurich and in Madrid are two jobs;
- and were online within ``GAP`` of each other: the same title a year later
  is a new opening, not the same one.

HN comments are never merged: one comment often announces several jobs.

Each job keeps all its postings in silver. They are ranked, and rank 0 stands
for the job in counts and lists: an open posting before a closed one, the
employer's own board before Adzuna, then the one with a description, then the
first seen. Headcount is unknown, so a job advertised twice in one city still
counts once.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

from jobpipe import employers, jobs, places

GAP = timedelta(days=30)
NEVER_MERGED = frozenset({"hn"})

GENDER = re.compile(
    r"\(?\b(?:[mwfdhx]|nb)(?:\s*/\s*(?:[mwfdhx]|nb)){1,3}\b\)?|\((?:all genders|alle geschlechter|gn\*?)\)"
    r"|\ball genders\b",
    re.IGNORECASE,
)
WORK_MODE = re.compile(r"\b(remote|hybrid|on-?site|100\s*%|full[- ]time|part[- ]time)\b", re.IGNORECASE)
# City names are dropped from titles, country names are not: "Account Executive
# (Malaysia Market)" and "(Philippines Market)" are two jobs. Cities that are
# also words in titles stay.
COMMON_WORDS = frozenset({"nice", "reading", "essen"})
CITY_NAMES = re.compile(
    r"\b(" + "|".join(sorted(
        (re.escape(name) for name in places.CITY_BY_KEY if name not in COMMON_WORDS), key=len, reverse=True,
    )) + r")\b"
)  # fmt: skip


def title_key(title: str | None) -> str:
    text = WORK_MODE.sub(" ", GENDER.sub(" ", title or ""))
    text = CITY_NAMES.sub(" ", places.fold(text))
    return " ".join(re.sub(r"[^a-z0-9+#]+", " ", text).split())


def _time(value: str | None) -> datetime:
    moment = datetime.fromisoformat(value) if value else datetime.min
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _preference(item: Any) -> tuple:
    posting = item.posting
    return (
        not item.is_open,
        jobs.SOURCES.index(posting.source) if posting.source in jobs.SOURCES else len(jobs.SOURCES),
        not posting.description,
        item.first_seen,
        posting.source,
        posting.source_id,
    )


def group(items: Sequence[Any]) -> list[tuple[str, int]]:
    """(job id, rank) for each item, in the same order.

    Items need ``posting`` (a jobs.Posting), ``first_seen``, ``last_seen`` and
    ``is_open``. The job id is "source:source_id" of its rank 0 posting.
    """
    by_key: dict[tuple, list[int]] = defaultdict(list)
    for n, item in enumerate(items):
        posting = item.posting
        employer = employers.employer_of(posting.company)
        company = employers.employer_key(employer.name or posting.company)
        title = title_key(posting.title)
        if posting.source in NEVER_MERGED or not company or not title:
            by_key[("single", n)].append(n)
        else:
            by_key[(company, title, posting.countries[:1])].append(n)

    result: list[tuple[str, int]] = [("", 0)] * len(items)
    for members in by_key.values():
        members.sort(key=lambda n: _time(items[n].posting.published or items[n].first_seen))
        clusters: list[list[int]] = []
        end = None
        for n in members:
            start = _time(items[n].posting.published or items[n].first_seen)
            if end is None or start > end + GAP:
                clusters.append([])
                end = start
            clusters[-1].append(n)
            end = max(end, _time(items[n].last_seen))
        for cluster in clusters:
            cluster.sort(key=lambda n: _preference(items[n]))
            first = items[cluster[0]].posting
            job_id = f"{first.source}:{first.source_id}"
            for rank, n in enumerate(cluster):
                result[n] = (job_id, rank)
    return result
