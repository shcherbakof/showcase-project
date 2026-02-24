#!/usr/bin/env bash
# Docs:
# - scripts/README.md
# - artifacts/docs/data/4.2 Оркестрация Airflow end-to-end (MVP).md
# - artifacts/docs/datastand/0.2.4 log_work_chaitan_mashine.md
set -euo pipefail
source "$(dirname "$0")/lib.sh"
cd_root

require_compose

# postgres должен жить
dcf --profile db up -d postgres
wait_healthy postgres 60 2

# гарантируем, что airflow-образы актуальны
dcf --profile airflow build airflow-init airflow-webserver airflow-scheduler

# airflow init one-shot, потом сервисы
dcf --profile airflow run --rm --entrypoint /bin/bash airflow-init -c \
  'airflow db migrate && if ! airflow users list | grep -q "${AIRFLOW_ADMIN_USERNAME:-admin}"; then airflow users create --role Admin --username "${AIRFLOW_ADMIN_USERNAME:-admin}" --password "${AIRFLOW_ADMIN_PASSWORD:-admin}" --firstname "${AIRFLOW_ADMIN_FIRSTNAME:-Admin}" --lastname "${AIRFLOW_ADMIN_LASTNAME:-User}" --email "${AIRFLOW_ADMIN_EMAIL:-admin@example.com}"; fi'
dcf --profile airflow up -d airflow-webserver airflow-scheduler
