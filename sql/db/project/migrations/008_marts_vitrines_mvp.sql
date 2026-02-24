-- Docs:
-- - artifacts/docs/data/3. Шаги выполнения checklist.md
-- - artifacts/docs/data/2.0 Стандарт разработки (рабочий, Lite).md
-- - artifacts/docs/datastand/0.2.4 log_work_chaitan_mashine.md

create table if not exists mart.vacancy_daily_snapshot (
  dt date not null,
  vacancy_id text not null,
  employer_key text not null,
  region_norm text not null,
  profession_norm text not null,
  is_active boolean null,
  salary_mid numeric(14,2) null,
  currency text not null default 'UNKNOWN',
  source_modified_at timestamptz not null,
  first_seen_dt date not null,
  updated_at timestamptz not null default now(),
  constraint pk_mart_vacancy_daily_snapshot primary key (dt, vacancy_id)
);

create index if not exists ix_mart_vacancy_daily_snapshot_vacancy
  on mart.vacancy_daily_snapshot (vacancy_id, dt desc);
create index if not exists ix_mart_vacancy_daily_snapshot_region_prof
  on mart.vacancy_daily_snapshot (dt, region_norm, profession_norm);
create index if not exists ix_mart_vacancy_daily_snapshot_employer
  on mart.vacancy_daily_snapshot (dt, employer_key);

create table if not exists mart.market_daily_kpis (
  dt date not null,
  region_norm text not null,
  profession_norm text not null,
  vacancies_total integer not null,
  active_vacancies integer not null,
  new_vacancies integer not null,
  closed_vacancies integer not null,
  salary_coverage_pct numeric(5,2) not null,
  salary_median numeric(14,2) null,
  salary_p75 numeric(14,2) null,
  salary_p90 numeric(14,2) null,
  timezone_name text not null default 'Europe/Moscow',
  updated_at timestamptz not null default now(),
  constraint pk_mart_market_daily_kpis primary key (dt, region_norm, profession_norm)
);

create index if not exists ix_mart_market_daily_kpis_dt
  on mart.market_daily_kpis (dt desc);

create table if not exists mart.employer_activity (
  dt date not null,
  employer_key text not null,
  region_norm text not null,
  unknown_employer_flag boolean not null,
  vacancies_total integer not null,
  active_vacancies integer not null,
  new_vacancies integer not null,
  closed_vacancies integer not null,
  timezone_name text not null default 'Europe/Moscow',
  updated_at timestamptz not null default now(),
  constraint pk_mart_employer_activity primary key (dt, employer_key, region_norm)
);

create index if not exists ix_mart_employer_activity_dt
  on mart.employer_activity (dt desc);
create index if not exists ix_mart_employer_activity_unknown
  on mart.employer_activity (dt desc, unknown_employer_flag);

create index if not exists ix_raw_vacancies_vacancy_event
  on raw.vacancies (vacancy_id, source_modified_at desc, ingested_at desc, id desc);

create or replace function mart.refresh_vacancy_daily_snapshot(
  p_date_from date default null,
  p_date_to date default null
)
returns table (from_dt date, to_dt date, rows_written integer)
language plpgsql
as $$
declare
  v_from date;
  v_to date;
  v_rows integer := 0;
begin
  with bounds as (
    select
      min((coalesce(r.source_modified_at, r.ingested_at) at time zone 'Europe/Moscow')::date) as min_dt,
      max((coalesce(r.source_modified_at, r.ingested_at) at time zone 'Europe/Moscow')::date) as max_dt
    from raw.vacancies r
  )
  select coalesce(p_date_from, min_dt), coalesce(p_date_to, max_dt)
  into v_from, v_to
  from bounds;

  if v_from is null or v_to is null or v_from > v_to then
    return query select p_date_from, p_date_to, 0;
    return;
  end if;

  delete from mart.vacancy_daily_snapshot
  where dt between v_from and v_to;

  with normalized_versions as (
    select
      r.id as raw_id,
      r.vacancy_id,
      coalesce(r.source_modified_at, r.ingested_at) as event_ts,
      (coalesce(r.source_modified_at, r.ingested_at) at time zone 'Europe/Moscow')::date as event_dt,
      coalesce(
        nullif(r.payload -> 'company' ->> 'inn', ''),
        nullif(r.payload -> 'company' ->> 'companycode', ''),
        nullif(r.payload -> 'company' ->> 'id', ''),
        'UNKNOWN_EMPLOYER:' || r.vacancy_id
      ) as employer_key,
      case
        when nullif(trim(coalesce(r.region_code_raw, r.payload -> 'region' ->> 'region_code', r.payload -> 'region' ->> 'name', '')), '') is null then 'UNKNOWN'
        when trim(coalesce(r.region_code_raw, r.payload -> 'region' ->> 'region_code', r.payload -> 'region' ->> 'name', '')) ~ '^[0-9]{2,}$'
          then left(trim(coalesce(r.region_code_raw, r.payload -> 'region' ->> 'region_code', r.payload -> 'region' ->> 'name', '')), 2)
        else upper(trim(coalesce(r.region_code_raw, r.payload -> 'region' ->> 'region_code', r.payload -> 'region' ->> 'name', '')))
      end as region_norm,
      coalesce(
        nullif(trim(coalesce(r.payload -> 'category' ->> 'specialisation', r.payload ->> 'job-name', '')), ''),
        'UNKNOWN'
      ) as profession_norm,
      map.is_active,
      coalesce(r.source_modified_at, r.ingested_at) as source_modified_at,
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
    from raw.vacancies r
    left join stg.ref_vacancy_status_map map
      on lower(trim(coalesce(r.payload ->> 'status', 'UNKNOWN'))) = map.status_raw_norm
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
            coalesce(r.payload ->> 'currency', r.payload ->> 'currencyCode', ''),
            '[^[:alnum:]А-Яа-я]',
            '',
            'g'
          )
        ) as currency_raw
      from (
        select
          substring(coalesce(r.payload ->> 'salary_min', '') from '[-]?[0-9]+(?:[.][0-9]+)?') as from_txt,
          substring(coalesce(r.payload ->> 'salary_max', '') from '[-]?[0-9]+(?:[.][0-9]+)?') as to_txt
      ) parsed
    ) s
  ), days as (
    select gs::date as dt
    from generate_series(v_from::timestamp, v_to::timestamp, interval '1 day') gs
  ), ranked_snapshot as (
    select
      d.dt,
      nv.vacancy_id,
      nv.employer_key,
      nv.region_norm,
      nv.profession_norm,
      nv.is_active,
      nv.salary_mid,
      nv.currency,
      nv.source_modified_at,
      min(nv.event_dt) over (partition by nv.vacancy_id) as first_seen_dt,
      row_number() over (
        partition by d.dt, nv.vacancy_id
        order by nv.event_ts desc, nv.raw_id desc
      ) as rn
    from days d
    join normalized_versions nv
      on nv.event_dt <= d.dt
  ), snapshot_rows as (
    select
      rs.dt,
      rs.vacancy_id,
      rs.employer_key,
      rs.region_norm,
      rs.profession_norm,
      rs.is_active,
      rs.salary_mid,
      rs.currency,
      rs.source_modified_at,
      rs.first_seen_dt
    from ranked_snapshot rs
    where rs.rn = 1
  )
  insert into mart.vacancy_daily_snapshot (
    dt,
    vacancy_id,
    employer_key,
    region_norm,
    profession_norm,
    is_active,
    salary_mid,
    currency,
    source_modified_at,
    first_seen_dt,
    updated_at
  )
  select
    sr.dt,
    sr.vacancy_id,
    sr.employer_key,
    sr.region_norm,
    sr.profession_norm,
    sr.is_active,
    sr.salary_mid,
    sr.currency,
    sr.source_modified_at,
    sr.first_seen_dt,
    now()
  from snapshot_rows sr;

  get diagnostics v_rows = row_count;

  return query select v_from, v_to, coalesce(v_rows, 0);
end;
$$;

create or replace function mart.refresh_market_daily_kpis(
  p_date_from date default null,
  p_date_to date default null
)
returns table (from_dt date, to_dt date, rows_written integer)
language plpgsql
as $$
declare
  v_from date;
  v_to date;
  v_rows integer := 0;
begin
  select min(dt), max(dt)
  into v_from, v_to
  from mart.vacancy_daily_snapshot;

  v_from := coalesce(p_date_from, v_from);
  v_to := coalesce(p_date_to, v_to);

  if v_from is null or v_to is null or v_from > v_to then
    return query select p_date_from, p_date_to, 0;
    return;
  end if;

  delete from mart.market_daily_kpis
  where dt between v_from and v_to;

  with snap as (
    select
      s.*,
      lag(s.is_active) over (partition by s.vacancy_id order by s.dt) as prev_is_active
    from mart.vacancy_daily_snapshot s
    where s.dt between v_from and v_to
  )
  insert into mart.market_daily_kpis (
    dt,
    region_norm,
    profession_norm,
    vacancies_total,
    active_vacancies,
    new_vacancies,
    closed_vacancies,
    salary_coverage_pct,
    salary_median,
    salary_p75,
    salary_p90,
    timezone_name,
    updated_at
  )
  select
    s.dt,
    s.region_norm,
    s.profession_norm,
    count(*)::integer as vacancies_total,
    count(*) filter (where s.is_active is true)::integer as active_vacancies,
    count(*) filter (where s.first_seen_dt = s.dt)::integer as new_vacancies,
    count(*) filter (
      where coalesce(s.prev_is_active, false) is true
        and coalesce(s.is_active, false) is false
    )::integer as closed_vacancies,
    coalesce(
      round(
        100.0 * (count(*) filter (where s.is_active is true and s.salary_mid is not null))
        / nullif((count(*) filter (where s.is_active is true)), 0),
        2
      ),
      0
    )::numeric(5,2) as salary_coverage_pct,
    percentile_cont(0.5) within group (order by s.salary_mid)
      filter (where s.is_active is true and s.salary_mid is not null)::numeric(14,2) as salary_median,
    percentile_cont(0.75) within group (order by s.salary_mid)
      filter (where s.is_active is true and s.salary_mid is not null)::numeric(14,2) as salary_p75,
    percentile_cont(0.9) within group (order by s.salary_mid)
      filter (where s.is_active is true and s.salary_mid is not null)::numeric(14,2) as salary_p90,
    'Europe/Moscow',
    now()
  from snap s
  group by s.dt, s.region_norm, s.profession_norm;

  get diagnostics v_rows = row_count;

  return query select v_from, v_to, coalesce(v_rows, 0);
end;
$$;

create or replace function mart.refresh_employer_activity(
  p_date_from date default null,
  p_date_to date default null
)
returns table (from_dt date, to_dt date, rows_written integer)
language plpgsql
as $$
declare
  v_from date;
  v_to date;
  v_rows integer := 0;
begin
  select min(dt), max(dt)
  into v_from, v_to
  from mart.vacancy_daily_snapshot;

  v_from := coalesce(p_date_from, v_from);
  v_to := coalesce(p_date_to, v_to);

  if v_from is null or v_to is null or v_from > v_to then
    return query select p_date_from, p_date_to, 0;
    return;
  end if;

  delete from mart.employer_activity
  where dt between v_from and v_to;

  with snap as (
    select
      s.*,
      lag(s.is_active) over (partition by s.vacancy_id order by s.dt) as prev_is_active
    from mart.vacancy_daily_snapshot s
    where s.dt between v_from and v_to
  )
  insert into mart.employer_activity (
    dt,
    employer_key,
    region_norm,
    unknown_employer_flag,
    vacancies_total,
    active_vacancies,
    new_vacancies,
    closed_vacancies,
    timezone_name,
    updated_at
  )
  select
    s.dt,
    s.employer_key,
    s.region_norm,
    (s.employer_key like 'UNKNOWN_EMPLOYER:%') as unknown_employer_flag,
    count(*)::integer as vacancies_total,
    count(*) filter (where s.is_active is true)::integer as active_vacancies,
    count(*) filter (where s.first_seen_dt = s.dt)::integer as new_vacancies,
    count(*) filter (
      where coalesce(s.prev_is_active, false) is true
        and coalesce(s.is_active, false) is false
    )::integer as closed_vacancies,
    'Europe/Moscow',
    now()
  from snap s
  group by s.dt, s.employer_key, s.region_norm;

  get diagnostics v_rows = row_count;

  return query select v_from, v_to, coalesce(v_rows, 0);
end;
$$;

create or replace function mart.refresh_all_vitrines(
  p_date_from date default null,
  p_date_to date default null
)
returns table (
  snapshot_rows integer,
  market_rows integer,
  employer_rows integer
)
language plpgsql
as $$
declare
  v_snapshot_rows integer := 0;
  v_market_rows integer := 0;
  v_employer_rows integer := 0;
begin
  select rows_written into v_snapshot_rows
  from mart.refresh_vacancy_daily_snapshot(p_date_from, p_date_to)
  limit 1;

  select rows_written into v_market_rows
  from mart.refresh_market_daily_kpis(p_date_from, p_date_to)
  limit 1;

  select rows_written into v_employer_rows
  from mart.refresh_employer_activity(p_date_from, p_date_to)
  limit 1;

  return query select coalesce(v_snapshot_rows, 0), coalesce(v_market_rows, 0), coalesce(v_employer_rows, 0);
end;
$$;

comment on function mart.refresh_vacancy_daily_snapshot(date, date)
is 'Builds daily vacancy snapshot in Europe/Moscow timezone from raw.vacancies versions.';

comment on function mart.refresh_market_daily_kpis(date, date)
is 'Refreshes mart.market_daily_kpis using active/new/closed definitions agreed in 3.3.1.';

comment on function mart.refresh_employer_activity(date, date)
is 'Refreshes mart.employer_activity including UNKNOWN employers (flagged separately).';

comment on function mart.refresh_all_vitrines(date, date)
is 'Runs full refresh of snapshot + market + employer vitrine tables.';
