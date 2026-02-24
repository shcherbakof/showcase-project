# Управление стендом

Команды запускаются из корня репозитория.

- Полный стенд: `make up-all`
- Только БД: `make up-db && make init-db`
- Airflow: `make up-airflow`
- Superset: `make up-superset`
- Smoke-проверка: `make smoke`
- Локальный quality gate: `make qa`
- Ручной backfill RAW: `make backfill ARGS="--window-from ... --window-to ... [--region-code ...]"`
- Soft reset БД: `make reset-soft`
- Hard reset всего стенда: `make reset-hard`

`make qa` выполняет:
- unit tests (`.venv/bin/python -m unittest discover -s test -p 'test_*.py'`)
- `make init-db`
- `make smoke`
- secret scan (`gitleaks detect --source . --no-banner`)
- dependency scan (`pip-audit -r requirements*.txt`)

Чтобы пропустить security scans локально (не рекомендуется): `SKIP_SECURITY_SCANS=1 make qa`.

UI:
- Airflow: `http://localhost:8080` (`admin` / `admin`)
- Superset: `http://localhost:8088` (`admin` / `admin`)

## См. также

- [Корневой README](../README.md)
- [Навигатор документации artifacts](../artifacts/docs/README.md)
- [Инфра-контекст по скриптам](../artifacts/docs/datastand/0.2.4%20log_work_chaitan_mashine.md)
- [Стандарт разработки](../artifacts/docs/data/2.0%20Стандарт%20разработки%20(рабочий,%20Lite).md)
