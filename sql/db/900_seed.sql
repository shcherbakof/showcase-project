-- Docs:
-- - artifacts/docs/data/3. Шаги выполнения checklist.md
-- - artifacts/docs/data/2.0 Стандарт разработки (рабочий, Lite).md
-- - artifacts/docs/datastand/0.2.4 log_work_chaitan_mashine.md

WITH d AS (
  SELECT (current_date - offs)::date AS dt
  FROM generate_series(0, 29) AS offs
)
INSERT INTO mart.demo_kpi_daily (dt, vacancies_cnt, employers_cnt)
SELECT
  dt,
  (1000 + (extract(day from dt)::int * 7))::int,
  (120 + (extract(day from dt)::int % 10))::int
FROM d
ON CONFLICT (dt) DO NOTHING;

WITH d AS (
  SELECT (current_date - offs)::date AS dt
  FROM generate_series(0, 29) AS offs
)
INSERT INTO mon.demo_dag_runs_daily (dt, dag_runs_cnt, failed_cnt)
SELECT
  dt,
  12,
  (extract(day from dt)::int % 3)
FROM d
ON CONFLICT (dt) DO NOTHING;