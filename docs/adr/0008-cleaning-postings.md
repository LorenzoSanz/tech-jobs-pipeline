# ADR 0008 — Places, seniority and one row per job

- Status: accepted
- Date: 2026-11-11

## Context

With nine sources, silver had three problems that made the numbers wrong in
ways a reader cannot see:

- **Places.** Each source writes them its own way: "Zürich, Zürich,
  Switzerland", "New York, NY" with the country in another field, "Barcelona
  (HQ)", several offices joined by ";". Personio gives no country at all, so a
  posting in Leipzig had no region.
- **Seniority.** Only the title says it. Without a column, the profile had to
  emulate it with a regex (`exclude_title = 'intern|principal|director'`).
- **Duplicates.** One job shows up several times: once per city on the same
  board (Datadog lists the same sales role in ten US cities), and, once Adzuna
  is collected, on the employer's board and on Adzuna. In the data of
  2026-11-11, 326 of 2081 postings were copies of another one.

## Decision

All three are computed in Python when silver is built (`jobpipe load`), from
bronze, like roles and technologies. Bronze is not touched.

**Places** (`src/jobpipe/places.py`). Every posting gets `city`, `country`
(ISO 3166 alpha-2 of the first place), `countries` (all of them) and `remote`.
The published text stays in `location`. A place's country comes from a country
named in it, then from the source's country field, then from a list of about
340 cities. Two-letter codes are only trusted in the country field, because in
text "CA" is more often California than Canada. Unknown places get no country
instead of a guess. Countries also feed the regions, so a Leipzig posting is
now `eu`.

**Seniority** (`src/jobpipe/seniority.py`). intern, junior, mid, senior, lead,
head, from the title only. A title with no marker is `unspecified`, not `mid`:
most of them probably are mid-level, but that would be a guess presented as
data. It is about 60 % of postings, and the dashboards show it as "Not stated".
The profile gets a `seniority` filter.

**One row per job** (`src/jobpipe/dedup.py`). Postings are the same job when
company, title (without gender markers, city names and work mode) and first
country match, and they were online within 30 days of each other. Silver keeps
every posting and adds `job_id` and `job_rank`; rank 0 is the posting that
stands for the job: open first, then the employer's board before Adzuna, then
one with a description, then the first seen. HN comments are never merged,
since one comment often announces several jobs.

Gold counts jobs: `gold.jobs` has one row per job, with how many postings it
had, on which sources, and in which cities. The feed, market and salary views
read from it; `gold.salaries` takes the salary of the best-ranked posting that
states one, preferring the employer's figure over an Adzuna estimate.

## Consequences

- Market numbers drop where the same role was listed in many cities. That is
  the intended reading: "how many jobs ask for Kafka", not "how many pages".
  Headcount is unknown, so a job listed twice in one city counts once.
- Merging is conservative: different wording ("Data Engineer" and "Data
  Engineer, Platform") stays two jobs. A missed duplicate inflates a count a
  little; a wrong merge would hide a job from the feed, which is worse.
- The city list needs care when sources add new places. The pipeline health
  dashboard shows the share of postings with a country, so a drop is visible.
- Country names are kept in titles on purpose: "Account Executive (Malaysia
  Market)" and "(Philippines Market)" are two jobs.
