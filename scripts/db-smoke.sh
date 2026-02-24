#!/usr/bin/env bash
# Docs:
# - scripts/README.md
# - artifacts/docs/datastand/0.2.3.2 Сервис `db-init` one-shot (profile `db-init`).md
set -euo pipefail

: "${POSTGRES_SUPERUSER:?}"
: "${POSTGRES_SUPERPASS:?}"
: "${POSTGRES_HOST_PORT:?}"
: "${PROJECT_DB:?}"
: "${AIRFLOW_DB:?}"
: "${SUPERSET_DB:?}"

export PGPASSWORD="$POSTGRES_SUPERPASS"

psqlh() { psql -v ON_ERROR_STOP=1 -h 127.0.0.1 -p "$POSTGRES_HOST_PORT" -U "$POSTGRES_SUPERUSER" "$@"; }

echo "[smoke] check databases exist..."
cnt="$(psqlh -d postgres -Atc \
  "select count(*) from pg_database where datname in ('$PROJECT_DB','$AIRFLOW_DB','$SUPERSET_DB');")"
[[ "$cnt" == "3" ]] || { echo "expected 3 dbs, got $cnt"; exit 1; }

echo "[smoke] check schemas in project_db..."
scnt="$(psqlh -d "$PROJECT_DB" -Atc \
  "select count(*) from information_schema.schemata where schema_name in ('raw','stg','mart','mon');")"
[[ "$scnt" == "4" ]] || { echo "expected 4 schemas, got $scnt"; exit 1; }

echo "[smoke] check applied_migrations exists..."
t="$(psqlh -d "$PROJECT_DB" -Atc "select to_regclass('mon.applied_migrations') is not null;")"
[[ "$t" == "t" ]] || { echo "applied_migrations not found"; exit 1; }

echo "[smoke] check seed demo tables (may be empty if DB_SEED_ENABLED=0)..."
kpi="$(psqlh -d "$PROJECT_DB" -Atc "select count(*) from mart.demo_kpi_daily;")"
mon="$(psqlh -d "$PROJECT_DB" -Atc "select count(*) from mon.demo_dag_runs_daily;")"
echo "[smoke] mart.demo_kpi_daily rows=$kpi, mon.demo_dag_runs_daily rows=$mon"

echo "[smoke] OK"
