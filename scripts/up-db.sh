#!/usr/bin/env bash
# Docs:
# - scripts/README.md
# - artifacts/docs/datastand/0.2.3 Модуль Postgres.md
# - artifacts/docs/datastand/0.2.4 log_work_chaitan_mashine.md
set -euo pipefail
source "$(dirname "$0")/lib.sh"
cd_root

require_compose

dcf --profile db up -d postgres
wait_healthy postgres 60 2
