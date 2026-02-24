#!/usr/bin/env bash
# Docs:
# - scripts/README.md
# - artifacts/docs/datastand/0.2.2. Compose базовый каркас.md
# - artifacts/docs/datastand/0.2.4 log_work_chaitan_mashine.md
set -euo pipefail
source "$(dirname "$0")/lib.sh"
cd_root

require_compose

"$(dirname "$0")/up-db.sh"
"$(dirname "$0")/init-db.sh"
"$(dirname "$0")/up-airflow.sh"
"$(dirname "$0")/up-superset.sh"
