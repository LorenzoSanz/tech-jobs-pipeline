# ADR 0009 — Big tech employers and where FAANG postings come from

- Status: accepted
- Date: 2026-11-11

## Context

The search now targets FAANG and other big tech companies. Two questions
follow: how to tell their postings apart, and how to collect them at all.

Google, Meta, Amazon, Apple, Netflix and Microsoft run their own career
sites. None of them offers a public API for job postings: Google retired
Cloud Talent Solution, which was a product for other employers anyway;
Netflix's portal runs on Eightfold, whose API is for its clients only; and
Amazon's conditions of use forbid automated access without written
permission. Scraping them would break ADR 0001 (only APIs meant for third
parties), and a tool that scrapes the very companies it reports on is a poor
thing to show them.

## Decision

**Tiers.** `src/jobpipe/employers.py` lists big tech employers in two tiers:
`faang` (the six above) and `big_tech` (about 45 large or top-paying tech
companies with offices in Europe). Every other company is `other`. A posting's
company is matched after dropping legal forms, places and generic words
("Google Switzerland GmbH", "Amazon Web Services EMEA SARL" and the board slug
"datadog" all match), and only on the whole remaining name, so "Elastic Path"
is not Elastic. The list is code, like the role families and the technology
catalogue: it changes rarely and every change is reviewed.

Silver gets `employer` (canonical name) and `company_tier`. Deduplication uses
the same normalised name, so Google on Adzuna and Google on HN are one company.
Dashboards get a company filter (FAANG + Microsoft, big tech, others), salaries
by tier, and a Big tech section in the market dashboard; the profile and
`jobpipe feed --tier` can keep only some tiers.

**Sources for FAANG postings**, all within ADR 0001:

1. Adzuna, which aggregates postings from boards that allow it.
2. HN "Who is hiring?" comments.
3. Postings the user finds while browsing (LinkedIn, career sites), added by
   hand with a `jobpipe watch` command, next on the roadmap. The tool will
   store the user's notes; it never fetches those sites.

Big tech companies on Greenhouse, Lever, Ashby, SmartRecruiters or Workable
are collected like any other board. About 150 candidate boards were checked
with `verify-boards` on 2026-11-11 and 44 kept, those that answer and have
open jobs in Switzerland, Spain or the rest of Europe: Databricks (166 of 916
open jobs in the region), Wise, Anthropic, OpenAI, ServiceNow, Snowflake,
HubSpot, Spotify, Waymo, Airbnb, LinkedIn and others. Boards whose slug is not
the company name (`hubspotjobs`, `traderepublicbank`) get an alias in
`employers.py`, so they land in the right tier.

## Consequences

- FAANG coverage depends on Adzuna and on the user: the dashboards say so
  instead of suggesting the numbers are complete.
- A company missing from the list counts as `other` until it is added; the
  market dashboard's company list shows which names are worth adding.
- Name collisions are possible for short names (Meta, Wise, Uber). Matching
  the whole name keeps them rare; tests pin the known look-alikes.
