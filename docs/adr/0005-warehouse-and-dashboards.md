# ADR 0005 — PostgreSQL warehouse and Grafana dashboards

- Status: accepted
- Date: 2026-11-11

## Context

Bronze is a pile of JSONL files. It is good for keeping raw data safe, bad for
asking questions: every report so far re-reads and re-parses all of it. I want
to look at salaries, volumes and source health in charts, filter them, and
check where an offer falls, without writing a front end.

## Decision

- **PostgreSQL** holds the silver and gold layers. `jobpipe load` reads bronze
  once and rebuilds both schemas from scratch in a single transaction.
- **Grafana** reads PostgreSQL. The data source and the three dashboards
  (salaries, market, pipeline health) are provisioned from files in
  `grafana/`, so the whole setup comes up with `docker compose up`.
- Grafana connects as `grafana_reader`, a role that can only `SELECT`.
- psycopg is an optional extra (`pip install -e .[db]`). The collectors still
  need nothing beyond the standard library.

### Why rebuild instead of upsert

Silver is fully derived from bronze, which never changes. Dropping and
rebuilding takes under a second for the current volume, cannot drift from
bronze, and needs no migrations: changing the schema is editing
`schema.sql`. Postgres DDL is transactional, so readers see the old data
until the new data is committed. When volume makes this slow, the plan is
incremental loads keyed on `run_id`.

### Alternatives

| Option | Why not (for now) |
| --- | --- |
| DuckDB over the JSONL files | Great for ad hoc SQL, but Grafana support is a community plugin and there is no server for several readers. |
| SQLite | Same Grafana problem; no roles. |
| A custom web UI | More code to maintain; Grafana already does filters, charts and links. |
| dbt for the transformations | Likely next step for the gold layer; the parsing (salary ranges in free text) stays in Python either way. |

## Consequences

- `first_seen`, `last_seen` and `snapshots` now exist per posting, the start
  of the silver layer from the roadmap.
- CI starts a PostgreSQL service, loads a fixture and runs the SQL of every
  dashboard panel, so a broken panel fails the build instead of showing an
  error in Grafana.
- Ports are bound to 127.0.0.1 and passwords come from `.env`; the defaults
  are only for a local machine.
