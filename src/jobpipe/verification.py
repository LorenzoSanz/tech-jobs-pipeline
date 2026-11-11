"""Check candidate ATS boards against the live APIs before trusting them.

discover-boards only says that a board was linked from an HN posting that
mentioned the region. The board may be gone, renamed, or hire elsewhere today.
Verification reads each board once and keeps it only if it answers and at
least one open job is located in the region.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any
from xml.etree import ElementTree

from jobpipe.http import HttpClient, HttpError
from jobpipe.sources import ats

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BoardCheck:
    ats: str
    board: str
    total_jobs: int
    regional_jobs: int
    error: str | None = None

    @property
    def keep(self) -> bool:
        return self.error is None and self.regional_jobs > 0


def _country_name(code: str | None) -> str | None:
    """SmartRecruiters gives only a country code; the region patterns match names."""
    return {"ch": "Switzerland", "es": "Spain"}.get((code or "").lower(), code)


def job_locations(ats_name: str, job: Mapping[str, Any]) -> list[str]:
    """Every location string an ATS gives for one job."""
    found: list[str | None] = []
    if ats_name == "greenhouse":
        found.append((job.get("location") or {}).get("name"))
        found.extend(office.get("name") for office in job.get("offices") or [])
        found.extend(office.get("location") for office in job.get("offices") or [])
    elif ats_name == "lever":
        categories = job.get("categories") or {}
        found.append(categories.get("location"))
        found.extend(categories.get("allLocations") or [])
        found.append(job.get("country"))
    elif ats_name == "ashby":
        found.append(job.get("location"))
        found.extend(extra.get("location") for extra in job.get("secondaryLocations") or [])
        address = (job.get("address") or {}).get("postalAddress") or {}
        found.extend([address.get("addressLocality"), address.get("addressCountry")])
    elif ats_name == "smartrecruiters":
        location = job.get("location") or {}
        found.extend([location.get("fullLocation"), _country_name(location.get("country"))])
    elif ats_name == "workable":
        found.extend([job.get("city"), job.get("country")])
        found.extend(loc.get("country") for loc in job.get("locations") or [])
    elif ats_name == "recruitee":
        found.extend([job.get("location"), job.get("country")])
        found.extend(loc.get("country") for loc in job.get("locations") or [])
    elif ats_name == "personio":
        found.append(job.get("office"))
        found.extend(job.get("additionalOffices") or [])
    return [value for value in found if isinstance(value, str) and value]


def check_board(
    http: HttpClient, ats_name: str, board: str, pattern: re.Pattern[str]
) -> BoardCheck:
    try:
        jobs = [item.payload["job"] for item in ats.FETCHERS[ats_name](http, board)]
    except (HttpError, KeyError, TypeError, ValueError, ElementTree.ParseError) as error:
        return BoardCheck(ats_name, board, 0, 0, str(error))
    regional = sum(
        1 for job in jobs if any(pattern.search(loc) for loc in job_locations(ats_name, job))
    )
    return BoardCheck(ats_name, board, len(jobs), regional)


def verify(
    http: HttpClient,
    candidates: Mapping[str, Iterable[str]],
    pattern: re.Pattern[str],
) -> list[BoardCheck]:
    checks: list[BoardCheck] = []
    for ats_name, boards in candidates.items():
        if ats_name not in ats.FETCHERS:
            continue
        for board in boards:
            check = check_board(http, ats_name, board, pattern)
            logger.info(
                "%s %r: %d/%d regional%s",
                ats_name, board, check.regional_jobs, check.total_jobs,
                f" ({check.error})" if check.error else "",
            )
            checks.append(check)
    return checks


def render_toml(checks: Iterable[BoardCheck]) -> str:
    """Kept boards as a config/boards.toml body, most regional jobs first."""
    checks = list(checks)
    lines = [
        "# Boards that answered and have open jobs in the region.",
        "# Comment = regional jobs / all open jobs at verification time.",
    ]
    for ats_name in ats.FETCHERS:
        kept = sorted(
            (c for c in checks if c.ats == ats_name and c.keep),
            key=lambda c: (-c.regional_jobs, c.board),
        )
        lines += ["", f"[{ats_name}]", "boards = ["]
        lines += [f'  "{c.board}",  # {c.regional_jobs}/{c.total_jobs}' for c in kept]
        lines.append("]")
    dropped = [c for c in checks if not c.keep]
    if dropped:
        lines += ["", f"# Dropped {len(dropped)} boards:"]
        lines += [
            f"#   {c.ats}/{c.board}: " + ("unreachable" if c.error else f"0/{c.total_jobs} regional")
            for c in dropped
        ]
    return "\n".join(lines) + "\n"
