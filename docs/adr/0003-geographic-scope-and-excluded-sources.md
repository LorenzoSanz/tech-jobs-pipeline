# ADR 0003 — Geographic scope and excluded sources

- Status: accepted
- Date: 2026-11-09

## Context

The dataset covers Europe: Spain (home market), Germany, Switzerland, the
Netherlands and remote roles, so that salaries and demand can be compared
across markets.

LinkedIn and jobs.ch hold some of the best job data for these markets, so
excluding them needs an explicit reason.

## Decision

### Scope

Collectors are region-agnostic; the region is a parameter:

- Adzuna runs per country (`ch`, `es`, `de`, `nl`, `at`, `fr`, `gb`, ...).
- ATS boards are global by nature; board discovery filters HN postings by
  region (`ch`, `es`, `eu`).
- HN threads are global already; region is assigned in the silver layer.

### Excluded: LinkedIn and JobCloud (jobs.ch, jobup.ch)

Both forbid automated collection in their terms:

- **LinkedIn User Agreement, section 8.2**: no bots or other automated methods to
  access the services. In *hiQ Labs v. LinkedIn* (N.D. Cal., November 2022) the
  court held this clause enforceable as a contract; hiQ ended with a USD 500,000
  consent judgment and had to destroy the scraped data.
- **jobs.ch Terms of Use for Job Seekers, section 7**: users must never use
  crawlers, scrapers or data-mining tools, nor bots or scripts to automate
  processes.

Three reasons make this a hard exclusion for this project, beyond the legal risk:

1. **The collector would run from the author's own accounts.** A restricted LinkedIn account costs far more than the data is worth.
2. **The project is public.** A portfolio repository that breaks the terms of
   the platforms recruiters use is a liability in exactly the interviews it is
   meant to help with.
3. **The data is mostly reachable another way.** Large employers that post on
   LinkedIn and jobs.ch usually publish the same roles on their own ATS board,
   and Adzuna aggregates many Swiss and Spanish boards with permission.

These sources may still be used **manually** for what they are good at:
reading individual postings, and noting the result counts of a few searches
by hand as a sanity check against the pipeline's numbers.

### Candidates, pending review before implementation

| Source | Market | Status |
| --- | --- | --- |
| Bundesagentur für Arbeit Jobsuche | Germany, largest job database in the country | Public endpoint used by its own website and documented by bund.dev, but not an official API. Review before use. |
| InfoJobs API | Spain | Official API; requires registering an application at developer.infojobs.net. |
| Arbeitnow job board API | Germany and remote EU | Free JSON API; check terms and attribution. |

## Consequences

- Coverage is biased towards companies that use public ATS boards or are
  aggregated by Adzuna. The silver layer records the source of every posting,
  so analyses can state that bias instead of hiding it.
- Adding a market is configuration (a country or region), not new code.
