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
[ADR 0003](docs/adr/0003-geographic-scope-and-excluded-sources.md); the last
four ATS were added in [ADR 0007](docs/adr/0007-more-ats-boards.md) and the
boards of big tech companies in [ADR 0009](docs/adr/0009-big-tech-employers.md).

| Source | What it adds | Auth |
| --- | --- | --- |
| HN "Ask HN: Who is hiring?" (Algolia API) | Monthly history back to 2011 | none |
| Greenhouse, Lever, Ashby, SmartRecruiters, Workable, Recruitee and Personio public job boards | Complete, first-hand postings from each employer | none |
| Adzuna | Broad coverage per country (ch, es, de, nl, ...), salary histograms | free key |
| Levels.fyi Compensation API | Actual pay by role, location and experience | paid employer key, optional |

Levels.fyi is used only through its official API: its terms forbid automated
collection of the site, public pages included. See
[ADR 0004](docs/adr/0004-salary-sources.md).

## Architecture

```
sources ──► polite HTTP client ──► bronze (JSONL) ──► jobpipe load ──► PostgreSQL ──► Grafana
  HN          rate limit, retries    immutable,                       silver: postings,  salaries,
  ATS         Retry-After, no        one file per run,                salaries, runs     market,
  Adzuna      secrets in logs        three clocks                     gold: views        pipeline health
```

Raw data is never modified, so a parsing bug is fixed by reprocessing, not by
collecting again. Time semantics are defined in
[ADR 0002](docs/adr/0002-bronze-layer-and-time-semantics.md). Silver and gold
live in PostgreSQL and are rebuilt from bronze on every load
([ADR 0005](docs/adr/0005-warehouse-and-dashboards.md)).

On the way to silver every posting gets a city, ISO country codes and a remote
flag, a seniority level read from its title, and a job id: the same job posted
on several sources or once per city is counted once in the dashboards
([ADR 0008](docs/adr/0008-cleaning-postings.md)).

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
levels.fyi by hand.

### Postings that fit you

```bash
cp config/profile.example.toml config/profile.toml   # list your skills, roles, regions and seniority
jobpipe feed                     # open postings, best match first, with what each one asks that you lack
jobpipe feed --days 7 --min-score 50
jobpipe feed --tier faang --tier big_tech   # only FAANG + Microsoft and other big tech
```

Big tech employers are recognised whatever name they publish under
("Google Switzerland GmbH", "Amazon Web Services EMEA SARL"), see
`src/jobpipe/employers.py`. FAANG career sites have no public API and Amazon's
terms forbid automated access, so their postings come from Adzuna and HN only
([ADR 0009](docs/adr/0009-big-tech-employers.md)). Many other big tech
companies publish on public boards and are collected directly: Databricks,
OpenAI, Anthropic, Snowflake, Spotify, Airbnb, LinkedIn, ServiceNow, Wise and
about 35 more, all in `config/boards.toml`.

Each posting's technologies are found in its title and description
(`src/jobpipe/tech.py`). The match is the share of them you know; the feed
ends with the technologies you lack most often in the postings that fit you.
See [ADR 0006](docs/adr/0006-technologies-and-matching.md).

### Your CV and LinkedIn against those postings

```bash
mkdir private   # gitignored: your CV and LinkedIn export never reach git
jobpipe cv --cv private/cv.md --linkedin private/linkedin-export.zip
jobpipe cv --cv private/cv-v1.docx --cv private/cv-v2.docx --tier faang --tier big_tech
```

Recruiters search LinkedIn by keyword and many application systems filter
CVs the same way. The report lists the technologies the postings that fit you
ask for most, which of them each document names, and how much of that demand
it covers. Then it gives:

- what to add: skills in your profile that a document never names;
- what to learn: technologies the postings ask for and you lack;
- skills a document names that your profile is missing;
- the job titles the postings use most ("platform engineer", "ingeniero de
  datos") and which documents say them.

CVs are read as text, Markdown or .docx. LinkedIn comes from its data export
(Settings, Data privacy, Get a copy of your data). Only the headline, about,
skills and positions are read; the address, contacts and messages in the
export are never opened (`src/jobpipe/cv.py`).

### Dashboards

Needs Docker.

```bash
pip install -e .[db]
docker compose up -d --build  # PostgreSQL (port 55432) + Grafana (3000), on 127.0.0.1 only
jobpipe load                  # rebuild silver/gold from bronze, scored with config/profile.toml
```

Then open http://localhost:3000. Four dashboards, in English and Spanish
(the button at the top switches language and keeps the filters):

- **For you** (the home page): open postings that fit your profile, best
  match first, and what to learn: the technologies they ask for that you lack.
- **Salaries**: p25 / median / p75 / p90 by region, role, seniority, company tier and currency, where
  your offer falls, best-paying postings with links, Adzuna histograms,
  Levels.fyi.
- **Market and postings**: postings per month and region, who is hiring, big
  tech with open jobs, the most asked technologies and their share per month,
  and the list of postings.
- **Pipeline health**: runs and records per source, days since the last
  collection, distinct jobs and the share of postings whose location was
  understood.

Every filter is a dropdown. Roles are grouped from the posting title
(`src/jobpipe/roles.py`), so "Data Engineer" and "Senior Data Engineer,
Platform" both land in *Data*; seniority comes from the title too
(`src/jobpipe/seniority.py`).

The dashboards are generated by `grafana/build_dashboards.py`: edit that and
rerun it rather than editing the JSON (CI fails if they differ). The rounded,
blue and purple look comes from `grafana/theme/jobpipe.css`, which the
Grafana image in `grafana/Dockerfile` links into the page. Passwords default
to local-only values; copy `.env.example` to `.env` to change them.

## Development

```bash
PYTHONPATH=src python -m unittest discover -s tests -t .

# Against PostgreSQL too: loads a fixture into the jobpipe_test database
# (never the real one) and runs every dashboard query
JOBPIPE_TEST_DATABASE_URL=postgresql://jobpipe:jobpipe@127.0.0.1:55432/jobpipe_test \
  PYTHONPATH=src python -m unittest tests.test_warehouse
```

Commits follow [Conventional Commits](https://www.conventionalcommits.org/);
CI checks every PR. Decisions that are hard to reverse get an ADR in `docs/adr/`.

## Roadmap

1. **Ingestion (bronze)** — HN, ATS boards, Adzuna. *Done.*
2. **Scheduling** — daily CronJobs on a local k3d cluster; HN monthly.
3. **Silver** — PostgreSQL with first_seen/last_seen per posting, normalised
   places and seniority, one job id across sources. *Done.*
4. **Gold** — salary, market and "for you" dashboards in Grafana, technology
   extraction and matching, counts per job. *Started.* Next: gold models in
   dbt, more Swiss and Spanish sources.
5. **Observability** — pipeline health dashboard. *Started.* Next: alerts when a
   source returns nothing.

Streaming (Kafka) was considered and left out: sources are polled once a day,
so a queue between collectors and bronze would add moving parts without
changing what the data can answer.

## Data and attribution

Collected data is not committed. Adzuna data shown publicly must credit Adzuna;
Levels.fyi data must say "Data source: Levels.fyi (https://www.levels.fyi)".
Postings belong to their publishers; only aggregated statistics are published.
