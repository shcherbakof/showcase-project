#!/usr/bin/env bash
# Docs:
# - scripts/README.md
# - artifacts/docs/datastand/0.2.3.2 Сервис `db-init` one-shot (profile `db-init`).md
set -euo pipefail
source "$(dirname "$0")/lib.sh"
cd_root

require_compose

# гарантируем, что postgres поднят
dcf --profile db up -d postgres
wait_healthy postgres 60 2

# one-shot init (повторяемый)
dcf --profile db-init run --rm db-init
