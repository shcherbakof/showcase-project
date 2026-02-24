-- Docs:
-- - artifacts/docs/data/3. Шаги выполнения checklist.md
-- - artifacts/docs/data/2.0 Стандарт разработки (рабочий, Lite).md
-- - artifacts/docs/datastand/0.2.4 log_work_chaitan_mashine.md

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'chk_stg_vacancies_source_modified_at_not_future'
  ) THEN
    ALTER TABLE stg.vacancies
      ADD CONSTRAINT chk_stg_vacancies_source_modified_at_not_future
      CHECK (source_modified_at <= now() + interval '1 day');
  END IF;
END;
$$;

create or replace view mon.v_stg_vacancies_dq as
select
  count(*)::bigint as total_rows,
  count(*) filter (where vacancy_id is null)::bigint as null_vacancy_id_rows,
  count(*) filter (where employer_key is null or trim(employer_key) = '')::bigint as null_or_empty_employer_key_rows,
  count(*) filter (where salary_from is not null and salary_from < 0)::bigint as salary_from_negative_rows,
  count(*) filter (where salary_to is not null and salary_to < 0)::bigint as salary_to_negative_rows,
  count(*) filter (
    where salary_from is not null
      and salary_to is not null
      and salary_from > salary_to
  )::bigint as salary_range_invalid_rows,
  count(*) filter (where source_modified_at is null)::bigint as source_modified_at_null_rows,
  count(*) filter (
    where source_modified_at > now() + interval '1 day'
  )::bigint as source_modified_at_future_rows,
  count(*) filter (
    where status_norm not in ('ACTIVE', 'INACTIVE', 'UNKNOWN')
  )::bigint as status_norm_invalid_rows,
  now() as checked_at
from stg.vacancies;

comment on view mon.v_stg_vacancies_dq
is 'STG DQ summary for vacancies: key nullability, salary range checks, and source_modified_at future-window checks.';
