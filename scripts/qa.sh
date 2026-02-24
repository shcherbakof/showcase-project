#!/usr/bin/env bash
# Docs:
# - scripts/README.md
# - artifacts/docs/data/2.0 Стандарт разработки (рабочий, Lite).md
# - artifacts/docs/artifacts_works_gpt/27_session_summary_2026-02-23_19-28_refactor_standard_compliance_and_qa.md
set -euo pipefail
source "$(dirname "$0")/lib.sh"
cd_root

echo "[qa] 1/5 unit tests"
.venv/bin/python -m unittest discover -s test -p 'test_*.py'

echo "[qa] 2/5 init-db"
./scripts/init-db.sh

echo "[qa] 3/5 smoke"
./scripts/smoke.sh

if [[ "${SKIP_SECURITY_SCANS:-0}" == "1" ]]; then
  echo "[qa] 4-5/5 security scans skipped (SKIP_SECURITY_SCANS=1)"
  exit 0
fi

need_cmd gitleaks
need_cmd pip-audit

echo "[qa] 4/5 secret scan"
gitleaks detect --source . --no-banner

echo "[qa] 5/5 dependency scan"
pip-audit -r requirements.txt
if [[ -f requirements-airflow.txt ]]; then
  pip-audit -r requirements-airflow.txt
fi

echo "OK: qa passed"
