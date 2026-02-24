#!/usr/bin/env bash
set -euo pipefail

mode="${1:-run}"

export SUPERSET_CONFIG_PATH=/app/project/superset/superset_config.py

wait_for_db() {
  python - <<'PY'
import os
import time
import sqlalchemy as sa

uri = os.environ["SUPERSET__SQLALCHEMY_DATABASE_URI"]
for _ in range(60):
    try:
        engine = sa.create_engine(uri)
        with engine.connect() as conn:
            conn.execute(sa.text("select 1"))
        print("superset db is ready")
        raise SystemExit(0)
    except Exception:
        time.sleep(2)
raise SystemExit(1)
PY
}

init_superset() {
  wait_for_db
  superset db upgrade
  superset fab create-admin \
    --username "$SUPERSET_ADMIN_USERNAME" \
    --firstname "$SUPERSET_ADMIN_FIRSTNAME" \
    --lastname "$SUPERSET_ADMIN_LASTNAME" \
    --email "$SUPERSET_ADMIN_EMAIL" \
    --password "$SUPERSET_ADMIN_PASSWORD" || true
  superset init
  superset set-database-uri -d project_db -u "$PROJECT_DB_URI"

  if [[ -f /app/project/superset/assets/datasources.yaml ]]; then
    superset import-datasources -p /app/project/superset/assets/datasources.yaml || true
  fi

  if [[ -f /app/project/superset/assets/build_pipeline_health_dashboard.py ]]; then
    python /app/project/superset/assets/build_pipeline_health_dashboard.py
  fi

  if [[ -f /app/project/superset/assets/build_business_health_dashboard.py ]]; then
    python /app/project/superset/assets/build_business_health_dashboard.py
  fi
}

case "$mode" in
  init)
    init_superset
    ;;
  run)
    superset run -h 0.0.0.0 -p 8088
    ;;
  *)
    echo "Unknown mode: $mode"
    exit 2
    ;;
esac
