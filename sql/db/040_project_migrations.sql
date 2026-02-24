-- Docs:
-- - artifacts/docs/data/3. Шаги выполнения checklist.md
-- - artifacts/docs/data/2.0 Стандарт разработки (рабочий, Lite).md
-- - artifacts/docs/datastand/0.2.4 log_work_chaitan_mashine.md

CREATE TABLE IF NOT EXISTS mon.applied_migrations (
  migration_key text PRIMARY KEY,
  applied_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE mon.applied_migrations OWNER TO :"PROJECT_USER";