#!/bin/sh
# Runs once, when the database volume is created. Grafana connects as this
# read-only role; `jobpipe load` grants it SELECT on every rebuild.
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v reader_password="$GRAFANA_DB_PASSWORD" <<'SQL'
CREATE ROLE grafana_reader LOGIN PASSWORD :'reader_password';
SQL

# Separate database for the integration tests, so they never touch real data.
createdb --username "$POSTGRES_USER" --owner "$POSTGRES_USER" jobpipe_test
