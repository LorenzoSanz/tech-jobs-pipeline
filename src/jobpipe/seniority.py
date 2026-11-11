"""Seniority of a posting, from its title.

Only the title is used: descriptions mention "senior colleagues" or "lead the
migration" too often to tell anything. A title with no marker is
``unspecified``, not ``mid``: most of them are mid-level, but that is a guess
and the dashboards say so instead of hiding it.

Levels are checked in order and the first match wins, so "Senior Staff
Engineer" is lead and "Head of Data Interns" is head. Roman numerals follow
the common ladder (Engineer I, II, III) and are only read right after an
individual-contributor title: "Manager II" is a management step, not mid-level.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Level:
    key: str
    en: str
    es: str
    pattern: str = ""

    def label(self, lang: str) -> str:
        return self.es if lang == "es" else self.en


# "Engineer II", "Data Scientist III": a ladder step only after an individual-contributor title.
_IC = r"(?:engineer|developer|scientist|analyst|designer|architect|administrator|programmer)\s+"
_NUMERAL = r"(?=\s*(?:$|[-,(|/–]))"
LEVELS: tuple[Level, ...] = (
    Level("intern", "Intern / trainee", "Prácticas / becario",
          r"\bintern(ship)?s?\b|praktik(um|ant)|werkstudent|working student|\btrainee|\bapprenti|lehrstelle|\blernende|lehrling"
          r"|\bbecari[oa]|pr[aá]cticas|stagiaire|alternan(ce|t)|summer student|thesis"),
    Level("head", "Head / director", "Head / dirección",
          r"\bhead of\b|\bdirector\b|\bvp\b|vice president|\bchief\b|\bc[tid]o\b|\bciso\b"),
    Level("lead", "Lead / staff / principal", "Lead / staff / principal",
          r"\bstaff\b|\bprincipal\b|\blead\b|\bdistinguished\b"),
    Level("senior", "Senior", "Senior", rf"\bsenior\b|\bs[eé]nior\b|\bsr\b\.?|{_IC}(iii|iv){_NUMERAL}"),
    Level("junior", "Junior", "Junior",
          rf"\bjunior\b|\bj[uú]nior\b|\bjr\b\.?|\bgraduate\b|new grad|entry[- ]level|\bassociate\b|{_IC}i{_NUMERAL}"),
    Level("mid", "Mid-level", "Intermedio", rf"\bmid\b(?![- ]?market)|intermediate|\bmedior\b|{_IC}ii{_NUMERAL}"),
)  # fmt: skip
UNSPECIFIED = Level("unspecified", "Not stated", "Sin indicar")
ALL = LEVELS + (UNSPECIFIED,)
ORDER = tuple(level.key for level in ALL)

_COMPILED = tuple((level.key, re.compile(level.pattern, re.IGNORECASE)) for level in LEVELS)


def seniority_of(title: str | None) -> str:
    """Key of the first level whose pattern matches the title."""
    for key, pattern in _COMPILED:
        if title and pattern.search(title):
            return key
    return UNSPECIFIED.key
