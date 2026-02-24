-- Docs:
-- - artifacts/docs/data/3. Шаги выполнения checklist.md
-- - artifacts/docs/data/2.0 Стандарт разработки (рабочий, Lite).md
-- - artifacts/docs/datastand/0.2.4 log_work_chaitan_mashine.md

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'chk_mart_market_daily_kpis_timezone_moscow'
  ) THEN
    ALTER TABLE mart.market_daily_kpis
      ADD CONSTRAINT chk_mart_market_daily_kpis_timezone_moscow
      CHECK (timezone_name = 'Europe/Moscow');
  END IF;
END;
$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'chk_mart_employer_activity_timezone_moscow'
  ) THEN
    ALTER TABLE mart.employer_activity
      ADD CONSTRAINT chk_mart_employer_activity_timezone_moscow
      CHECK (timezone_name = 'Europe/Moscow');
  END IF;
END;
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
  perform pg_advisory_xact_lock(hashtext('mart.refresh_all_vitrines'));
  perform set_config('TimeZone', 'Europe/Moscow', true);

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

comment on function mart.refresh_all_vitrines(date, date)
is 'Atomic MART refresh (snapshot -> market -> employer) under transaction-scoped advisory lock and Europe/Moscow timezone.';
