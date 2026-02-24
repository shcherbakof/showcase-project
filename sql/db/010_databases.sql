-- Docs:
-- - artifacts/docs/data/3. Шаги выполнения checklist.md
-- - artifacts/docs/data/2.0 Стандарт разработки (рабочий, Lite).md
-- - artifacts/docs/datastand/0.2.4 log_work_chaitan_mashine.md

SELECT format('CREATE DATABASE %I OWNER %I', :'PROJECT_DB', :'PROJECT_USER')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'PROJECT_DB')
\gexec

SELECT format('CREATE DATABASE %I OWNER %I', :'AIRFLOW_DB', :'AIRFLOW_USER')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'AIRFLOW_DB')
\gexec

SELECT format('CREATE DATABASE %I OWNER %I', :'SUPERSET_DB', :'SUPERSET_USER')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'SUPERSET_DB')
\gexec