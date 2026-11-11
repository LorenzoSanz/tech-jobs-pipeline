# ADR 0006 — Technologies and matching postings to a profile

- Status: accepted
- Date: 2026-11-11

## Context

Counting postings per month and region says little to someone looking for a
job. The useful questions are "which open postings fit me" and "what do they
ask for that I lack". Both need to know which technologies each posting asks
for, and that also enables the market question this project started from:
how demand for a technology changes over time.

Postings carry their description as free text (HTML for Greenhouse and HN,
plain text for Lever, Ashby and Adzuna). Adzuna only returns a snippet.

## Decision

**Extraction.** `jobpipe/tech.py` holds a fixed catalogue of about 70
technologies, each with a regex, matched against title plus description at
load time and stored as `silver.postings.technologies`. A catalogue rather
than open keyword extraction or an LLM, because:

- results must be comparable month to month and against a profile, so every
  spelling must land on one key (`postgres` and `PostgreSQL`);
- it is deterministic, free and testable, and runs over the full HN history
  in seconds;
- each false positive found is fixed once, with a test (Go the verb, Java in
  JavaScript, a company's own product in its postings).

The cost is recall: a technology missing from the catalogue is invisible
until it is added.

**Open postings.** An ATS board is fetched whole, so a posting is open when it
was in the newest run that fetched its board. HN and Adzuna are not
snapshots; their postings count as open for 45 days after posting, counted
from the newest fetch of the source so the result depends only on the data.

**Matching.** `config/profile.toml` (not committed; an example is) lists the
user's skills, role families, regions and titles to skip. `jobpipe/match.py`
scores a posting as the share of its technologies the user knows, and ranks
with `(have + 1) / (asked + 3)` so a posting naming one known tool does not
top one naming five. The score is computed in Python once; `jobpipe load`
stores it in `silver.posting_matches`, and both `jobpipe feed` and the
"For you" dashboard read the same result.

## Consequences

- A posting that names no catalogued technology has no score. It is listed
  last, not hidden: many good postings describe the work, not the stack.
- Requirements and "nice to have" are not told apart, so the score is a sort
  order and a list of gaps, not a probability of getting the job.
- Changing the profile needs a `jobpipe load` (about a second) before the
  dashboard reflects it; `jobpipe feed` reads bronze directly and does not.
