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
    when lag(coalesce(r.raw_rows, 0)) over (order by d.dt) in (0, null) then null
    else round(
      100.0
      * (coalesce(r.raw_rows, 0) - lag(coalesce(r.raw_rows, 0)) over (order by d.dt))
      / lag(coalesce(r.raw_rows, 0)) over (order by d.dt),
      2
    )::numeric(8,2)
  end as raw_rows_diff_pct,
  case
    when lag(coalesce(s.stg_rows, 0)) over (order by d.dt) in (0, null) then null
    else round(
      100.0
      * (coalesce(s.stg_rows, 0) - lag(coalesce(s.stg_rows, 0)) over (order by d.dt))
      / lag(coalesce(s.stg_rows, 0)) over (order by d.dt),
      2
    )::numeric(8,2)
  end as stg_rows_diff_pct,
  case
    when lag(coalesce(m.mart_rows, 0)) over (order by d.dt) in (0, null) then null
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

comment on view mon.v_pipeline_health_volumes_daily
is 'Daily row volumes for RAW/STG/MART layers in Europe/Moscow with day-over-day deltas.';

create or replace view mon.v_pipeline_health_dq_daily as
with snap as (
  select
    s.dt,
    count(*)::integer as total_rows,
    count(*) filter (where s.region_norm = 'UNKNOWN')::integer as unknown_region_rows,
    count(*) filter (where s.profession_norm = 'UNKNOWN')::integer as unknown_profession_rows,
    count(*) filter (where s.is_active is true)::integer as active_rows,
    count(*) filter (where s.is_active is true and s.salary_mid is null)::integer as active_without_salary_rows
  from mart.vacancy_daily_snapshot s
  group by s.dt
)
select
  s.dt,
  s.total_rows,
  s.unknown_region_rows,
  s.unknown_profession_rows,
  s.active_rows,
  s.active_without_salary_rows,
  round(100.0 * s.unknown_region_rows / nullif(s.total_rows, 0), 2)::numeric(8,2) as unknown_region_pct,
  round(100.0 * s.unknown_profession_rows / nullif(s.total_rows, 0), 2)::numeric(8,2) as unknown_profession_pct,
  round(100.0 * s.active_without_salary_rows / nullif(s.active_rows, 0), 2)::numeric(8,2) as active_without_salary_pct,
  (s.total_rows = 0) as critical_emptiness
from snap s
order by s.dt;

comment on view mon.v_pipeline_health_dq_daily
is 'Daily DQ metrics for UNKNOWN buckets and salary completeness on active vacancies.';

create or replace view mon.v_pipeline_health_dq_current as
with today as (
  select (now() at time zone 'Europe/Moscow')::date as dt
), today_dq as (
  select d.*
  from mon.v_pipeline_health_dq_daily d
  join today t on t.dt = d.dt
), stg_dq as (
  select
    source_modified_at_future_rows,
    source_modified_at_null_rows,
    salary_range_invalid_rows
  from mon.v_stg_vacancies_dq
)
select
  t.dt,
  coalesce(td.total_rows, 0) as total_rows,
  coalesce(td.unknown_region_pct, 0)::numeric(8,2) as unknown_region_pct,
  coalesce(td.unknown_profession_pct, 0)::numeric(8,2) as unknown_profession_pct,
  coalesce(td.active_without_salary_pct, 0)::numeric(8,2) as active_without_salary_pct,
  coalesce(td.critical_emptiness, true) as critical_emptiness,
  coalesce(sd.source_modified_at_future_rows, 0)::bigint as source_modified_at_future_rows,
  coalesce(sd.source_modified_at_null_rows, 0)::bigint as source_modified_at_null_rows,
  coalesce(sd.salary_range_invalid_rows, 0)::bigint as salary_range_invalid_rows
from today t
left join today_dq td on true
left join stg_dq sd on true;

comment on view mon.v_pipeline_health_dq_current
is 'Current-day DQ health including STG timestamp and salary range violations.';

create or replace view mon.v_pipeline_health_last_runs as
select
  p.run_id,
  p.dag_id,
  p.status,
  case
    when p.status = 'success' then 'ok'
    when p.status = 'partial' then 'warning'
    else 'failed'
  end as quality_label,
  p.started_at,
  p.finished_at,
  p.duration_sec,
  p.window_from,
  p.window_to,
  p.items_extracted as snapshot_rows,
  p.raw_rows_inserted as market_rows,
  p.quarantine_rows as employer_rows,
  p.error_summary
from mon.pipeline_runs p
where p.dag_id in ('raw_master_regions', 'stg_marts_pipeline')
order by p.started_at desc;

comment on view mon.v_pipeline_health_last_runs
is 'Recent run log for RAW master and STG/MART pipeline with normalized quality labels.';

create or replace view mon.v_pipeline_health_freshness_current as
with latest_success as (
  select
    p.run_id,
    p.status,
    p.finished_at as last_success_run_time,
    case
      when p.status = 'success' then 'ok'
      when p.status = 'partial' then 'warning'
      else 'failed'
    end as quality_label
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
  ls.run_id as latest_run_id,
  ls.status as latest_run_status,
  ls.quality_label,
  ls.last_success_run_time,
  rm.max_raw_ingested_at,
  sm.max_stg_source_modified_at,
  floor(extract(epoch from (now() - rm.max_raw_ingested_at)) / 60.0)::integer as freshness_delay_min,
  case
    when floor(extract(epoch from (now() - rm.max_raw_ingested_at)) / 60.0) > 720 then 'error'
    when floor(extract(epoch from (now() - rm.max_raw_ingested_at)) / 60.0) > 360 then 'warning'
    else 'ok'
  end as freshness_severity
from latest_success ls
cross join raw_max rm
cross join stg_max sm;

comment on view mon.v_pipeline_health_freshness_current
is 'Current freshness snapshot and delay severity using thresholds warning>6h, error>12h.';

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
), volume_flags as (
  select
    case when coalesce(v.raw_rows_diff_pct, 0) <= -70 or coalesce(v.stg_rows_diff_pct, 0) <= -70 or coalesce(v.mart_rows_diff_pct, 0) <= -70 then 1 else 0 end as vol_error,
    case when (
      coalesce(v.raw_rows_diff_pct, 0) <= -40 or coalesce(v.stg_rows_diff_pct, 0) <= -40 or coalesce(v.mart_rows_diff_pct, 0) <= -40
    ) and not (
      coalesce(v.raw_rows_diff_pct, 0) <= -70 or coalesce(v.stg_rows_diff_pct, 0) <= -70 or coalesce(v.mart_rows_diff_pct, 0) <= -70
    ) then 1 else 0 end as vol_warning
  from volumes v
), dq_flags as (
  select
    greatest(d.unknown_region_pct, d.unknown_profession_pct) as unknown_pct,
    case
      when greatest(d.unknown_region_pct, d.unknown_profession_pct) > 40 then 1
      when d.critical_emptiness or d.source_modified_at_future_rows > 0 then 1
      else 0
    end as dq_error,
    case
      when greatest(d.unknown_region_pct, d.unknown_profession_pct) > 20
       and greatest(d.unknown_region_pct, d.unknown_profession_pct) <= 40 then 1
      else 0
    end as dq_warning
  from dq d
)
select
  t.dt,
  f.latest_run_id,
  f.latest_run_status,
  f.quality_label,
  f.freshness_delay_min,
  coalesce(v.raw_rows, 0) as raw_rows_today,
  coalesce(v.stg_rows, 0) as stg_rows_today,
  coalesce(v.mart_rows, 0) as mart_rows_today,
  (case when f.freshness_severity = 'error' then 1 else 0 end) + vf.vol_error + df.dq_error as dq_error_count,
  (case when f.freshness_severity = 'warning' then 1 else 0 end) + vf.vol_warning + df.dq_warning as dq_warning_count,
  f.freshness_severity,
  coalesce(v.raw_rows_diff_pct, 0)::numeric(8,2) as raw_rows_diff_pct,
  coalesce(v.stg_rows_diff_pct, 0)::numeric(8,2) as stg_rows_diff_pct,
  coalesce(v.mart_rows_diff_pct, 0)::numeric(8,2) as mart_rows_diff_pct,
  df.unknown_pct::numeric(8,2) as dq_unknown_pct,
  d.active_without_salary_pct::numeric(8,2) as dq_without_salary_pct,
  d.source_modified_at_future_rows,
  now() as checked_at
from today t
cross join freshness f
left join volumes v on true
left join dq d on true
left join volume_flags vf on true
left join dq_flags df on true;

comment on view mon.v_pipeline_health_status_cards
is 'One-row status cards source for Superset Pipeline & Data Health dashboard.';
