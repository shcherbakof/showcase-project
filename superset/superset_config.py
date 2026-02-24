# Docs:
# - artifacts/docs/data/5.1 Мониторинг Superset Pipeline & Data Health (MVP).md
# - artifacts/docs/datastand/0.2.4 log_work_chaitan_mashine.md

import os

SECRET_KEY = os.getenv("SUPERSET_SECRET_KEY", "dev-only-secret-key")
SQLALCHEMY_DATABASE_URI = os.getenv("SUPERSET__SQLALCHEMY_DATABASE_URI")

FEATURE_FLAGS = {
    "DASHBOARD_RBAC": True,
}

TALISMAN_ENABLED = False
