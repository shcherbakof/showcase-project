-- Docs:
-- - artifacts/docs/data/3. Шаги выполнения checklist.md
-- - artifacts/docs/data/2.0 Стандарт разработки (рабочий, Lite).md
-- - artifacts/docs/datastand/0.2.4 log_work_chaitan_mashine.md

create or replace view mon.v_pipeline_health_volumes_daily as
with raw_daily as (
  select
    (r.ingested_at at time zone 'Europe/Moscow')::date as dt,
    count(*)::integer as raw_rows
  from raw.vacancies r
  group by 1
), stg_daily as (
  select
    s.dt,
    count(*)::integer as stg_rows
  from mart.vacancy_daily_snapshot s
  group by 1
), mart_daily as (
  select
    m.dt,
    count(*)::integer as mart_rows
  from mart.market_daily_kpis m
  group by 1
), bounds as (
  select
    min(dt) as min_dt,
    max(dt) as max_dt
  from (
    select dt from raw_daily
    union all
    select dt from stg_daily
    union all
    select dt from mart_daily
  ) d
), dates as (
  select gs::date as dt
  from bounds b
  cross join lateral generate_series(b.min_dt::timestamp, b.max_dt::timestamp, interval '1 day') gs
)
select
  d.dt,
  coalesce(r.raw_rows, 0) as raw_rows,
  coalesce(s.stg_rows, 0) as stg_rows,
  coalesce(m.mart_rows, 0) as mart_rows,
  lag(coalesce(r.raw_rows, 0)) over (order by d.dt) as raw_rows_prev,
  lag(coalesce(s.stg_rows, 0)) over (order by d.dt) as stg_rows_prev,
  lag(coalesce(m.mart_rows, 0)) over (order by d.dt) as mart_rows_prev,
  case
    when lag(coalesce(r.raw_rows, 0)) over (order by d.dt) is null
      or lag(coalesce(r.raw_rows, 0)) over (order by d.dt) = 0 then null
    else round(
      100.0
      * (coalesce(r.raw_rows, 0) - lag(coalesce(r.raw_rows, 0)) over (order by d.dt))
      / lag(coalesce(r.raw_rows, 0)) over (order by d.dt),
      2
    )::numeric(8,2)
  end as raw_rows_diff_pct,
  case
    when lag(coalesce(s.stg_rows, 0)) over (order by d.dt) is null
      or lag(coalesce(s.stg_rows, 0)) over (order by d.dt) = 0 then null
    else round(
      100.0
      * (coalesce(s.stg_rows, 0) - lag(coalesce(s.stg_rows, 0)) over (order by d.dt))
      / lag(coalesce(s.stg_rows, 0)) over (order by d.dt),
      2
    )::numeric(8,2)
  end as stg_rows_diff_pct,
  case
    when lag(coalesce(m.mart_rows, 0)) over (order by d.dt) is null
      or lag(coalesce(m.mart_rows, 0)) over (order by d.dt) = 0 then null
    else round(
      100.0
      * (coalesce(m.mart_rows, 0) - lag(coalesce(m.mart_rows, 0)) over (order by d.dt))
      / lag(coalesce(m.mart_rows, 0)) over (order by d.dt),
      2
    )::numeric(8,2)
  end as mart_rows_diff_pct
from dates d
left join raw_daily r on r.dt = d.dt
left join stg_daily s on s.dt = d.dt
left join mart_daily m on m.dt = d.dt
order by d.dt;

create or replace view mon.v_pipeline_health_freshness_current as
with latest_run as (
  select
    p.run_id,
    p.status,
    p.finished_at as last_run_time
  from mon.pipeline_runs p
  where p.dag_id = 'stg_marts_pipeline'
  order by p.started_at desc
  limit 1
), raw_max as (
  select max(ingested_at) as max_raw_ingested_at
  from raw.vacancies
), stg_max as (
  select max(source_modified_at) as max_stg_source_modified_at
  from stg.vacancies
)
select
  coalesce(lr.run_id, 'n/a') as latest_run_id,
  coalesce(lr.status, 'failed') as latest_run_status,
  case
    when coalesce(lr.status, 'failed') = 'success' then 'ok'
    when coalesce(lr.status, 'failed') = 'partial' then 'warning'
    else 'failed'
  end as quality_label,
  lr.last_run_time as last_success_run_time,
  rm.max_raw_ingested_at,
  sm.max_stg_source_modified_at,
  case
    when rm.max_raw_ingested_at is null then null
    else floor(extract(epoch from (now() - rm.max_raw_ingested_at)) / 60.0)::integer
  end as freshness_delay_min,
  case
    when rm.max_raw_ingested_at is null then 'error'
    when floor(extract(epoch from (now() - rm.max_raw_ingested_at)) / 60.0) > 720 then 'error'
    when floor(extract(epoch from (now() - rm.max_raw_ingested_at)) / 60.0) > 360 then 'warning'
    else 'ok'
  end as freshness_severity
from (select 1 as anchor) a
left join latest_run lr on true
cross join raw_max rm
cross join stg_max sm;

create or replace view mon.v_pipeline_health_status_cards as
with today as (
  select (now() at time zone 'Europe/Moscow')::date as dt
), freshness as (
  select * from mon.v_pipeline_health_freshness_current
), volumes as (
  select v.*
  from mon.v_pipeline_health_volumes_daily v
  join today t on t.dt = v.dt
), dq as (
  select * from mon.v_pipeline_health_dq_current
), base as (
  select
    t.dt,
    f.latest_run_id,
    f.latest_run_status,
    f.quality_label,
    f.freshness_delay_min,
    f.freshness_severity,
    v.raw_rows,
    v.stg_rows,
    v.mart_rows,
    v.raw_rows_diff_pct,
    v.stg_rows_diff_pct,
    v.mart_rows_diff_pct,
    d.unknown_region_pct,
    d.unknown_profession_pct,
    d.active_without_salary_pct,
    d.critical_emptiness,
    d.source_modified_at_future_rows
  from today t
  cross join freshness f
  left join volumes v on true
  left join dq d on true
)
select
  b.dt,
  b.latest_run_id,
  b.latest_run_status,
  b.quality_label,
  b.freshness_delay_min,
  coalesce(b.raw_rows, 0) as raw_rows_today,
  coalesce(b.stg_rows, 0) as stg_rows_today,
  coalesce(b.mart_rows, 0) as mart_rows_today,
  (
    case when b.freshness_severity = 'error' then 1 else 0 end
    + case
        when coalesce(b.raw_rows_diff_pct, 0) <= -70
          or coalesce(b.stg_rows_diff_pct, 0) <= -70
          or coalesce(b.mart_rows_diff_pct, 0) <= -70 then 1
        when coalesce(greatest(b.unknown_region_pct, b.unknown_profession_pct), 0) > 40 then 1
        when coalesce(b.critical_emptiness, true) then 1
        when coalesce(b.source_modified_at_future_rows, 0) > 0 then 1
        else 0
      end
  ) as dq_error_count,
  (
    case when b.freshness_severity = 'warning' then 1 else 0 end
    + case
        when (
          coalesce(b.raw_rows_diff_pct, 0) <= -40
          or coalesce(b.stg_rows_diff_pct, 0) <= -40
          or coalesce(b.mart_rows_diff_pct, 0) <= -40
        )
        and not (
          coalesce(b.raw_rows_diff_pct, 0) <= -70
          or coalesce(b.stg_rows_diff_pct, 0) <= -70
          or coalesce(b.mart_rows_diff_pct, 0) <= -70
        ) then 1
        when coalesce(greatest(b.unknown_region_pct, b.unknown_profession_pct), 0) > 20
          and coalesce(greatest(b.unknown_region_pct, b.unknown_profession_pct), 0) <= 40 then 1
        else 0
      end
  ) as dq_warning_count,
  b.freshness_severity,
  coalesce(b.raw_rows_diff_pct, 0)::numeric(8,2) as raw_rows_diff_pct,
  coalesce(b.stg_rows_diff_pct, 0)::numeric(8,2) as stg_rows_diff_pct,
  coalesce(b.mart_rows_diff_pct, 0)::numeric(8,2) as mart_rows_diff_pct,
  coalesce(greatest(b.unknown_region_pct, b.unknown_profession_pct), 0)::numeric(8,2) as dq_unknown_pct,
  coalesce(b.active_without_salary_pct, 0)::numeric(8,2) as dq_without_salary_pct,
  coalesce(b.source_modified_at_future_rows, 0) as source_modified_at_future_rows,
  now() as checked_at
from base b;
