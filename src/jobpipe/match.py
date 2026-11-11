"""How well a posting fits you, from your profile (config/profile.toml).

A posting fits when its role family, region and title pass the profile's
filters. Its score is the share of the technologies it asks for that you
know: 3 of 4 is 75 %. A posting that names no catalogued technology gets no
score rather than a perfect one, and sorts after the scored ones.

The score is deliberately simple. Postings list "nice to have" tools next to
requirements and nothing separates them reliably, so a weighted score would
look precise without being so. What it is good for is ordering a long list
and showing what you lack. Lists are ordered by ``Match.rank``, which keeps a
posting that names a single tool you know from topping one that names five.
"""

from __future__ import annotations

import re
import tomllib
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from jobpipe import roles, tech

REGIONS = frozenset({"ch", "es", "eu", "other"})


class ProfileError(ValueError):
    pass


@dataclass(frozen=True)
class Profile:
    skills: frozenset[str]
    roles: frozenset[str] = frozenset()
    regions: frozenset[str] = frozenset()
    exclude_title: re.Pattern[str] | None = None


@dataclass(frozen=True)
class Match:
    fits: bool
    score: float | None
    have: tuple[str, ...]
    missing: tuple[str, ...]

    @property
    def rank(self) -> float:
        """Sort key: the score, smoothed so one known tool of one is not a perfect match.

        (have + 1) / (asked + 3): 1 of 1 ranks below 3 of 4 and 2 of 2.
        Postings that name no technology rank last.
        """
        if self.score is None:
            return -1.0
        return (len(self.have) + 1) / (len(self.have) + len(self.missing) + 3)


def _keys(data: dict, name: str, valid: Iterable[str]) -> frozenset[str]:
    values = data.get(name, [])
    if not isinstance(values, list):
        raise ProfileError(f"{name} must be a list")
    valid = set(valid)
    unknown = sorted(set(values) - valid)
    if unknown:
        raise ProfileError(f"unknown {name}: {', '.join(unknown)}. Valid: {', '.join(sorted(valid))}")
    return frozenset(values)


def parse_profile(text: str) -> Profile:
    data = tomllib.loads(text)
    exclude = data.get("exclude_title")
    try:
        pattern = re.compile(exclude, re.IGNORECASE) if exclude else None
    except re.error as error:
        raise ProfileError(f"exclude_title is not a valid regex: {error}") from error
    profile = Profile(
        skills=_keys(data, "skills", tech.BY_KEY),
        roles=_keys(data, "roles", (family.key for family in roles.ALL)),
        regions=_keys(data, "regions", REGIONS),
        exclude_title=pattern,
    )
    if not profile.skills:
        raise ProfileError("skills is empty: list the technologies you know")
    return profile


def load_profile(path: Path) -> Profile:
    try:
        return parse_profile(Path(path).read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise ProfileError(f"{path}: {error}") from error


def match(profile: Profile, title: str, role: str, regions: Iterable[str], technologies: Iterable[str]) -> Match:
    technologies = tuple(technologies)
    fits = (
        (not profile.roles or role in profile.roles)
        and (not profile.regions or bool(profile.regions & (set(regions) or {"other"})))
        and not (profile.exclude_title and profile.exclude_title.search(title))
    )
    have = tuple(t for t in technologies if t in profile.skills)
    missing = tuple(t for t in technologies if t not in profile.skills)
    score = len(have) / len(technologies) if technologies else None
    return Match(fits, score, have, missing)


def gaps(matches: Iterable[Match]) -> list[tuple[str, int, float]]:
    """Technologies you lack, with how many fitting postings ask for them and what share that is."""
    fitting = [m for m in matches if m.fits and m.score is not None]
    counts = Counter(t for m in fitting for t in m.missing)
    return [(key, n, n / len(fitting)) for key, n in counts.most_common()]
