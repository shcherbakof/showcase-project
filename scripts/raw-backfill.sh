#!/usr/bin/env bash
# Docs:
# - scripts/README.md
# - artifacts/docs/data/3.1.5.3 Ручной backfill CLI (MVP).md
# - artifacts/docs/artifacts_works_gpt/2_session_summary_2026-02-21_20-24.md
set -euo pipefail
source "$(dirname "$0")/lib.sh"
cd_root

export PYTHONPATH="${PROJECT_ROOT}/src:${PYTHONPATH:-}"
.venv/bin/python src/jobs/raw_backfill_cli.py "$@"
