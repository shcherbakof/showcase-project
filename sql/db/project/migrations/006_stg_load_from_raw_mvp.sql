-- Docs:
-- - artifacts/docs/data/3. Шаги выполнения checklist.md
-- - artifacts/docs/data/2.0 Стандарт разработки (рабочий, Lite).md
-- - artifacts/docs/datastand/0.2.4 log_work_chaitan_mashine.md

create or replace function stg.load_vacancies_from_raw(p_run_id text default null)
returns table (
  processed_count integer,
  inserted_count integer,
  updated_count integer
)
language sql
as $$
with ranked_raw as (
  select
    r.id,
    r.run_id,
    r.source_system,
    r.ingested_at,
    r.vacancy_id,
    coalesce(r.source_modified_at, r.ingested_at) as source_modified_at_eff,
    coalesce(r.region_code_raw, r.payload -> 'region' ->> 'region_code', r.payload -> 'region' ->> 'name', 'UNKNOWN') as region_raw,
    coalesce(nullif(r.payload ->> 'status', ''), 'UNKNOWN') as status_raw,
    jsonb_strip_nulls(
      jsonb_build_object(
        'salary_min', r.payload ->> 'salary_min',
        'salary_max', r.payload ->> 'salary_max',
        'salary_text', r.payload ->> 'salary',
        'currency', coalesce(r.payload ->> 'currency', r.payload ->> 'currencyCode')
      )
    ) as salary_raw,
    coalesce(
      nullif(r.payload -> 'category' ->> 'specialisation', ''),
      nullif(r.payload ->> 'job-name', ''),
      'UNKNOWN'
    ) as profession_raw,
    nullif(r.payload ->> 'job-name', '') as title,
    coalesce(
      nullif(r.payload -> 'company' ->> 'inn', ''),
      nullif(r.payload -> 'company' ->> 'companycode', ''),
      nullif(r.payload -> 'company' ->> 'id', ''),
      'UNKNOWN_EMPLOYER:' || r.vacancy_id
    ) as employer_key,
    row_number() over (
      partition by r.vacancy_id
      order by
        coalesce(r.source_modified_at, r.ingested_at) desc,
        r.ingested_at desc,
        r.id desc
    ) as rn
  from raw.vacancies r
  where p_run_id is null or r.run_id = p_run_id
), latest_raw as (
  select
    vacancy_id,
    run_id,
    source_system,
    source_modified_at_eff,
    ingested_at,
    region_raw,
    status_raw,
    salary_raw,
    profession_raw,
    employer_key,
    title
  from ranked_raw
  where rn = 1
), normalized as (
  select
    lr.vacancy_id,
    lr.source_system,
    lr.run_id,
    lr.source_modified_at_eff as source_modified_at,
    lr.region_raw,
    lr.status_raw,
    lr.salary_raw,
    lr.profession_raw,
    lr.employer_key,
    lr.title,
    lr.ingested_at as last_raw_ingested_at,
    coalesce(map.status_norm, 'UNKNOWN') as status_norm,
    map.is_active,
    case
      when nullif(trim(lr.region_raw), '') is null then 'UNKNOWN'
      when trim(lr.region_raw) ~ '^[0-9]{2,}$' then left(trim(lr.region_raw), 2)
      else upper(trim(lr.region_raw))
    end as region_norm,
    coalesce(nullif(trim(lr.profession_raw), ''), 'UNKNOWN') as profession_norm,
    case
      when coalesce(s.salary_from_raw, s.salary_to_raw) is null then null::numeric(14,2)
      when s.salary_from_raw is not null and s.salary_to_raw is not null then least(s.salary_from_raw, s.salary_to_raw)
      else s.salary_from_raw
    end as salary_from,
    case
      when coalesce(s.salary_from_raw, s.salary_to_raw) is null then null::numeric(14,2)
      when s.salary_from_raw is not null and s.salary_to_raw is not null then greatest(s.salary_from_raw, s.salary_to_raw)
      else s.salary_to_raw
    end as salary_to,
    case
      when s.salary_from_raw is not null and s.salary_to_raw is not null
        then round(((least(s.salary_from_raw, s.salary_to_raw) + greatest(s.salary_from_raw, s.salary_to_raw)) / 2.0)::numeric, 2)
      when s.salary_from_raw is not null then s.salary_from_raw
      when s.salary_to_raw is not null then s.salary_to_raw
      else null::numeric(14,2)
    end as salary_mid,
    case
      when s.currency_raw in ('RUB', 'RUR', 'РУБ', 'РУБЛЬ', 'РУБЛЕЙ') then 'RUB'
      when s.currency_raw in ('USD', 'ДОЛЛАР', 'ДОЛЛАРОВ') then 'USD'
      when s.currency_raw in ('EUR', 'ЕВРО') then 'EUR'
      when s.currency_raw is null or s.currency_raw = '' then 'UNKNOWN'
      else s.currency_raw
    end as currency
  from latest_raw lr
  left join stg.ref_vacancy_status_map map
    on lower(trim(lr.status_raw)) = map.status_raw_norm
  cross join lateral (
    select
      case
        when from_txt ~ '^-?[0-9]+(\.[0-9]+)?$' and from_txt::numeric(14,2) >= 0 then from_txt::numeric(14,2)
        else null::numeric(14,2)
      end as salary_from_raw,
      case
        when to_txt ~ '^-?[0-9]+(\.[0-9]+)?$' and to_txt::numeric(14,2) >= 0 then to_txt::numeric(14,2)
        else null::numeric(14,2)
      end as salary_to_raw,
      upper(
        regexp_replace(
          coalesce(
            lr.salary_raw ->> 'currency',
            lr.salary_raw ->> 'currency_code',
            lr.salary_raw ->> 'currency_full',
            ''
          ),
          '[^[:alnum:]А-Яа-я]',
          '',
          'g'
        )
      ) as currency_raw
    from (
      select
        substring(
          coalesce(
            lr.salary_raw ->> 'salary_min',
            lr.salary_raw ->> 'from',
            lr.salary_raw ->> 'min',
            ''
          ) from '[-]?[0-9]+(?:[.][0-9]+)?'
        ) as from_txt,
        substring(
          coalesce(
            lr.salary_raw ->> 'salary_max',
            lr.salary_raw ->> 'to',
            lr.salary_raw ->> 'max',
            ''
          ) from '[-]?[0-9]+(?:[.][0-9]+)?'
        ) as to_txt
    ) parsed
  ) s
), upserted as (
  insert into stg.vacancies (
    vacancy_id,
    region,
    source_system,
    run_id,
    source_modified_at,
    region_raw,
    status_raw,
    salary_raw,
    profession_raw,
    employer_key,
    title,
    last_raw_ingested_at,
    stg_updated_at,
    status_norm,
    is_active,
    salary_from,
    salary_to,
    salary_mid,
    currency,
    region_norm,
    profession_norm
  )
  select
    n.vacancy_id,
    n.region_norm,
    n.source_system,
    n.run_id,
    n.source_modified_at,
    n.region_raw,
    n.status_raw,
    n.salary_raw,
    n.profession_raw,
    n.employer_key,
    n.title,
    n.last_raw_ingested_at,
    now(),
    n.status_norm,
    n.is_active,
    n.salary_from,
    n.salary_to,
    n.salary_mid,
    n.currency,
    n.region_norm,
    n.profession_norm
  from normalized n
  on conflict (vacancy_id) do update
  set
    source_system = excluded.source_system,
    region = excluded.region,
    run_id = excluded.run_id,
    source_modified_at = excluded.source_modified_at,
    region_raw = excluded.region_raw,
    status_raw = excluded.status_raw,
    salary_raw = excluded.salary_raw,
    profession_raw = excluded.profession_raw,
    employer_key = excluded.employer_key,
    title = excluded.title,
    last_raw_ingested_at = excluded.last_raw_ingested_at,
    stg_updated_at = now(),
    status_norm = excluded.status_norm,
    is_active = excluded.is_active,
    salary_from = excluded.salary_from,
    salary_to = excluded.salary_to,
    salary_mid = excluded.salary_mid,
    currency = excluded.currency,
    region_norm = excluded.region_norm,
    profession_norm = excluded.profession_norm
  where
    excluded.source_modified_at > stg.vacancies.source_modified_at
    or (
      excluded.source_modified_at = stg.vacancies.source_modified_at
      and excluded.last_raw_ingested_at > stg.vacancies.last_raw_ingested_at
    )
    or (
      excluded.source_modified_at = stg.vacancies.source_modified_at
      and excluded.last_raw_ingested_at = stg.vacancies.last_raw_ingested_at
      and excluded.run_id > stg.vacancies.run_id
    )
  returning (xmax = 0) as inserted_flag
)
select
  (select count(*)::integer from normalized) as processed_count,
  coalesce(sum(case when inserted_flag then 1 else 0 end), 0)::integer as inserted_count,
  coalesce(sum(case when not inserted_flag then 1 else 0 end), 0)::integer as updated_count
from upserted;
$$;

comment on function stg.load_vacancies_from_raw(text)
is 'Builds latest-per-vacancy snapshot from raw.vacancies and upserts deterministic state into stg.vacancies.';
