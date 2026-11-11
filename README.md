# swiss-tech-jobs-pipeline

Collects public tech job postings for Switzerland, Spain and the rest of Europe
and turns them into a chronological dataset of what the market asks for: technologies, roles,
seniority and salaries, month by month.

> Status: **phase 1 — ingestion into an immutable raw (bronze) layer.**

## Why

Job market advice is usually anecdotal. This pipeline answers questions like
"how many Zurich backend postings asked for Kafka this quarter, compared with a
year ago?" from real postings, with dates that mean the same thing across
sources.

## Sources

Only APIs intended for third parties are used. LinkedIn and jobs.ch are
excluded because their terms forbid automated collection. See
[ADR 0001](docs/adr/0001-data-sources.md) and
[ADR 0003](docs/adr/0003-geographic-scope-and-excluded-sources.md).

| Source | What it adds | Auth |
| --- | --- | --- |
| HN "Ask HN: Who is hiring?" (Algolia API) | Monthly history back to 2011 | none |
| Greenhouse, Lever and Ashby public job boards | Complete, first-hand postings from each employer | none |
| Adzuna | Broad coverage per country (ch, es, de, nl, ...), salary histograms | free key |
| Levels.fyi Compensation API | Actual pay by role, location and experience | paid employer key, optional |

Levels.fyi is used only through its official API: its terms forbid automated
collection of the site, public pages included. See
[ADR 0004](docs/adr/0004-salary-sources.md).

## Architecture

```
sources ──► polite HTTP client ──► bronze (immutable JSONL) ──► silver ──► gold
  HN          rate limit, retries     one file per run,          dedup,     tech demand
  ATS         Retry-After, no         three clocks:              first/last per month,
  Adzuna      secrets in logs         event_time, fetched_at     seen       salaries
```

Raw data is never modified, so a parsing bug is fixed by reprocessing, not by
collecting again. Time semantics are defined in
[ADR 0002](docs/adr/0002-bronze-layer-and-time-semantics.md).

## Usage

Requires Python 3.11+. No dependencies.

```bash
pip install -e .

# Full HN history (about 180 threads; takes a few minutes at 1 request/s)
jobpipe ingest hn
# or only recent threads
jobpipe ingest hn --since 2026-01-01

# Suggest ATS boards from the HN data (Switzerland, Spain, Europe), review, then add to config/boards.toml
jobpipe discover-boards --region ch --region es --region eu
jobpipe ingest ats

# Adzuna (free key from developer.adzuna.com)
export ADZUNA_APP_ID=... ADZUNA_APP_KEY=...
jobpipe ingest adzuna --country ch --country es --country de --max-days-old 1
```

Data lands in `data/bronze/source=<source>/ingest_date=<date>/run=<id>.jsonl`.
Every command prints one JSON summary line per file written.

### Salaries, for negotiating

```bash
# Salary distribution of current postings for your searches, per country (Adzuna key)
jobpipe ingest adzuna-salaries --country ch --country es --what "data engineer" --what "backend"

# Optional: Levels.fyi benchmarks, only with an official API key
export LEVELS_FYI_API_KEY=...
jobpipe levelsfyi-lookup locations zurich          # find the location slug
jobpipe ingest levelsfyi --job-family software-engineer --location <slug> --focus-tag backend

# Report: posted ranges per currency (p25 / median / p75), best-paying postings
# with links, Adzuna histograms and Levels.fyi benchmarks
jobpipe salaries --region ch --title "data|backend"
jobpipe salaries --region es --region eu --format json > salaries.json
```

Posted ranges come from Ashby, Lever, Greenhouse, Adzuna and HN postings already
collected. Currencies are never mixed; Adzuna's estimated salaries are left out
unless `--include-predicted` is given. Without a Levels.fyi key, check
levels.fyi by hand or through its free MCP server from an AI assistant.

## Development

```bash
PYTHONPATH=src python -m unittest discover -s tests -t .
```

Commits follow [Conventional Commits](https://www.conventionalcommits.org/);
CI checks every PR. Decisions that are hard to reverse get an ADR in `docs/adr/`.

## Roadmap

1. **Ingestion (bronze)** — HN, ATS boards, Adzuna. *Done.*
2. **Scheduling** — daily CronJobs on a local k3d cluster; HN monthly.
3. **Streaming** — collectors publish to Apache Kafka (Strimzi); bronze becomes a consumer.
4. **Silver** — deduplication across sources, first_seen/last_seen, location and seniority normalisation.
5. **Gold** — technology extraction and monthly demand, salary ranges by role
   (a first salary report from bronze exists: `jobpipe salaries`).
6. **Observability** — run metrics and alerts when a source returns nothing.

## Data and attribution

Collected data is not committed. Adzuna data shown publicly must credit Adzuna;
Levels.fyi data must say "Data source: Levels.fyi (https://www.levels.fyi)".
Postings belong to their publishers; only aggregated statistics are published.
