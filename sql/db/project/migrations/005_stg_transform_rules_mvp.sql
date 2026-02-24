-- Docs:
-- - artifacts/docs/data/3. Шаги выполнения checklist.md
-- - artifacts/docs/data/2.0 Стандарт разработки (рабочий, Lite).md
-- - artifacts/docs/datastand/0.2.4 log_work_chaitan_mashine.md

create table if not exists stg.ref_vacancy_status_map (
  status_raw_norm text primary key,
  status_norm text not null,
  is_active boolean null
);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'chk_ref_vacancy_status_map_status_norm'
  ) THEN
    ALTER TABLE stg.ref_vacancy_status_map
      ADD CONSTRAINT chk_ref_vacancy_status_map_status_norm
      CHECK (status_norm in ('ACTIVE', 'INACTIVE', 'UNKNOWN'));
  END IF;
END;
$$;

insert into stg.ref_vacancy_status_map (status_raw_norm, status_norm, is_active)
values
  ('active', 'ACTIVE', true),
  ('активна', 'ACTIVE', true),
  ('актуальна', 'ACTIVE', true),
  ('опубликована', 'ACTIVE', true),
  ('размещена', 'ACTIVE', true),
  ('открыта', 'ACTIVE', true),
  ('inactive', 'INACTIVE', false),
  ('закрыта', 'INACTIVE', false),
  ('снята', 'INACTIVE', false),
  ('в архиве', 'INACTIVE', false),
  ('архив', 'INACTIVE', false),
  ('приостановлена', 'INACTIVE', false),
  ('unknown', 'UNKNOWN', null)
on conflict (status_raw_norm) do update
set
  status_norm = excluded.status_norm,
  is_active = excluded.is_active;

alter table if exists stg.vacancies
  add column if not exists status_norm text;

alter table if exists stg.vacancies
  add column if not exists is_active boolean;

update stg.vacancies v
set
  status_norm = m.status_norm,
  is_active = m.is_active
from stg.ref_vacancy_status_map m
where lower(trim(v.status_raw)) = m.status_raw_norm;

update stg.vacancies
set
  status_norm = 'UNKNOWN',
  is_active = null
where status_norm is null;

alter table if exists stg.vacancies
  alter column status_norm set default 'UNKNOWN',
  alter column status_norm set not null;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'chk_stg_vacancies_status_norm'
  ) THEN
    ALTER TABLE stg.vacancies
      ADD CONSTRAINT chk_stg_vacancies_status_norm
      CHECK (status_norm in ('ACTIVE', 'INACTIVE', 'UNKNOWN'));
  END IF;
END;
$$;

alter table if exists stg.vacancies
  add column if not exists salary_from numeric(14,2);

alter table if exists stg.vacancies
  add column if not exists salary_to numeric(14,2);

alter table if exists stg.vacancies
  add column if not exists salary_mid numeric(14,2);

alter table if exists stg.vacancies
  add column if not exists currency text;

with raw_salary as (
  select
    vacancy_id,
    substring(
      coalesce(
        salary_raw ->> 'salary_min',
        salary_raw ->> 'from',
        salary_raw ->> 'min',
        ''
      )
      from '[-]?[0-9]+(?:[.][0-9]+)?'
    ) as from_txt,
    substring(
      coalesce(
        salary_raw ->> 'salary_max',
        salary_raw ->> 'to',
        salary_raw ->> 'max',
        ''
      )
      from '[-]?[0-9]+(?:[.][0-9]+)?'
    ) as to_txt,
    upper(
      regexp_replace(
        coalesce(
          salary_raw ->> 'currency',
          salary_raw ->> 'currency_code',
          salary_raw ->> 'currency_full',
          ''
        ),
        '[^[:alnum:]А-Яа-я]',
        '',
        'g'
      )
    ) as currency_txt
  from stg.vacancies
), parsed_salary as (
  select
    vacancy_id,
    case
      when from_txt ~ '^-?[0-9]+(\\.[0-9]+)?$' then from_txt::numeric(14,2)
      else null
    end as from_raw_num,
    case
      when to_txt ~ '^-?[0-9]+(\\.[0-9]+)?$' then to_txt::numeric(14,2)
      else null
    end as to_raw_num,
    case
      when currency_txt in ('RUB', 'RUR', 'РУБ', 'РУБЛЬ', 'РУБЛЕЙ') then 'RUB'
      when currency_txt in ('USD', 'ДОЛЛАР', 'ДОЛЛАРОВ') then 'USD'
      when currency_txt in ('EUR', 'ЕВРО') then 'EUR'
      when currency_txt = '' then 'UNKNOWN'
      else currency_txt
    end as currency_norm
  from raw_salary
), non_negative_salary as (
  select
    vacancy_id,
    case when from_raw_num is not null and from_raw_num >= 0 then from_raw_num else null end as from_num,
    case when to_raw_num is not null and to_raw_num >= 0 then to_raw_num else null end as to_num,
    currency_norm
  from parsed_salary
), final_salary as (
  select
    vacancy_id,
    case
      when from_num is not null and to_num is not null then least(from_num, to_num)
      else from_num
    end as salary_from,
    case
      when from_num is not null and to_num is not null then greatest(from_num, to_num)
      else to_num
    end as salary_to,
    case
      when from_num is not null and to_num is not null then round(((least(from_num, to_num) + greatest(from_num, to_num)) / 2.0)::numeric, 2)
      when from_num is not null then from_num
      when to_num is not null then to_num
      else null
    end as salary_mid,
    currency_norm as currency
  from non_negative_salary
)
update stg.vacancies v
set
  salary_from = f.salary_from,
  salary_to = f.salary_to,
  salary_mid = f.salary_mid,
  currency = f.currency
from final_salary f
where v.vacancy_id = f.vacancy_id
  and (
    v.salary_from is distinct from f.salary_from
    or v.salary_to is distinct from f.salary_to
    or v.salary_mid is distinct from f.salary_mid
    or v.currency is distinct from f.currency
  );

update stg.vacancies
set currency = 'UNKNOWN'
where currency is null or trim(currency) = '';

alter table if exists stg.vacancies
  alter column currency set default 'UNKNOWN',
  alter column currency set not null;

alter table if exists stg.vacancies
  add column if not exists region_norm text;

update stg.vacancies
set region_norm = case
  when nullif(trim(region_raw), '') is null then 'UNKNOWN'
  when trim(region_raw) ~ '^[0-9]{2,}$' then left(trim(region_raw), 2)
  else upper(trim(region_raw))
end
where region_norm is null or trim(region_norm) = '';

alter table if exists stg.vacancies
  alter column region_norm set default 'UNKNOWN',
  alter column region_norm set not null;

alter table if exists stg.vacancies
  add column if not exists profession_norm text;

update stg.vacancies
set profession_norm = coalesce(nullif(trim(profession_raw), ''), 'UNKNOWN')
where profession_norm is null or trim(profession_norm) = '';

alter table if exists stg.vacancies
  alter column profession_norm set default 'UNKNOWN',
  alter column profession_norm set not null;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'chk_stg_vacancies_salary_non_negative'
  ) THEN
    ALTER TABLE stg.vacancies
      ADD CONSTRAINT chk_stg_vacancies_salary_non_negative
      CHECK (
        (salary_from is null or salary_from >= 0)
        and (salary_to is null or salary_to >= 0)
      );
  END IF;
END;
$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'chk_stg_vacancies_salary_from_lte_to'
  ) THEN
    ALTER TABLE stg.vacancies
      ADD CONSTRAINT chk_stg_vacancies_salary_from_lte_to
      CHECK (
        salary_from is null
        or salary_to is null
        or salary_from <= salary_to
      );
  END IF;
END;
$$;

create index if not exists ix_stg_vacancies_status_norm
  on stg.vacancies (status_norm);

create index if not exists ix_stg_vacancies_is_active
  on stg.vacancies (is_active);

create index if not exists ix_stg_vacancies_region_profession
  on stg.vacancies (region_norm, profession_norm);
