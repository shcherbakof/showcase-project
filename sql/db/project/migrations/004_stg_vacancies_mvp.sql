-- Docs:
-- - artifacts/docs/data/3. Шаги выполнения checklist.md
-- - artifacts/docs/data/2.0 Стандарт разработки (рабочий, Lite).md
-- - artifacts/docs/datastand/0.2.4 log_work_chaitan_mashine.md

alter table if exists stg.vacancies
  add column if not exists source_system text;

update stg.vacancies
set source_system = 'trudvsem'
where source_system is null;

alter table if exists stg.vacancies
  alter column source_system set default 'trudvsem',
  alter column source_system set not null;

alter table if exists stg.vacancies
  add column if not exists run_id text;

update stg.vacancies
set run_id = 'legacy_bootstrap'
where run_id is null;

alter table if exists stg.vacancies
  alter column run_id set not null;

alter table if exists stg.vacancies
  add column if not exists source_modified_at timestamptz;

update stg.vacancies
set source_modified_at = coalesce(source_modified_at, loaded_at, now())
where source_modified_at is null;

alter table if exists stg.vacancies
  alter column source_modified_at set not null;

alter table if exists stg.vacancies
  add column if not exists region_raw text;

update stg.vacancies
set region_raw = coalesce(nullif(region_raw, ''), nullif(region, ''), 'UNKNOWN')
where region_raw is null or region_raw = '';

alter table if exists stg.vacancies
  alter column region_raw set default 'UNKNOWN',
  alter column region_raw set not null;

alter table if exists stg.vacancies
  add column if not exists status_raw text;

update stg.vacancies
set status_raw = coalesce(nullif(status_raw, ''), 'UNKNOWN')
where status_raw is null or status_raw = '';

alter table if exists stg.vacancies
  alter column status_raw set default 'UNKNOWN',
  alter column status_raw set not null;

alter table if exists stg.vacancies
  add column if not exists salary_raw jsonb;

alter table if exists stg.vacancies
  add column if not exists profession_raw text;

alter table if exists stg.vacancies
  add column if not exists employer_key text;

update stg.vacancies
set employer_key = coalesce(nullif(employer_key, ''), nullif(employer, ''), 'UNKNOWN_EMPLOYER:' || vacancy_id)
where employer_key is null or employer_key = '';

alter table if exists stg.vacancies
  alter column employer_key set not null;

alter table if exists stg.vacancies
  add column if not exists last_raw_ingested_at timestamptz;

update stg.vacancies
set last_raw_ingested_at = coalesce(last_raw_ingested_at, loaded_at, now())
where last_raw_ingested_at is null;

alter table if exists stg.vacancies
  alter column last_raw_ingested_at set default now(),
  alter column last_raw_ingested_at set not null;

alter table if exists stg.vacancies
  add column if not exists stg_updated_at timestamptz;

update stg.vacancies
set stg_updated_at = coalesce(stg_updated_at, loaded_at, now())
where stg_updated_at is null;

alter table if exists stg.vacancies
  alter column stg_updated_at set default now(),
  alter column stg_updated_at set not null;

create index if not exists ix_stg_vacancies_employer_key
  on stg.vacancies (employer_key);

create index if not exists ix_stg_vacancies_source_modified_at
  on stg.vacancies (source_modified_at desc);

create index if not exists ix_stg_vacancies_region_raw
  on stg.vacancies (region_raw);
