-- Docs:
-- - artifacts/docs/data/3. Шаги выполнения checklist.md
-- - artifacts/docs/data/2.0 Стандарт разработки (рабочий, Lite).md
-- - artifacts/docs/datastand/0.2.4 log_work_chaitan_mashine.md

create or replace view mon.v_business_health_dynamics_daily as
with base as (
  select
    m.dt,
    sum(m.active_vacancies)::integer as active_cnt,
    sum(m.new_vacancies)::integer as new_cnt,
    sum(m.closed_vacancies)::integer as closed_cnt
  from mart.market_daily_kpis m
  group by m.dt
), with_prev as (
  select
    b.dt,
    b.active_cnt,
    b.new_cnt,
    b.closed_cnt,
    (b.new_cnt - b.closed_cnt)::integer as net_change,
    lag(b.active_cnt) over (order by b.dt) as active_cnt_prev
  from base b
)
select
  wp.dt,
  wp.active_cnt,
  wp.new_cnt,
  wp.closed_cnt,
  wp.net_change,
  wp.active_cnt_prev,
  case
    when wp.active_cnt_prev is null or wp.active_cnt_prev = 0 then null
    else round(100.0 * (wp.active_cnt - wp.active_cnt_prev) / wp.active_cnt_prev, 2)::numeric(8,2)
  end as active_change_pct,
  case
    when wp.active_cnt_prev is null or wp.active_cnt_prev = 0 then 'n/a'
    when round(100.0 * (wp.active_cnt - wp.active_cnt_prev) / wp.active_cnt_prev, 2) <= -40 then 'error'
    when round(100.0 * (wp.active_cnt - wp.active_cnt_prev) / wp.active_cnt_prev, 2) <= -25 then 'warning'
    else 'ok'
  end as active_drop_severity
from with_prev wp
order by wp.dt;

comment on view mon.v_business_health_dynamics_daily
is 'Daily business dynamics: active/new/closed/net and DoD anomaly severity for active vacancies.';

create or replace view mon.v_business_health_salary_daily as
with active_snap as (
  select
    s.dt,
    count(*)::integer as active_cnt,
    count(*) filter (where s.salary_mid is not null)::integer as active_with_salary_cnt,
    percentile_cont(0.25) within group (order by s.salary_mid)
      filter (where s.salary_mid is not null)::numeric(14,2) as p25_salary_mid,
    percentile_cont(0.5) within group (order by s.salary_mid)
      filter (where s.salary_mid is not null)::numeric(14,2) as median_salary_mid,
    percentile_cont(0.75) within group (order by s.salary_mid)
      filter (where s.salary_mid is not null)::numeric(14,2) as p75_salary_mid
  from mart.vacancy_daily_snapshot s
  where s.is_active is true
  group by s.dt
)
select
  a.dt,
  a.active_cnt,
  a.active_with_salary_cnt,
  coalesce(round(100.0 * a.active_with_salary_cnt / nullif(a.active_cnt, 0), 2), 0)::numeric(8,2) as salary_coverage_pct,
  a.p25_salary_mid,
  a.median_salary_mid,
  a.p75_salary_mid
from active_snap a
order by a.dt;

comment on view mon.v_business_health_salary_daily
is 'Daily salary trend metrics on active vacancies: coverage and p25/median/p75.';

create or replace view mon.v_business_health_kpi_cards as
with latest_dt as (
  select max(dt) as dt
  from mon.v_business_health_dynamics_daily
), dyn as (
  select d.*
  from mon.v_business_health_dynamics_daily d
  join latest_dt l on d.dt = l.dt
), sal as (
  select s.*
  from mon.v_business_health_salary_daily s
  join latest_dt l on s.dt = l.dt
)
select
  coalesce(l.dt, (now() at time zone 'Europe/Moscow')::date) as dt,
  coalesce(d.active_cnt, 0)::integer as active_vacancies_today,
  coalesce(d.new_cnt, 0)::integer as new_vacancies_today,
  coalesce(d.closed_cnt, 0)::integer as closed_vacancies_today,
  coalesce(d.net_change, 0)::integer as net_change_today,
  coalesce(s.salary_coverage_pct, 0)::numeric(8,2) as salary_coverage_pct_today,
  s.median_salary_mid as median_salary_mid_today,
  s.p25_salary_mid as p25_salary_mid_today,
  s.p75_salary_mid as p75_salary_mid_today,
  d.active_change_pct as active_change_pct_dod,
  coalesce(d.active_drop_severity, 'n/a') as active_drop_severity,
  now() as checked_at
from (select 1 as anchor) a
left join latest_dt l on true
left join dyn d on true
left join sal s on true;

comment on view mon.v_business_health_kpi_cards
is 'One-row current KPI cards source for Business Health dashboard.';

create or replace view mon.v_business_health_top_regions_current as
with latest_dt as (
  select max(dt) as dt
  from mart.market_daily_kpis
), agg as (
  select
    m.dt,
    m.region_norm,
    sum(m.active_vacancies)::integer as active_vacancies
  from mart.market_daily_kpis m
  join latest_dt l on m.dt = l.dt
  group by m.dt, m.region_norm
), ranked as (
  select
    a.dt,
    a.region_norm,
    a.active_vacancies,
    round(100.0 * a.active_vacancies / nullif(sum(a.active_vacancies) over (), 0), 2)::numeric(8,2) as active_share_pct,
    row_number() over (order by a.active_vacancies desc, a.region_norm asc) as rank_no
  from agg a
)
select
  r.dt,
  r.rank_no,
  r.region_norm,
  r.active_vacancies,
  r.active_share_pct
from ranked r
where r.rank_no <= 10
order by r.rank_no;

comment on view mon.v_business_health_top_regions_current
is 'Top-10 regions by active vacancies for the latest business day.';

create or replace view mon.v_business_health_top_professions_current as
with latest_dt as (
  select max(dt) as dt
  from mart.market_daily_kpis
), agg as (
  select
    m.dt,
    m.profession_norm,
    sum(m.active_vacancies)::integer as active_vacancies
  from mart.market_daily_kpis m
  join latest_dt l on m.dt = l.dt
  group by m.dt, m.profession_norm
), ranked as (
  select
    a.dt,
    a.profession_norm,
    a.active_vacancies,
    round(100.0 * a.active_vacancies / nullif(sum(a.active_vacancies) over (), 0), 2)::numeric(8,2) as active_share_pct,
    row_number() over (order by a.active_vacancies desc, a.profession_norm asc) as rank_no
  from agg a
)
select
  r.dt,
  r.rank_no,
  r.profession_norm,
  r.active_vacancies,
  r.active_share_pct
from ranked r
where r.rank_no <= 10
order by r.rank_no;

comment on view mon.v_business_health_top_professions_current
is 'Top-10 professions by active vacancies for the latest business day.';

create or replace view mon.v_business_health_top_employers_current as
with latest_dt as (
  select max(dt) as dt
  from mart.employer_activity
), agg as (
  select
    e.dt,
    e.employer_key,
    e.region_norm,
    bool_or(e.unknown_employer_flag) as unknown_employer_flag,
    sum(e.active_vacancies)::integer as active_vacancies,
    sum(e.new_vacancies)::integer as new_vacancies,
    sum(e.closed_vacancies)::integer as closed_vacancies
  from mart.employer_activity e
  join latest_dt l on e.dt = l.dt
  group by e.dt, e.employer_key, e.region_norm
), ranked as (
  select
    a.dt,
    a.employer_key,
    a.region_norm,
    a.unknown_employer_flag,
    a.active_vacancies,
    a.new_vacancies,
    a.closed_vacancies,
    round(100.0 * a.active_vacancies / nullif(sum(a.active_vacancies) over (), 0), 2)::numeric(8,2) as active_share_pct,
    row_number() over (order by a.active_vacancies desc, a.employer_key asc, a.region_norm asc) as rank_no
  from agg a
)
select
  r.dt,
  r.rank_no,
  r.employer_key,
  r.region_norm,
  r.unknown_employer_flag,
  r.active_vacancies,
  r.new_vacancies,
  r.closed_vacancies,
  r.active_share_pct
from ranked r
where r.rank_no <= 10
order by r.rank_no;

comment on view mon.v_business_health_top_employers_current
is 'Top-10 employers by active vacancies for the latest business day, split by region.';
