-- Docs:
-- - artifacts/docs/data/3. Шаги выполнения checklist.md
-- - artifacts/docs/data/2.0 Стандарт разработки (рабочий, Lite).md
-- - artifacts/docs/datastand/0.2.4 log_work_chaitan_mashine.md

CREATE TABLE IF NOT EXISTS raw.vacancies_raw (
  id bigserial PRIMARY KEY,
  source text NOT NULL,
  run_id text NOT NULL,
  fetched_at timestamptz NOT NULL,
  payload jsonb NOT NULL,
  CONSTRAINT uq_raw_source_run UNIQUE (source, run_id)
);

CREATE TABLE IF NOT EXISTS stg.vacancies (
  vacancy_id text PRIMARY KEY,
  region text NOT NULL,
  employer text,
  title text,
  published_at date,
  loaded_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS mart.vacancies_daily (
  dt date NOT NULL,
  region text NOT NULL,
  vacancies_count integer NOT NULL,
  PRIMARY KEY (dt, region)
);

CREATE TABLE IF NOT EXISTS mon.dag_runs_daily (
  dt date NOT NULL,
  dag_id text NOT NULL,
  status text NOT NULL,
  runs integer NOT NULL,
  PRIMARY KEY (dt, dag_id, status)
);

CREATE TABLE IF NOT EXISTS mart.demo_kpi_daily (
  dt date PRIMARY KEY,
  vacancies_cnt integer NOT NULL,
  employers_cnt integer NOT NULL
);

CREATE TABLE IF NOT EXISTS mon.demo_dag_runs_daily (
  dt date PRIMARY KEY,
  dag_runs_cnt integer NOT NULL,
  failed_cnt integer NOT NULL
);

ALTER TABLE raw.vacancies_raw OWNER TO :"PROJECT_USER";
ALTER TABLE stg.vacancies OWNER TO :"PROJECT_USER";
ALTER TABLE mart.vacancies_daily OWNER TO :"PROJECT_USER";
ALTER TABLE mon.dag_runs_daily OWNER TO :"PROJECT_USER";
ALTER TABLE mart.demo_kpi_daily OWNER TO :"PROJECT_USER";
ALTER TABLE mon.demo_dag_runs_daily OWNER TO :"PROJECT_USER";
