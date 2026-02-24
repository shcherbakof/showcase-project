-- Docs:
-- - artifacts/docs/data/3. Шаги выполнения checklist.md
-- - artifacts/docs/data/2.0 Стандарт разработки (рабочий, Lite).md
-- - artifacts/docs/datastand/0.2.4 log_work_chaitan_mashine.md

SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'PROJECT_USER', :'PROJECT_PASS')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'PROJECT_USER')
\gexec

SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'AIRFLOW_USER', :'AIRFLOW_PASS')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'AIRFLOW_USER')
\gexec

SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'SUPERSET_USER', :'SUPERSET_PASS')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'SUPERSET_USER')
\gexec

SELECT format('ALTER ROLE %I WITH LOGIN PASSWORD %L', :'PROJECT_USER', :'PROJECT_PASS')
\gexec

SELECT format('ALTER ROLE %I WITH LOGIN PASSWORD %L', :'AIRFLOW_USER', :'AIRFLOW_PASS')
\gexec

SELECT format('ALTER ROLE %I WITH LOGIN PASSWORD %L', :'SUPERSET_USER', :'SUPERSET_PASS')
\gexec
