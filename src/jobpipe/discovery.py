"""Find public ATS boards of companies hiring in a region (Switzerland, Spain, Europe).

The ATS endpoints read one company at a time and there is no public list of
boards. HN postings often link to the company's Greenhouse, Lever or Ashby
page, so the HN bronze data doubles as a discovery source. The output is a
suggestion list to review by hand, not something applied automatically.
"""

from __future__ import annotations

import html
import re
import urllib.parse
from collections import Counter
from typing import Iterable, Mapping

REGION_KEYWORDS: dict[str, str] = {
    "ch": r"switzerland|swiss|z[uü]rich|geneva|gen[eè]ve|lausanne|basel|bern|zug|lugano|winterthur",
    "es": r"spain|espa[ñn]a|madrid|barcelona|valencia|sevilla|seville|m[aá]laga|bilbao|zaragoza",
    "eu": (
        r"europe|european union|emea|cet|berlin|munich|m[uü]nchen|hamburg|amsterdam|rotterdam"
        r"|dublin|paris|lisbon|vienna|wien|stockholm|copenhagen|helsinki|oslo|warsaw|prague|london"
    ),
}


def location_pattern(regions: Iterable[str]) -> re.Pattern[str]:
    unknown = set(regions) - set(REGION_KEYWORDS)
    if unknown:
        raise ValueError(f"unknown regions: {sorted(unknown)}")
    alternatives = "|".join(REGION_KEYWORDS[region] for region in regions)
    return re.compile(rf"\b({alternatives})\b", re.IGNORECASE)


DEFAULT_LOCATION_PATTERN = location_pattern(["ch"])

# EU-hosted boards (job-boards.eu.greenhouse.io, jobs.eu.lever.co) use other API
# hosts and are deliberately not matched until those hosts are supported.
BOARD_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "greenhouse": [
        re.compile(r"(?<![.\w])(?:boards|job-boards)\.greenhouse\.io/(?!embed\b)([A-Za-z0-9_-]+)"),
        re.compile(r"(?<![.\w])(?:boards|job-boards)\.greenhouse\.io/embed/job_board\?for=([A-Za-z0-9_-]+)"),
    ],
    "lever": [re.compile(r"(?<![.\w])jobs\.lever\.co/([A-Za-z0-9_.-]+)")],
    "ashby": [re.compile(r"(?<![.\w])jobs\.ashbyhq\.com/([A-Za-z0-9_.%-]+)")],
}


def extract_boards(text: str) -> dict[str, set[str]]:
    plain = html.unescape(text)
    found: dict[str, set[str]] = {}
    for ats, patterns in BOARD_PATTERNS.items():
        for pattern in patterns:
            for match in pattern.finditer(plain):
                slug = urllib.parse.unquote(match.group(1)).rstrip(".")
                if slug:
                    found.setdefault(ats, set()).add(slug)
    return found


def discover_from_hn(
    records: Iterable[Mapping],
    location_pattern: re.Pattern[str] = DEFAULT_LOCATION_PATTERN,
) -> dict[str, Counter]:
    """Count, per ATS, how many matching HN postings link to each board."""
    counts: dict[str, Counter] = {ats: Counter() for ats in BOARD_PATTERNS}
    for record in records:
        text = record.get("payload", {}).get("comment", {}).get("text") or ""
        if not location_pattern.search(html.unescape(text)):
            continue
        for ats, slugs in extract_boards(text).items():
            counts[ats].update(slugs)
    return counts
