-- Docs:
-- - artifacts/docs/data/3. Шаги выполнения checklist.md
-- - artifacts/docs/data/2.0 Стандарт разработки (рабочий, Lite).md
-- - artifacts/docs/datastand/0.2.4 log_work_chaitan_mashine.md

CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS stg;
CREATE SCHEMA IF NOT EXISTS mart;
CREATE SCHEMA IF NOT EXISTS mon;

ALTER SCHEMA raw  OWNER TO :"PROJECT_USER";
ALTER SCHEMA stg  OWNER TO :"PROJECT_USER";
ALTER SCHEMA mart OWNER TO :"PROJECT_USER";
ALTER SCHEMA mon  OWNER TO :"PROJECT_USER";