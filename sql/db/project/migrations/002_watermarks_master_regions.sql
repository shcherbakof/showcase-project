-- Docs:
-- - artifacts/docs/data/3. Шаги выполнения checklist.md
-- - artifacts/docs/data/2.0 Стандарт разработки (рабочий, Lite).md
-- - artifacts/docs/datastand/0.2.4 log_work_chaitan_mashine.md

create table if not exists mon.watermarks (
  source_system text not null,
  entity_name text not null,
  region_code text not null,
  watermark_value timestamptz not null,
  updated_at timestamptz not null default now(),
  updated_by_run_id text null,
  notes text null,
  constraint pk_mon_watermarks primary key (source_system, entity_name, region_code)
);

insert into mon.watermarks (source_system, entity_name, region_code, watermark_value, notes)
values
  ('trudvsem', 'vacancies', '66', '2025-01-01T00:00:00+00:00'::timestamptz, 'bootstrap'),
  ('trudvsem', 'vacancies', '77', '2025-01-01T00:00:00+00:00'::timestamptz, 'bootstrap'),
  ('trudvsem', 'vacancies', '78', '2025-01-01T00:00:00+00:00'::timestamptz, 'bootstrap')
on conflict (source_system, entity_name, region_code) do nothing;
