"""Big tech employers, so the feed and dashboards can single them out.

Two tiers:

- ``faang``: Google, Meta, Amazon, Apple, Netflix and Microsoft, the companies
  people mean by FAANG or MAANG. Their own job sites have no public API, so
  their postings arrive through Adzuna and HN (see ADR 0009).
- ``big_tech``: large or top-paying tech companies with offices in Europe.
  Many publish on Greenhouse, Lever or Ashby, so their boards can be collected.

Every other company is ``other``. A posting's company is matched against the
names below once legal forms, places and generic words are dropped, so
"Google Switzerland GmbH", "Amazon Development Center Germany" and the board
"datadog" all match, while "Elastic Path" does not match Elastic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from jobpipe import places


@dataclass(frozen=True)
class Tier:
    key: str
    en: str
    es: str

    def label(self, lang: str) -> str:
        return self.es if lang == "es" else self.en


FAANG = Tier("faang", "FAANG + Microsoft", "FAANG + Microsoft")
BIG_TECH = Tier("big_tech", "Big tech", "Big tech")
OTHER = Tier("other", "Other companies", "Otras empresas")
TIERS = (FAANG, BIG_TECH, OTHER)

# Employer name, then other names it publishes under, separated by "|".
EMPLOYERS: dict[str, tuple[str, ...]] = {
    FAANG.key: (
        "Google|Alphabet|Google DeepMind|DeepMind|YouTube",
        "Meta|Meta Platforms|Facebook|Instagram|WhatsApp",
        "Amazon|AWS|Amazon Web Services|Amazon Development Center|Amazon EU",
        "Apple",
        "Netflix",
        "Microsoft",
    ),
    BIG_TECH.key: (
        "Adobe", "Adyen", "Airbnb", "AMD", "Anthropic", "Atlassian", "Bloomberg", "Booking.com|Booking",
        "ByteDance|TikTok", "Canonical", "Cisco", "Cloudflare", "Coinbase", "Databricks", "Datadog",
        "Dropbox", "Elastic", "GitHub", "GitLab", "IBM", "Intel", "Klarna", "LinkedIn", "MongoDB",
        "Nvidia", "Okta", "OpenAI", "Oracle", "Palantir|Palantir Technologies", "Pinterest", "Qualcomm",
        "Revolut", "Salesforce", "SAP", "ServiceNow", "Shopify", "Snowflake", "Spotify", "Stripe", "Twilio",
        "Uber", "Wise|Wise Payments", "Workday", "xAI", "Zalando",
    ),
}  # fmt: skip

LEGAL_FORMS = frozenset(
    "ag gmbh sa sl slu sau inc ltd llc bv nv sas sarl plc ab oy as aps spa srl co corp corporation limited"
    " company se kg holding group com io careers jobs hq the a b l s u v".split()
)


def company_key(company: str | None) -> str:
    """Lowercase words of a company name, without legal forms or punctuation."""
    words = re.sub(r"[^a-z0-9]+", " ", places.fold(company or "")).split()
    kept = [w for w in words if w not in LEGAL_FORMS]
    return " ".join(kept or words)


# Dropped after the legal forms: "Amazon Web Services EMEA", "Google Switzerland".
GENERIC = frozenset(
    "international global europe european emea worldwide technologies technology tech development center centre"
    " services operations digital software labs research engineering".split()
)


def employer_key(name: str | None) -> str:
    """"Amazon Development Center (Romania) S.R.L." -> "amazon"."""
    words = [w for w in company_key(name).split() if len(w) > 1] or company_key(name).split()
    while len(words) > 1 and (words[-1] in GENERIC or words[-1] in places.COUNTRY_BY_NAME
                               or words[-1] in places.CITY_BY_KEY):  # fmt: skip
        words.pop()
    return " ".join(words)


_BY_KEY: dict[str, tuple[str, str]] = {}
for _tier, _employers in EMPLOYERS.items():
    for _names in _employers:
        _canonical = _names.split("|")[0]
        for _name in _names.split("|"):
            _BY_KEY[employer_key(_name)] = (_canonical, _tier)


@dataclass(frozen=True)
class Employer:
    name: str | None  # canonical name for big tech, None otherwise
    tier: str


def employer_of(company: str | None) -> Employer:
    found = _BY_KEY.get(employer_key(company))
    return Employer(*found) if found else Employer(None, OTHER.key)
