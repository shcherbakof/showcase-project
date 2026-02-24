#!/usr/bin/env bash
set -euo pipefail

log() { printf '[db-init] %s\n' "$*"; }

: "${PGHOST:=postgres}"
: "${PGPORT:=5432}"
: "${PGUSER:?PGUSER is required}"
: "${PGPASSWORD:?PGPASSWORD is required}"

: "${PROJECT_DB:?PROJECT_DB is required}"
: "${PROJECT_USER:?PROJECT_USER is required}"
: "${PROJECT_PASS:?PROJECT_PASS is required}"

: "${AIRFLOW_DB:?AIRFLOW_DB is required}"
: "${AIRFLOW_USER:?AIRFLOW_USER is required}"
: "${AIRFLOW_PASS:?AIRFLOW_PASS is required}"

: "${SUPERSET_DB:?SUPERSET_DB is required}"
: "${SUPERSET_USER:?SUPERSET_USER is required}"
: "${SUPERSET_PASS:?SUPERSET_PASS is required}"

: "${DB_SEED_ENABLED:=1}"
: "${MODE:=full-init}"

PSQL_BASE=(psql -v ON_ERROR_STOP=1 -h "$PGHOST" -p "$PGPORT" -U "$PGUSER")

wait_pg() {
  log "waiting postgres ($PGHOST:$PGPORT) ..."
  for _ in $(seq 1 60); do
    if pg_isready -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" >/dev/null 2>&1; then
      log "postgres is ready"
      return 0
    fi
    sleep 2
  done
  log "postgres did not become ready"
  exit 1
}

run_file() {
  local db="$1"
  local file="$2"
  log "apply $(basename "$file") on db=$db"
  "${PSQL_BASE[@]}" -d "$db" \
    -v PROJECT_DB="$PROJECT_DB" -v PROJECT_USER="$PROJECT_USER" -v PROJECT_PASS="$PROJECT_PASS" \
    -v AIRFLOW_DB="$AIRFLOW_DB" -v AIRFLOW_USER="$AIRFLOW_USER" -v AIRFLOW_PASS="$AIRFLOW_PASS" \
    -v SUPERSET_DB="$SUPERSET_DB" -v SUPERSET_USER="$SUPERSET_USER" -v SUPERSET_PASS="$SUPERSET_PASS" \
    -f "$file"
}

apply_migrations_dir() {
  local db="$1"
  local dir="$2"

  if [[ ! -d "$dir" ]]; then
    log "migrations dir not found: $dir (skip)"
    return 0
  fi

  shopt -s nullglob
  local files=("$dir"/*.sql)
  shopt -u nullglob

  if (( ${#files[@]} == 0 )); then
    log "no migrations in $dir (skip)"
    return 0
  fi

  for f in "${files[@]}"; do
    local key
    key="$(basename "$f")"

    local applied
    applied="$("${PSQL_BASE[@]}" -d "$db" -Atc \
      "select 1 from mon.applied_migrations where migration_key = '$key' limit 1;" || true)"

    if [[ "$applied" == "1" ]]; then
      log "skip migration (already applied): $key"
      continue
    fi

    log "apply migration: $key"
    "${PSQL_BASE[@]}" -d "$db" -v ON_ERROR_STOP=1 <<SQL
BEGIN;
\\i '$f'
INSERT INTO mon.applied_migrations(migration_key) VALUES ('$key');
COMMIT;
SQL
  done
}

main() {
  wait_pg

  if [[ "$MODE" == "full-init" ]]; then
    # строгий порядок base-init
    run_file "postgres" "/sql/db/000_roles.sql"
    run_file "postgres" "/sql/db/010_databases.sql"

    run_file "$PROJECT_DB" "/sql/db/020_extensions.sql"
    run_file "$PROJECT_DB" "/sql/db/030_project_schemas.sql"
    run_file "$PROJECT_DB" "/sql/db/040_project_migrations.sql"
    run_file "$PROJECT_DB" "/sql/db/050_project_baseline.sql"

    # будущие миграции (ключ = имя файла)
    apply_migrations_dir "$PROJECT_DB" "/sql/db/project/migrations"
    run_file "$PROJECT_DB" "/sql/db/060_airflow_grants.sql"

    if [[ "$DB_SEED_ENABLED" == "1" ]]; then
      run_file "$PROJECT_DB" "/sql/db/900_seed.sql"
    else
      log "seed disabled (DB_SEED_ENABLED=$DB_SEED_ENABLED)"
    fi
  elif [[ "$MODE" == "reset-soft" ]]; then
    run_file "$PROJECT_DB" "/sql/db/800_soft_reset.sql"
    run_file "$PROJECT_DB" "/sql/db/030_project_schemas.sql"
    run_file "$PROJECT_DB" "/sql/db/040_project_migrations.sql"
    run_file "$PROJECT_DB" "/sql/db/050_project_baseline.sql"
    run_file "$PROJECT_DB" "/sql/db/060_airflow_grants.sql"

    if [[ "$DB_SEED_ENABLED" == "1" ]]; then
      run_file "$PROJECT_DB" "/sql/db/900_seed.sql"
    else
      log "seed disabled (DB_SEED_ENABLED=$DB_SEED_ENABLED)"
    fi
  else
    log "unknown MODE=$MODE (supported: full-init, reset-soft)"
    exit 2
  fi

  log "done"
}

main "$@"
