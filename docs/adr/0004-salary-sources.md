# ADR 0004 — Salary sources and Levels.fyi

- Status: accepted
- Date: 2026-11-11

## Context

The dataset is also used to negotiate offers, so it needs salary evidence for
Switzerland, Spain and the rest of Europe: what employers advertise, and what
people in the role are actually paid.

Levels.fyi has the best data on actual tech pay, including Zurich and Madrid.
Its Terms of Use (section on restrictions, checked 2026-11-11) forbid accessing,
crawling, scraping or downloading "any part of the Services or any data on the
Services (whether or not you have an Account, and including publicly accessible
pages) by any automated means", including AI agents, and using its data "to
compile any dataset", unless Levels.fyi permits it in writing. Third-party
"Levels.fyi scrapers" exist; using them would break those terms.

Levels.fyi offers three sanctioned ways in:

| Access | For | Credential |
| --- | --- | --- |
| Compensation REST API (`api.levels.fyi`, OpenAPI at `levels.fyi/openapi.json`) | Scripts and data pipelines | API key from an employer account, paid |
| Free MCP server (`mcp.levels.fyi`) | An AI assistant answering one person's question | None, or OAuth |
| The website | A person reading it | None |

## Decision

Salary evidence comes from three kinds of source, reported separately and never
blended into one number:

1. **Posted ranges** extracted from postings already in bronze: Ashby
   compensation (with per-market tiers), Lever `salaryRange`, Adzuna
   `salary_min/max` (Adzuna's own estimates are flagged `salary_is_predicted`
   and excluded by default), and ranges written in Greenhouse and HN text.
2. **Adzuna salary histograms and history** (`/jobs/{country}/histogram`,
   `/jobs/{country}/history`): official endpoints, same free key as search.
3. **Levels.fyi benchmarks** only through the official Compensation API, when
   `LEVELS_FYI_API_KEY` is set. Without a key the pipeline collects nothing from
   Levels.fyi. Personal lookups go through the website or the free MCP server
   and are not stored in this dataset.

Amounts are annualised (hour × 2080, day × 260, week × 52, month × 12) but never
converted between currencies. Levels.fyi data shown anywhere carries
"Data source: Levels.fyi (https://www.levels.fyi)"; Adzuna data credits Adzuna.

## Consequences

- Posted ranges cover only employers that publish pay. That is common in the US
  and growing in the EU (Pay Transparency Directive, transposition due June
  2026), but still rare in Switzerland, so Swiss numbers rest on few postings
  plus Adzuna. The report prints the sample size next to every spread.
- Monthly Swiss and Spanish salaries are multiplied by 12; a 13th or 14th
  payment is not added because postings rarely say whether it is included.
- Free-text extraction is a heuristic. It only accepts ranges with an explicit
  currency and plausible annual values (10k to 2M, max ≤ 3 × min), and every
  extracted range keeps a link to its posting so it can be checked by hand.
