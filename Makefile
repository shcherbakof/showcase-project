SHELL := /bin/bash

.PHONY: up-db init-db reset-soft reset-hard up-airflow up-superset up-all smoke backfill qa

up-db:
	./scripts/up-db.sh

init-db:
	./scripts/init-db.sh

reset-soft:
	./scripts/reset-soft.sh

reset-hard:
	./scripts/reset-hard.sh

up-airflow:
	./scripts/up-airflow.sh

up-superset:
	./scripts/up-superset.sh

up-all:
	./scripts/up-all.sh

smoke:
	./scripts/smoke.sh

backfill:
	./scripts/raw-backfill.sh $(ARGS)

qa:
	./scripts/qa.sh
