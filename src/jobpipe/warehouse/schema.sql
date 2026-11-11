-- Silver and gold layers in PostgreSQL. See docs/adr/0005-warehouse-and-dashboards.md.
--
-- Everything here is derived from bronze, so `jobpipe load` drops and rebuilds
-- both schemas in one transaction. Never edit these tables by hand.

DROP SCHEMA IF EXISTS gold CASCADE;
DROP SCHEMA IF EXISTS silver CASCADE;
CREATE SCHEMA silver;
CREATE SCHEMA gold;

-- One row per posting (source + source_id), from its newest snapshot.
CREATE TABLE silver.postings (
    source      text        NOT NULL,
    source_id   text        NOT NULL,
    title       text        NOT NULL,
    company     text,
    location    text,
    country     text,
    url         text,
    published   timestamptz,          -- event_time: when the source says it was posted
    first_seen  timestamptz NOT NULL, -- first snapshot that contained it
    last_seen   timestamptz NOT NULL, -- latest snapshot that contained it
    snapshots   integer     NOT NULL,
    is_open     boolean     NOT NULL, -- still published, see current_postings in jobpipe/warehouse
    regions     text[]      NOT NULL, -- ch, es, eu; empty when unknown
    role        text        NOT NULL, -- role family key from the title, see jobpipe/roles.py
    technologies text[]     NOT NULL, -- technology keys from title and description, see jobpipe/tech.py
    PRIMARY KEY (source, source_id)
);

-- The technology catalogue, so dashboards can show labels and categories.
CREATE TABLE silver.technologies (
    key       text PRIMARY KEY,
    label     text NOT NULL,
    category  text NOT NULL
);

-- How each posting fits the profile in config/profile.toml. Empty without a profile.
CREATE TABLE silver.posting_matches (
    source      text    NOT NULL,
    source_id   text    NOT NULL,
    fits        boolean NOT NULL,  -- role, region and title pass the profile's filters
    score       numeric,           -- share of the posting's technologies you know; NULL when it names none
    rank        numeric NOT NULL,  -- sort key, see Match.rank in jobpipe/match.py
    have        text[]  NOT NULL,
    missing     text[]  NOT NULL,
    PRIMARY KEY (source, source_id),
    FOREIGN KEY (source, source_id) REFERENCES silver.postings
);

-- Salary ranges found in postings, annualised, never converted between currencies.
CREATE TABLE silver.posted_salaries (
    source      text    NOT NULL,
    source_id   text    NOT NULL,
    n           integer NOT NULL,    -- a posting can state several ranges
    currency    text    NOT NULL,
    min_annual  numeric NOT NULL,
    max_annual  numeric NOT NULL,
    midpoint    numeric GENERATED ALWAYS AS ((min_annual + max_annual) / 2) STORED,
    period      text    NOT NULL,    -- what the posting used: year, month, hour...
    predicted   boolean NOT NULL,    -- Adzuna's own estimate, not stated by the employer
    tier        text,                -- Ashby per-market tier title
    PRIMARY KEY (source, source_id, n),
    FOREIGN KEY (source, source_id) REFERENCES silver.postings
);

CREATE TABLE silver.adzuna_salary_histogram (
    country     text        NOT NULL,
    category    text,
    what        text,
    bucket_from numeric     NOT NULL,
    postings    integer     NOT NULL,
    fetched_at  timestamptz NOT NULL
);

CREATE TABLE silver.adzuna_salary_history (
    country     text        NOT NULL,
    category    text        NOT NULL,
    month       date        NOT NULL,
    avg_salary  numeric     NOT NULL,
    fetched_at  timestamptz NOT NULL,
    PRIMARY KEY (country, category, month)
);

CREATE TABLE silver.levelsfyi_benchmarks (
    job_family   text        NOT NULL,
    salary_type  text        NOT NULL,
    focus_tags   text        NOT NULL,
    location     text        NOT NULL,
    kind         text        NOT NULL,  -- location_percentiles or by_experience
    yoe_range    text,
    p10          numeric,
    p25          numeric,
    p50          numeric,
    p75          numeric,
    p90          numeric,
    sample_size  integer,
    fetched_at   timestamptz NOT NULL
);

-- One row per bronze file: what the pipeline collected and when.
CREATE TABLE silver.ingest_runs (
    source        text        NOT NULL,
    run_id        text        NOT NULL,
    ingest_date   date        NOT NULL,
    records       integer     NOT NULL,
    first_fetched timestamptz,
    last_fetched  timestamptz,
    PRIMARY KEY (source, run_id)
);

CREATE TABLE silver.load_log (
    loaded_at  timestamptz NOT NULL DEFAULT now(),
    postings   integer     NOT NULL,
    salaries   integer     NOT NULL,
    runs       integer     NOT NULL
);

CREATE INDEX ON silver.postings USING gin (regions);
CREATE INDEX ON silver.postings USING gin (technologies);
CREATE INDEX ON silver.postings (coalesce(published, first_seen));

-- Gold: views shaped for the dashboards. `region` is 'other' when unknown.

CREATE VIEW gold.posting_regions AS
SELECT p.*, coalesce(r.region, 'other') AS region
FROM silver.postings p
LEFT JOIN LATERAL unnest(nullif(p.regions, '{}')) AS r(region) ON true;

CREATE VIEW gold.salaries AS
SELECT s.*, p.title, p.role, p.company, p.location, p.country, p.url, p.regions,
       coalesce(p.published, p.first_seen) AS posted_at
FROM silver.posted_salaries s
JOIN silver.postings p USING (source, source_id);

CREATE VIEW gold.postings_monthly AS
SELECT date_trunc('month', coalesce(published, first_seen))::date AS month,
       source, region, role, count(*) AS postings
FROM gold.posting_regions
GROUP BY 1, 2, 3, 4;

-- Open postings that fit the profile: what the "For you" dashboard lists.
CREATE VIEW gold.feed AS
SELECT p.source, p.source_id, p.title, p.company, p.location, p.country, p.url, p.regions, p.role,
       p.first_seen, coalesce(p.published, p.first_seen) AS posted_at,
       m.score, m.rank, m.have, m.missing
FROM silver.postings p
JOIN silver.posting_matches m USING (source, source_id)
WHERE p.is_open AND m.fits;

-- One row per posting and technology it asks for.
CREATE VIEW gold.posting_technologies AS
SELECT p.source, p.source_id, p.role, p.regions, p.is_open,
       coalesce(p.published, p.first_seen) AS posted_at, t.key AS technology, t.label, t.category
FROM silver.postings p
CROSS JOIN LATERAL unnest(p.technologies) AS u(key)
JOIN silver.technologies t USING (key);

CREATE VIEW gold.source_health AS
SELECT source,
       count(*)              AS runs,
       max(ingest_date)      AS last_ingest,
       sum(records)          AS records,
       max(last_fetched)     AS last_fetched
FROM silver.ingest_runs
GROUP BY source;

-- Grafana reads through a read-only role, created by docker/postgres/init.
DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'grafana_reader') THEN
        GRANT USAGE ON SCHEMA silver, gold TO grafana_reader;
        GRANT SELECT ON ALL TABLES IN SCHEMA silver, gold TO grafana_reader;
    END IF;
END
$$;
