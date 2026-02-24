-- Docs:
-- - artifacts/docs/data/3. Шаги выполнения checklist.md
-- - artifacts/docs/data/2.0 Стандарт разработки (рабочий, Lite).md
-- - artifacts/docs/datastand/0.2.4 log_work_chaitan_mashine.md

create table if not exists raw.vacancies (
  id bigserial primary key,
  run_id text not null,
  ingested_at timestamptz not null default now(),
  source_system text not null,
  endpoint text not null,
  request_params jsonb not null,
  http_status integer not null,
  payload jsonb not null,
  vacancy_id text not null,
  source_modified_at_raw text not null,
  source_modified_at timestamptz null,
  region_code_raw text null,
  response_meta jsonb null,
  request_url text null,
  payload_sha256 text null,
  constraint uq_raw_vacancies_version
    unique (source_system, vacancy_id, source_modified_at_raw)
);

create index if not exists ix_raw_vacancies_run_id
  on raw.vacancies (run_id);
create index if not exists ix_raw_vacancies_ingested_at
  on raw.vacancies (ingested_at desc);
create index if not exists ix_raw_vacancies_modified_at
  on raw.vacancies (source_modified_at desc);
create index if not exists ix_raw_vacancies_region
  on raw.vacancies (region_code_raw);

create table if not exists raw.quarantine (
  id bigserial primary key,
  run_id text not null,
  ingested_at timestamptz not null default now(),
  source_system text not null,
  endpoint text not null,
  request_params jsonb not null,
  http_status integer null,
  payload jsonb null,
  error_type text not null,
  error_reason text null,
  vacancy_id_raw text null
);

create index if not exists ix_raw_quarantine_run_id
  on raw.quarantine (run_id);
create index if not exists ix_raw_quarantine_ingested_at
  on raw.quarantine (ingested_at desc);

create table if not exists mon.pipeline_runs (
  run_id text primary key,
  dag_id text not null,
  run_type text not null default 'scheduled',
  status text not null,
  started_at timestamptz not null,
  finished_at timestamptz null,
  duration_sec integer null,
  window_from timestamptz null,
  window_to timestamptz null,
  source_system text not null default 'trudvsem',
  requests_total integer not null default 0,
  requests_success integer not null default 0,
  http_429_count integer not null default 0,
  http_5xx_count integer not null default 0,
  parse_error_count integer not null default 0,
  items_extracted integer not null default 0,
  raw_rows_inserted integer not null default 0,
  raw_rows_skipped_conflict integer not null default 0,
  quarantine_rows integer not null default 0,
  max_source_modified_at timestamptz null,
  max_ingested_at timestamptz null,
  error_summary text null,
  created_at timestamptz not null default now(),
  constraint chk_pipeline_runs_status
    check (status in ('success', 'partial', 'failed')),
  constraint chk_pipeline_runs_run_type
    check (run_type in ('scheduled', 'manual', 'backfill'))
);

create index if not exists ix_mon_pipeline_runs_dag_started
  on mon.pipeline_runs (dag_id, started_at desc);
create index if not exists ix_mon_pipeline_runs_status_started
  on mon.pipeline_runs (status, started_at desc);
