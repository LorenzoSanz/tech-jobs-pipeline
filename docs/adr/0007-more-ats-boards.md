# ADR 0007 — SmartRecruiters, Workable, Recruitee and Personio boards

- Status: accepted
- Date: 2026-11-11

## Context

After the first loads, 16 of 1582 postings were in Switzerland. Greenhouse,
Lever and Ashby are mostly used by US and UK startups; Swiss and Spanish
employers more often publish through SmartRecruiters (large companies),
Personio (German-speaking SMEs), Workable and Recruitee. Their job boards have
public endpoints that power the employers' career pages, like the three
already used, so the reasoning of ADR 0001 applies to them unchanged.

## Decision

Add four ATS sources, collected by `jobpipe ingest ats` from `config/boards.toml`:

| ATS | Endpoint | Notes |
| --- | --- | --- |
| SmartRecruiters | `api.smartrecruiters.com/v1/companies/{id}/postings` and `/postings/{id}` | The list has no description; see below |
| Workable | `apply.workable.com/api/v1/widget/accounts/{account}?details=true` | One request per board, with descriptions |
| Recruitee | `{company}.recruitee.com/api/offers/` | Structured salary when the employer publishes it |
| Personio | `{company}.jobs.personio.de/xml?language=en` | XML only |

- **SmartRecruiters** is used by employers with thousands of postings, most of
  them outside tech or outside Europe. Every posting is listed, so a snapshot
  stays complete and `is_open` keeps working, but the second request for the
  text is made only for postings in Switzerland, Spain or the rest of Europe
  whose title falls in a technical role family. Other postings are stored
  without description and never get technologies, which is right for them.
- **Recruitee and Personio** put the board in the host name. Board names are
  accepted only as a single lowercase DNS label, so a typo or a crafted name in
  `config/boards.toml` cannot send requests to another host.
- **Personio** returns XML. Each position is stored as a dict of its fields plus
  the raw XML of the position, so bronze stays JSON lines and still keeps the
  response unchanged (ADR 0001, rule 4).

Board discovery (`discover-boards`) recognises links to the four ATS, and
`verify-boards` checks them like the others.

## Consequences

- Boards still have to be curated: none of these ATS lists its customers.
  Candidates come from HN links and from lists of Swiss and Spanish
  companies, checked with `verify-boards`.
- SmartRecruiters boards cost one request per regional technical posting on
  every run (one per second). A board with hundreds of them adds minutes to
  the run; that is the price of having their technologies.
- job-room.ch (arbeit.swiss) was looked at again and still has no public API
  for third parties, so it stays out.
