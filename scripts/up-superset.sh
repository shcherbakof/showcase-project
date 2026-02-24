#!/usr/bin/env bash
# Docs:
# - scripts/README.md
# - artifacts/docs/data/5.1 Мониторинг Superset Pipeline & Data Health (MVP).md
# - artifacts/docs/datastand/0.2.4 log_work_chaitan_mashine.md
set -euo pipefail
source "$(dirname "$0")/lib.sh"
cd_root

require_compose

dcf --profile db up -d postgres
wait_healthy postgres 60 2

dcf --profile superset build superset-init superset
dcf --profile superset run --rm superset-init
dcf --profile superset up -d superset
