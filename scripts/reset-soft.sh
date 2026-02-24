#!/usr/bin/env bash
# Docs:
# - scripts/README.md
# - artifacts/docs/datastand/0.2.2. Compose базовый каркас.md
# - artifacts/docs/datastand/0.2.3.2 Сервис `db-init` one-shot (profile `db-init`).md
set -euo pipefail
source "$(dirname "$0")/lib.sh"
cd_root

require_compose

dcf --profile db up -d postgres
wait_healthy postgres 60 2
dcf --profile db-init run --rm -e MODE=reset-soft db-init
