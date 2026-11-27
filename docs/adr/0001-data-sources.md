# ADR 0001 — Data sources

- Status: accepted
- Date: 2026-11-09

## Context

The goal is a dataset that reflects the European tech job market as closely as
possible: real postings, with reliable dates, in volume, and collected the same
way over time so that trends are comparable.

The obvious sources (LinkedIn, jobs.ch, jobup.ch) offer no public API for this
use. LinkedIn's user agreement forbids automated collection, and scraping the
HTML of job boards is brittle and legally unclear. A dataset that cannot be
published or explained in an interview is worth little for this project.

## Decision

Only sources that publish data through an API intended for third parties are
used. Every source is tagged with what it is good for, so the analysis layer
never mixes populations by accident.

| Source | Endpoint | Auth | Strength | Limitation |
| --- | --- | --- | --- | --- |
| Greenhouse job boards | `boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true` | none | Full, official postings from the employer itself | One company per call; board tokens must be curated |
| Lever postings | `api.lever.co/v0/postings/{site}?mode=json` | none | Same as above, with `createdAt` | Same as above |
| Ashby job boards | `api.ashbyhq.com/posting-api/job-board/{name}?includeCompensation=true` | none | Structured salary ranges when published | Same as above |
| Adzuna | `api.adzuna.com/v1/api/jobs/ch/search/{page}` | free key | Broad coverage of Switzerland, with salary fields | Aggregator: descriptions are truncated, duplicates across boards |
| Hacker News "Who is hiring?" | `hn.algolia.com/api/v1` | none | Monthly threads since 2011: the longest consistent history available | Skews to startups and remote roles; Swiss postings are a minority |

Rules for every connector:

1. Identify the client with a descriptive `User-Agent` that links to this repository.
2. At most one request per second per host by default; honour `Retry-After`.
3. Never send credentials anywhere except the API that issued them, and never log them.
4. Store raw responses unchanged (see ADR 0002), so any parsing mistake can be fixed by reprocessing instead of re-collecting.
5. Respect each provider's terms. Adzuna requires attribution when its data is displayed publicly.

## Consequences

- History comes from HN (back to 2011) and from snapshots collected from now on. There is no free, legal source for years of Swiss job board history, so the time series of ATS and Adzuna data starts on the first run. Running the collector daily matters more than any single backfill.
- ATS coverage depends on the list of boards. Board discovery is automated from HN postings that link to Greenhouse, Lever or Ashby, and the list is reviewed by hand.
- New sources (for example the SECO job room, arbeit.swiss) are only added after checking their terms, in a new ADR.
