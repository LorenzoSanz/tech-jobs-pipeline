# ADR 0002 — Bronze layer and time semantics

- Status: accepted
- Date: 2026-11-09

## Context

The value of this dataset is chronological: how demand for a technology changes
month by month. That only works if every record says *when* things happened,
and if the meaning of each timestamp is the same across sources.

Sources disagree on what they expose. HN and Lever give a creation time, Ashby a
publication time, Greenhouse often only an update time, and none of them says
when a posting was taken down.

## Decision

### Immutable raw layer (bronze)

Every response item is written once, unchanged, as one JSON line:

```json
{
  "schema_version": 1,
  "source": "lever",
  "source_id": "acme:4f1c...",
  "run_id": "20261109T081500Z-3fa2b1c4",
  "fetched_at": "2026-11-09T08:15:02.123456+00:00",
  "event_time": "2026-10-28T09:00:00+00:00",
  "payload_sha256": "9b1d...",
  "payload": { "...": "exactly what the API returned for this item" }
}
```

Files are partitioned as
`data/bronze/source=<source>/ingest_date=<YYYY-MM-DD>/run=<run_id>.jsonl`, are
written to a temporary file and renamed atomically, and are never overwritten.

### Three clocks, never mixed

| Field | Meaning | Set by |
| --- | --- | --- |
| `event_time` | When the source says the posting was created or published. Null when the source does not say. | Connector |
| `fetched_at` | When this pipeline saw the record. | Bronze writer, per record, in UTC |
| `first_seen` / `last_seen` | Lifetime of a posting, derived later from consecutive snapshots. | Silver layer |

`payload_sha256` (SHA-256 of the canonical JSON payload) lets the silver layer
tell "same posting seen again" from "posting edited" without diffing payloads.

## Consequences

- Reprocessing is always possible: a bug in parsing or tech extraction never forces a re-collection.
- Storage grows with every snapshot. JSONL compresses well, and older partitions can be compacted to Parquet later without changing their content.
- Analyses must state which clock they use. Trend charts use `event_time` when available and `first_seen` otherwise, and say so.
