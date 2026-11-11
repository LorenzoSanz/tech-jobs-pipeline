"""How your CV and LinkedIn profile read against the postings that fit you.

Recruiters search LinkedIn for words and many application systems filter CVs
the same way, so a technology you use but never name is invisible. This finds
the technologies a document names (with the same catalogue as the postings,
src/jobpipe/tech.py) and compares them with what the open postings that fit
your profile ask for, weighted by how often each one is asked:

- coverage: the share of that demand a document names. Python asked by 60 % of
  the postings weighs more than Rust asked by 5 %.
- to add: asked, in your profile skills, but the document does not name it.
  The cheapest fix there is.
- to learn: asked, and not in your skills.
- not in your skills: the document names it but the profile does not list it,
  so the feed scores you as lacking it.
- titles: the role phrases the postings use most ("platform engineer",
  "ingeniero de datos") and whether the document says them; a LinkedIn
  headline without the title recruiters type is hard to find.

Documents stay on your machine: keep them in ``private/`` (gitignored). Text,
Markdown and .docx CVs are read; for a PDF, save it as text first. LinkedIn is
read from its official data export (Settings > Data privacy > Get a copy of
your data), only the headline, about, skills and positions; the rest of the
export (address, contacts, messages) is never opened.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

from jobpipe import dedup, tech

_WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def read_document(path: Path) -> str:
    """Text of a .txt, .md or .docx file."""
    path = Path(path)
    if path.suffix.lower() == ".docx":
        with zipfile.ZipFile(path) as archive:
            root = ElementTree.fromstring(archive.read("word/document.xml"))
        paragraphs = root.iter(f"{_WORD_NS}p")
        return "\n".join("".join(t.text or "" for t in p.iter(f"{_WORD_NS}t")) for p in paragraphs)
    if path.suffix.lower() == ".pdf":
        raise ValueError(f"{path}: PDF is not read; save the CV as .txt, .md or .docx")
    return path.read_text(encoding="utf-8-sig")


# Export file -> (column, section) pairs read from it.
LINKEDIN_FIELDS: dict[str, tuple[tuple[str, str], ...]] = {
    "Profile.csv": (("Headline", "headline"), ("Summary", "about")),
    "Skills.csv": (("Name", "skills"),),
    "Positions.csv": (("Title", "experience"), ("Description", "experience")),
}
LINKEDIN_SECTIONS = ("headline", "about", "skills", "experience")


def _csv_column(text: str, column: str) -> list[str]:
    """Values of one column. Some export files start with notes before the header."""
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if column in next(csv.reader([line]), [])), None)
    if start is None:
        return []
    return [row.get(column) or "" for row in csv.DictReader(io.StringIO("\n".join(lines[start:])))]


def read_linkedin(path: Path) -> dict[str, str]:
    """Headline, about, skills and experience text from a LinkedIn data export (.zip or folder)."""
    path = Path(path)
    files: dict[str, str] = {}
    if path.is_dir():
        for name in LINKEDIN_FIELDS:
            found = next(path.rglob(name), None)
            if found is not None:
                files[name] = found.read_text(encoding="utf-8-sig")
    else:
        with zipfile.ZipFile(path) as archive:
            for member in archive.namelist():
                name = member.rsplit("/", 1)[-1]
                if name in LINKEDIN_FIELDS:
                    files[name] = archive.read(member).decode("utf-8-sig")
    if not files:
        raise ValueError(f"{path}: no Profile.csv, Skills.csv or Positions.csv; is it a LinkedIn data export?")
    sections: dict[str, list[str]] = {section: [] for section in LINKEDIN_SECTIONS}
    for name, text in files.items():
        for column, section in LINKEDIN_FIELDS[name]:
            sections[section].extend(value for value in _csv_column(text, column) if value)
    return {section: "\n".join(values) for section, values in sections.items()}


@dataclass(frozen=True)
class Demand:
    """What the postings that fit you ask for."""

    postings: int
    technologies: Counter[str]  # key -> postings asking for it
    titles: Counter[str]  # role phrase in the title ("data engineer") -> postings

    def share(self, key: str) -> float:
        return self.technologies[key] / self.postings if self.postings else 0.0


_SENIORITY_WORDS = re.compile(
    r"\b(senior|sr|junior|jr|staff|principal|mid(-level)?|intern(ship)?|graduate|entry level"
    r"|i{1,3}|iv|[1-5])\b\.?",
    re.IGNORECASE,
)


ROLE_NOUNS = frozenset(
    "engineer engineers developer analyst scientist architect administrator consultant specialist".split()
)
# Spanish puts the noun first: "ingeniero de datos", "desarrollador backend".
ROLE_NOUNS_FIRST = frozenset(
    "ingeniero ingeniera desarrollador desarrolladora analista arquitecto arquitecta cientifico".split()
)
_NOT_A_QUALIFIER = frozenset("and or of for the a to with in at".split())


def title_terms(title: str) -> set[str]:
    """The role phrases recruiters search for: "Senior Backend Software Engineer, Payments" ->
    {"software engineer"}, "Ingeniero/a de Datos" -> {"ingeniero de datos"}."""
    title = re.sub(r"/[ao]\b", "", title, flags=re.IGNORECASE)  # "Ingeniero/a"
    words = dedup.title_key(_SENIORITY_WORDS.sub(" ", title)).split()
    terms = set()
    for i, word in enumerate(words):
        if word in ROLE_NOUNS and i > 0 and words[i - 1] not in _NOT_A_QUALIFIER:
            terms.add(f"{words[i - 1]} {word.removesuffix('s')}")
        elif word in ROLE_NOUNS_FIRST and i + 1 < len(words):
            follow = words[i + 1 : i + 3] if words[i + 1] == "de" else words[i + 1 : i + 2]
            if follow[-1] not in _NOT_A_QUALIFIER | {"de", "a"}:
                terms.add(" ".join([word, *follow]))
    return terms


def demand(postings: Iterable[tuple[str, Iterable[str]]]) -> Demand:
    """From (title, technologies) of each fitting posting."""
    n, technologies, titles = 0, Counter[str](), Counter[str]()
    for title, keys in postings:
        n += 1
        technologies.update(dict.fromkeys(keys, 1))  # once per posting, in a stable order
        titles.update(sorted(title_terms(title)))
    return Demand(n, technologies, titles)


@dataclass(frozen=True)
class Review:
    """One document against the demand."""

    name: str
    named: frozenset[str]
    coverage: float  # share of the demand the document names, 0-1
    to_add: tuple[str, ...]  # asked, in your skills, not named; most asked first
    to_learn: tuple[str, ...]  # asked, not in your skills
    not_in_skills: tuple[str, ...]  # named, but missing from the profile
    titles: tuple[str, ...]  # the most asked titles the document contains


def review(name: str, text: str, skills: Iterable[str], wanted: Demand, top_titles: int = 10) -> Review:
    named = frozenset(tech.technologies_in(text))
    skills = frozenset(skills)
    asked = [key for key, _ in wanted.technologies.most_common()]
    total = sum(wanted.technologies.values())
    covered = sum(wanted.technologies[key] for key in named)
    folded = " ".join(dedup.title_key(text).split())
    return Review(
        name=name,
        named=named,
        coverage=covered / total if total else 0.0,
        to_add=tuple(k for k in asked if k in skills and k not in named),
        to_learn=tuple(k for k in asked if k not in skills),
        not_in_skills=tuple(k for k in sorted(named) if k not in skills),
        titles=tuple(t for t, _ in wanted.titles.most_common(top_titles) if re.search(rf"\b{re.escape(t)}\b", folded)),
    )


def reviews(documents: Mapping[str, str], skills: Iterable[str], wanted: Demand) -> list[Review]:
    skills = frozenset(skills)
    return [review(name, text, skills, wanted) for name, text in documents.items() if text.strip()]


def _pct(value: float) -> str:
    return f"{value:4.0%}"


def render_text(wanted: Demand, found: list[Review], skills: Iterable[str], top: int = 15) -> str:
    skills = frozenset(skills)
    label = {key: t.label for key, t in tech.BY_KEY.items()}
    if not wanted.postings:
        return "No open postings fit your profile: run `jobpipe ingest ...` or widen config/profile.toml.\n"
    names = [r.name for r in found]
    width = max([len(n) for n in names] + [6])
    out = [f"Your documents against {wanted.postings} open postings that fit your profile.", ""]
    out.append("Most asked technologies   asked  skill  " + "  ".join(f"{n:>{width}}" for n in names))
    for key, _ in wanted.technologies.most_common(top):
        marks = "  ".join(f"{('yes' if key in r.named else '-'):>{width}}" for r in found)
        out.append(f"  {label[key]:<23} {_pct(wanted.share(key))}  {'yes' if key in skills else '-':>5}  {marks}")
    out += ["", "Coverage, the share of that demand each document names:"]
    out += [f"  {r.name:<{width}} {_pct(r.coverage)}" for r in found]
    for r in found:
        if r.to_add[:top]:
            listed = ", ".join(f"{label[k]} ({wanted.share(k):.0%})" for k in r.to_add[:top])
            out += ["", f"Add to {r.name}, you list them as skills: {listed}"]
    learn = next(iter(found)).to_learn[:10] if found else ()
    if learn:
        out += ["", "Worth learning, asked and not in your skills: "
                + ", ".join(f"{label[k]} ({wanted.share(k):.0%})" for k in learn)]  # fmt: skip
    missing = sorted({k for r in found for k in r.not_in_skills})
    if missing:
        out += ["", "Named in your documents but not in your profile skills, so the feed counts them as missing: "
                + ", ".join(label[k] for k in missing)]  # fmt: skip
    if wanted.titles:
        out += ["", "Job titles these postings use most, and which documents name them:"]
        for title, n in wanted.titles.most_common(10):
            where = ", ".join(r.name for r in found if title in r.titles) or "-"
            out.append(f"  {title:<28} {n:>4}  {where}")
    return "\n".join(out) + "\n"


def to_jsonable(wanted: Demand, found: list[Review]) -> dict[str, object]:
    return {
        "postings": wanted.postings,
        "technologies": [{"technology": k, "postings": n, "share": wanted.share(k)}
                         for k, n in wanted.technologies.most_common()],
        "titles": [{"title": t, "postings": n} for t, n in wanted.titles.most_common(25)],
        "documents": [{
            "name": r.name, "coverage": r.coverage, "named": sorted(r.named), "to_add": list(r.to_add),
            "to_learn": list(r.to_learn), "not_in_skills": list(r.not_in_skills), "titles": list(r.titles),
        } for r in found],
    }  # fmt: skip
