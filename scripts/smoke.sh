#!/usr/bin/env bash
# Docs:
# - scripts/README.md
# - artifacts/docs/datastand/0.2.3.2 Сервис `db-init` one-shot (profile `db-init`).md
# - artifacts/docs/datastand/0.2.4 log_work_chaitan_mashine.md
set -euo pipefail
source "$(dirname "$0")/lib.sh"
cd_root

require_compose

# 1) Compose config валиден
dcf config >/dev/null

# 2) postgres healthy
dcf --profile db up -d postgres
wait_healthy postgres 60 2

# 3) Проверка, что порты поднялись (если опубликованы в compose)
# Примечание: это smoke “по факту”, без curl-зависимостей на схемы/таблицы.
need_cmd docker

echo "Containers:"
dcf ps

set -a
if [[ -f .env.example ]]; then
  # shellcheck disable=SC1091
  source .env.example
fi
if [[ -f .env ]]; then
  # shellcheck disable=SC1091
  source .env
fi
set +a

"$(dirname "$0")/db-smoke.sh"

echo "OK: smoke passed"
