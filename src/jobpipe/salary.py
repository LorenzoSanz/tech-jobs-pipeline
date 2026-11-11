"""Salary ranges from collected postings, plus market benchmarks, for negotiation.

Reads the bronze layer and never writes to it, so a better parser only needs a
rerun. Ranges come from three kinds of evidence, never mixed in one number:

1. **Posted ranges**: what employers advertise. Structured fields (Ashby
   compensation, Lever ``salaryRange``, Adzuna ``salary_min/max``) and ranges
   written in the text (Greenhouse content, HN comments).
2. **Adzuna histograms**: the distribution of advertised salaries for a search.
3. **Levels.fyi benchmarks**: self-reported pay of people in the role, via the
   official API only (see docs/adr/0004).

Amounts are annualised but never converted between currencies: each currency is
reported on its own, so no exchange rate assumption hides in the result.
"""

from __future__ import annotations

import html
import re
import statistics
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from jobpipe.bronze import read_records
from jobpipe.discovery import REGION_KEYWORDS

HOURS_PER_YEAR = 2080
PERIODS_PER_YEAR = {"year": 1, "month": 12, "week": 52, "day": 260, "hour": HOURS_PER_YEAR}
MIN_ANNUAL = 10_000
MAX_ANNUAL = 2_000_000

ADZUNA_CURRENCY = {
    "ch": "CHF", "gb": "GBP", "us": "USD", "pl": "PLN", "ca": "CAD", "au": "AUD",
    "in": "INR", "br": "BRL", "mx": "MXN", "sg": "SGD", "za": "ZAR", "nz": "NZD",
}  # fmt: skip
EUROPE_ISO = {
    "at", "be", "bg", "cy", "cz", "de", "dk", "ee", "fi", "fr", "gb", "gr", "hr", "hu",
    "ie", "is", "it", "li", "lt", "lu", "lv", "mt", "nl", "no", "pl", "pt", "ro", "se",
    "si", "sk", "uk",
}  # fmt: skip
EUROPE_NAMES = (
    r"germany|deutschland|netherlands|holland|austria|[öo]sterreich|france|italy|ireland"
    r"|portugal|belgium|denmark|sweden|norway|finland|poland|czech|united kingdom|uk"
    r"|england|scotland|estonia|lithuania|latvia|romania|greece|croatia|hungary|luxembourg"
)
REGION_PATTERNS = {
    "ch": re.compile(rf"\b({REGION_KEYWORDS['ch']})\b", re.IGNORECASE),
    "es": re.compile(rf"\b({REGION_KEYWORDS['es']})\b", re.IGNORECASE),
    "eu": re.compile(rf"\b({REGION_KEYWORDS['eu']}|{EUROPE_NAMES})\b", re.IGNORECASE),
}

SYMBOLS = {"€": "EUR", "$": "USD", "£": "GBP", "fr.": "CHF", "sfr": "CHF"}
_CUR = r"CHF|EUR|USD|GBP|SFr|Fr\.|€|\$|£"
_NUM = r"\d{1,3}(?:[,.'’ ]\d{3})+|\d+(?:\.\d+)?"
RANGE_PATTERN = re.compile(
    rf"(?P<c1>{_CUR})?\s?(?P<a>{_NUM})\s?(?P<k1>[kK])?\s*"
    rf"(?:-|–|—|to|bis|a|hasta)\s*"
    rf"(?P<c2>{_CUR})?\s?(?P<b>{_NUM})\s?(?P<k2>[kK])?(?![\w%])\s*(?P<c3>CHF|EUR|USD|GBP)?",
    re.IGNORECASE,
)
INTERVAL_HINTS = [
    ("hour", re.compile(r"^\W{0,3}(per hour|/\s?h(ou)?r|an hour|hourly|/h\b|pro stunde)", re.I)),
    ("month", re.compile(r"^\W{0,3}(per month|/\s?mo(nth)?|monthly|a month|pro monat|al mes|/mes)", re.I)),
    ("day", re.compile(r"^\W{0,3}(per day|/\s?day|daily|a day)", re.I)),
]


@dataclass(frozen=True)
class PostedSalary:
    source: str
    source_id: str
    company: str | None
    title: str | None
    location: str | None
    country: str | None
    currency: str
    min_annual: float
    max_annual: float
    period: str
    predicted: bool
    tier: str | None
    url: str | None
    fetched_at: str | None

    @property
    def midpoint(self) -> float:
        return (self.min_annual + self.max_annual) / 2

    def regions(self) -> set[str]:
        return regions_of(self.location, self.country)


def regions_of(location: str | None, country: str | None = None) -> set[str]:
    """ch, es and/or eu, from a country code or name and free location text."""
    found = set()
    country = (country or "").strip()
    iso = country.lower() if len(country) == 2 else None
    if iso == "ch":
        found.add("ch")
    elif iso == "es":
        found.add("es")
    elif iso in EUROPE_ISO:
        found.add("eu")
    text = " ".join(filter(None, [location, None if iso else country]))
    for region, pattern in REGION_PATTERNS.items():
        if pattern.search(text):
            found.add(region)
    return found


def plain_text(text: str) -> str:
    text = html.unescape(html.unescape(text or ""))
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text))


def _number(raw: str, thousands: bool) -> float:
    value = float(re.sub(r"[,.'’ ]", "", raw)) if re.fullmatch(r"\d{1,3}(?:[,.'’ ]\d{3})+", raw) else float(raw)
    return value * 1000 if thousands else value


def _currency(*tokens: str | None) -> str | None:
    for token in tokens:
        if token:
            upper = token.upper()
            if upper in {"CHF", "EUR", "USD", "GBP"}:
                return upper
            if token.lower() in SYMBOLS:
                return SYMBOLS[token.lower()]
    return None


def _annual(minimum: float, maximum: float, period: str) -> tuple[float, float] | None:
    factor = PERIODS_PER_YEAR.get(period)
    if factor is None or minimum <= 0 or maximum < minimum:
        return None
    low, high = minimum * factor, maximum * factor
    if low < MIN_ANNUAL or high > MAX_ANNUAL or high > low * 3:
        return None
    return low, high


def ranges_in_text(text: str) -> list[tuple[str, float, float, str]]:
    """Salary ranges written in prose: ``(currency, min_annual, max_annual, period)``.

    Only ranges with an explicit currency count; "5-10 years" never matches.
    """
    plain = plain_text(text)
    found = []
    for match in RANGE_PATTERN.finditer(plain):
        currency = _currency(match["c1"], match["c2"], match["c3"])
        if currency is None:
            continue
        k = bool(match["k1"] or match["k2"])
        try:
            low = _number(match["a"], bool(match["k1"]) or (k and float(match["a"].replace(",", ".")) < 1000))
            high = _number(match["b"], bool(match["k2"]) or (k and float(match["b"].replace(",", ".")) < 1000))
        except ValueError:
            continue
        tail = plain[match.end() : match.end() + 25]
        period = next((name for name, hint in INTERVAL_HINTS if hint.search(tail)), "year")
        annual = _annual(low, high, period)
        if annual:
            found.append((currency, annual[0], annual[1], period))
    return found


def _ashby(record: Mapping[str, Any]) -> Iterator[PostedSalary]:
    job = record["payload"]["job"]
    comp = job.get("compensation") or {}
    tiers = [t for t in comp.get("compensationTiers") or [] if t.get("title")]
    if len(tiers) > 1:
        groups = [(t["title"], t.get("components") or []) for t in tiers]
    else:
        groups = [(None, comp.get("summaryComponents") or [])]
    address = (job.get("address") or {}).get("postalAddress") or {}
    for tier, components in groups:
        for component in components:
            if component.get("compensationType") != "Salary" or not component.get("currencyCode"):
                continue
            period = {"1 YEAR": "year", "1 MONTH": "month", "1 WEEK": "week", "1 DAY": "day", "1 HOUR": "hour"}.get(
                component.get("interval") or ""
            )
            low, high = component.get("minValue"), component.get("maxValue")
            if period is None or low is None:
                continue
            annual = _annual(float(low), float(high if high is not None else low), period)
            if annual:
                yield _posted(record, job.get("title"), record["payload"]["board"], job.get("location"),
                              address.get("addressCountry"), component["currencyCode"], annual, period,
                              tier=tier, url=job.get("jobUrl"))


def _lever(record: Mapping[str, Any]) -> Iterator[PostedSalary]:
    job = record["payload"]["job"]
    salary = job.get("salaryRange") or {}
    period = {
        "per-year-salary": "year", "per-month-salary": "month",
        "per-week-salary": "week", "per-day-wage": "day", "per-hour-wage": "hour",
    }.get(salary.get("interval") or "")  # fmt: skip
    location = (job.get("categories") or {}).get("location")
    if period and salary.get("min") and salary.get("currency"):
        annual = _annual(float(salary["min"]), float(salary.get("max") or salary["min"]), period)
        if annual:
            yield _posted(record, job.get("text"), record["payload"]["board"], location, job.get("country"),
                          salary["currency"], annual, period, url=job.get("hostedUrl"))
            return
    yield from _from_text(record, job.get("text"), record["payload"]["board"], location, job.get("country"),
                          " ".join(filter(None, [job.get("descriptionPlain"), job.get("additionalPlain")])),
                          job.get("hostedUrl"))


def _greenhouse(record: Mapping[str, Any]) -> Iterator[PostedSalary]:
    job = record["payload"]["job"]
    location = (job.get("location") or {}).get("name")
    yield from _from_text(record, job.get("title"), job.get("company_name") or record["payload"]["board"],
                          location, None, job.get("content") or "", job.get("absolute_url"))


def _smartrecruiters(record: Mapping[str, Any]) -> Iterator[PostedSalary]:
    job = record["payload"]["job"]
    location = job.get("location") or {}
    sections = ((job.get("jobAd") or {}).get("sections") or {}).values()
    yield from _from_text(record, job.get("name"), (job.get("company") or {}).get("name") or record["payload"]["board"],
                          location.get("fullLocation"), location.get("country"),
                          " ".join(s.get("text") or "" for s in sections if isinstance(s, dict)), job.get("postingUrl"))


def _workable(record: Mapping[str, Any]) -> Iterator[PostedSalary]:
    job = record["payload"]["job"]
    country = next((loc.get("countryCode") for loc in job.get("locations") or []), None) or job.get("country")
    yield from _from_text(record, job.get("title"), record["payload"]["board"],
                          ", ".join(filter(None, [job.get("city"), job.get("country")])), country,
                          job.get("description") or "", job.get("url"))


def _recruitee(record: Mapping[str, Any]) -> Iterator[PostedSalary]:
    job = record["payload"]["job"]
    company = job.get("company_name") or record["payload"]["board"]
    pay = job.get("salary") or {}
    period = {"year": "year", "month": "month", "week": "week", "day": "day", "hour": "hour"}.get(pay.get("period") or "")
    try:
        low, high = float(pay.get("min") or 0), float(pay.get("max") or pay.get("min") or 0)
    except ValueError:
        low = high = 0
    if period and low and pay.get("currency"):
        annual = _annual(low, high, period)
        if annual:
            yield _posted(record, job.get("title"), company, job.get("location"), job.get("country_code"),
                          pay["currency"], annual, period, url=job.get("careers_url"))
            return
    yield from _from_text(record, job.get("title"), company, job.get("location"), job.get("country_code"),
                          " ".join(filter(None, [job.get("description"), job.get("requirements")])),
                          job.get("careers_url"))


def _personio(record: Mapping[str, Any]) -> Iterator[PostedSalary]:
    job = record["payload"]["job"]
    yield from _from_text(record, job.get("name"), job.get("subcompany") or record["payload"]["board"],
                          job.get("office"), None,
                          " ".join(d.get("value") or "" for d in job.get("descriptions") or []), job.get("url"))


def _adzuna(record: Mapping[str, Any]) -> Iterator[PostedSalary]:
    job = record["payload"]["job"]
    country = record["payload"].get("country")
    low, high = job.get("salary_min"), job.get("salary_max")
    if not low:
        return
    annual = _annual(float(low), float(high or low), "year")
    if annual:
        yield _posted(record, job.get("title"), (job.get("company") or {}).get("display_name"),
                      (job.get("location") or {}).get("display_name"), country,
                      ADZUNA_CURRENCY.get(country, "EUR"), annual, "year",
                      predicted=str(job.get("salary_is_predicted")) == "1", url=job.get("redirect_url"))


def _hn(record: Mapping[str, Any]) -> Iterator[PostedSalary]:
    text = record["payload"]["comment"]["text"]
    header = plain_text(text.split("<p>")[0])
    parts = [p.strip() for p in header.split("|")]
    company = parts[0][:80] if parts else None
    url = f"https://news.ycombinator.com/item?id={record['payload']['comment']['id']}"
    yield from _from_text(record, header[:200], company, header, None, text, url)


def _from_text(
    record: Mapping[str, Any], title: str | None, company: str | None, location: str | None,
    country: str | None, text: str, url: str | None,
) -> Iterator[PostedSalary]:
    for currency, low, high, period in dict.fromkeys(ranges_in_text(text)):
        yield _posted(record, title, company, location, country, currency, (low, high), period, url=url)


def _posted(
    record: Mapping[str, Any], title: str | None, company: str | None, location: str | None,
    country: str | None, currency: str, annual: tuple[float, float], period: str, *,
    predicted: bool = False, tier: str | None = None, url: str | None = None,
) -> PostedSalary:
    return PostedSalary(
        source=record["source"], source_id=record["source_id"], company=company, title=title,
        location=location, country=country, currency=currency.upper(), min_annual=annual[0],
        max_annual=annual[1], period=period, predicted=predicted, tier=tier, url=url,
        fetched_at=record.get("fetched_at"),
    )  # fmt: skip


EXTRACTORS = {
    "ashby": _ashby, "lever": _lever, "greenhouse": _greenhouse, "smartrecruiters": _smartrecruiters,
    "workable": _workable, "recruitee": _recruitee, "personio": _personio, "adzuna": _adzuna, "hn": _hn,
}  # fmt: skip


def latest(records: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """The newest snapshot of each source_id (bronze keeps every snapshot)."""
    newest: dict[str, Mapping[str, Any]] = {}
    for record in records:
        current = newest.get(record["source_id"])
        if current is None or (record.get("fetched_at") or "") >= (current.get("fetched_at") or ""):
            newest[record["source_id"]] = record
    return list(newest.values())


def posted_salaries(data_dir: Path, sources: Iterable[str] = EXTRACTORS) -> Iterator[PostedSalary]:
    for source in sources:
        for record in latest(read_records(data_dir, source)):
            try:
                yield from EXTRACTORS[source](record)
            except (KeyError, TypeError, ValueError, AttributeError):
                continue  # one malformed payload never hides the rest


@dataclass(frozen=True)
class Spread:
    count: int
    p25: float
    p50: float
    p75: float

    @classmethod
    def of(cls, values: list[float]) -> Spread | None:
        if not values:
            return None
        if len(values) == 1:
            return cls(1, values[0], values[0], values[0])
        p25, p50, p75 = statistics.quantiles(values, n=4, method="inclusive")
        return cls(len(values), p25, p50, p75)


def filter_salaries(
    salaries: Iterable[PostedSalary],
    regions: Iterable[str] = (),
    title: re.Pattern[str] | None = None,
    include_predicted: bool = False,
) -> list[PostedSalary]:
    wanted = set(regions)
    result = []
    for salary in salaries:
        if salary.predicted and not include_predicted:
            continue
        if wanted and not (salary.regions() & wanted):
            continue
        if title and not title.search(salary.title or ""):
            continue
        result.append(salary)
    return result


def summarise(salaries: list[PostedSalary]) -> dict[str, dict[str, Any]]:
    """Per currency: spread of range minimums, maximums and midpoints."""
    by_currency: dict[str, list[PostedSalary]] = {}
    for salary in salaries:
        by_currency.setdefault(salary.currency, []).append(salary)
    summary = {}
    for currency, items in sorted(by_currency.items(), key=lambda kv: -len(kv[1])):
        summary[currency] = {
            "postings": len(items),
            "min": Spread.of(sorted(s.min_annual for s in items)),
            "midpoint": Spread.of(sorted(s.midpoint for s in items)),
            "max": Spread.of(sorted(s.max_annual for s in items)),
            "by_source": dict(sorted({s.source: sum(1 for x in items if x.source == s.source) for s in items}.items())),
            "top": sorted(items, key=lambda s: -s.max_annual)[:10],
        }
    return summary


def histogram_median(histogram: Mapping[str, Any]) -> tuple[float, int] | None:
    """Approximate median (lower bound of the median bucket) and total count."""
    buckets = sorted((float(k), int(float(v))) for k, v in histogram.items())
    total = sum(count for _, count in buckets)
    if total == 0:
        return None
    running = 0
    for lower, count in buckets:
        running += count
        if running * 2 >= total:
            return lower, total
    return buckets[-1][0], total  # pragma: no cover


def benchmark_records(data_dir: Path, source: str) -> list[Mapping[str, Any]]:
    return sorted(latest(read_records(data_dir, source)), key=lambda r: r["source_id"])


def to_jsonable(value: Any) -> Any:
    if isinstance(value, (PostedSalary, Spread)):
        return asdict(value)
    if isinstance(value, dict):
        return {k: to_jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [to_jsonable(v) for v in value]
    return value


def _k(value: float) -> str:
    return f"{value / 1000:,.0f}k"


def render_text(
    summary: Mapping[str, Mapping[str, Any]],
    histograms: list[Mapping[str, Any]],
    levels: list[Mapping[str, Any]],
) -> str:
    """A plain report to read before a salary conversation."""
    lines = ["# Posted salary ranges (annual, gross, per currency)", ""]
    if not summary:
        lines.append("No posting with a salary matches the filters.")
    for currency, block in summary.items():
        lines.append(f"## {currency} - {block['postings']} postings {block['by_source']}")
        lines.append(f"{'':10}{'p25':>10}{'median':>10}{'p75':>10}")
        for name in ("min", "midpoint", "max"):
            spread = block[name]
            lines.append(f"{name:10}{_k(spread.p25):>10}{_k(spread.p50):>10}{_k(spread.p75):>10}")
        lines.append("Highest ranges:")
        for s in block["top"]:
            tier = f" [{s.tier}]" if s.tier else ""
            where = s.location if s.location and s.location != s.title else s.country
            lines.append(
                f"  {_k(s.min_annual)}-{_k(s.max_annual)}  {(s.company or '?')[:25]} | "
                f"{(s.title or '?')[:70]} | {(where or '')[:40]}{tier}  {s.url or ''}".rstrip()
            )
        lines.append("")

    if histograms:
        lines += ["# Adzuna: distribution of advertised salaries (Jobs by Adzuna)", ""]
        for record in histograms:
            payload = record["payload"]
            if payload["kind"] == "histogram":
                currency = ADZUNA_CURRENCY.get(payload["country"], "EUR")
                median = histogram_median(payload["histogram"])
                label = f"{payload['country']} | {payload.get('what') or payload.get('category')}"
                if median:
                    lines.append(f"  {label}: median bucket from {_k(median[0])} {currency}, {median[1]} postings")
            elif payload["month"]:
                months = sorted(payload["month"].items())
                first, last = months[0], months[-1]
                lines.append(
                    f"  {payload['country']} | {payload['category']} average: "
                    f"{first[0]} {_k(float(first[1]))} -> {last[0]} {_k(float(last[1]))}"
                )
        lines.append("")

    if levels:
        lines += ["# Levels.fyi benchmarks (USD; Data source: Levels.fyi, https://www.levels.fyi)", ""]
        for record in levels:
            payload, data = record["payload"], record["payload"]["data"]
            if payload["kind"] == "location_percentiles":
                lines.append(
                    f"  {payload['job_family']} {payload['salary_type']} | {data['locationName']}: "
                    f"p25 {_k(data['p25'])}  p50 {_k(data['p50'])}  p75 {_k(data['p75'])}  "
                    f"p90 {_k(data['p90'])}  (n={data['sampleSize']})"
                )
            else:
                lines.append(
                    f"    {payload['location']} {data['yoeRange']} yrs: p25 {_k(data['p25'])}  "
                    f"p50 {_k(data['p50'])}  p75 {_k(data['p75'])}  (n={data['sampleSize']})"
                )
    return "\n".join(lines).rstrip() + "\n"
