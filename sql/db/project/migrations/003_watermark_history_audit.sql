-- Docs:
-- - artifacts/docs/data/3. Шаги выполнения checklist.md
-- - artifacts/docs/data/2.0 Стандарт разработки (рабочий, Lite).md
-- - artifacts/docs/datastand/0.2.4 log_work_chaitan_mashine.md

create table if not exists mon.watermark_history (
  id bigserial primary key,
  source_system text not null,
  entity_name text not null,
  region_code text not null,
  old_watermark_value timestamptz null,
  new_watermark_value timestamptz not null,
  changed_at timestamptz not null default now(),
  changed_by_run_id text null,
  change_source text not null default 'watermarks_trigger',
  notes text null
);

create index if not exists ix_mon_watermark_history_key_changed_at
  on mon.watermark_history (source_system, entity_name, region_code, changed_at desc);

create index if not exists ix_mon_watermark_history_changed_by_run
  on mon.watermark_history (changed_by_run_id);

create or replace function mon.fn_log_watermark_change()
returns trigger
language plpgsql
as $$
begin
  if tg_op = 'INSERT' then
    insert into mon.watermark_history (
      source_system,
      entity_name,
      region_code,
      old_watermark_value,
      new_watermark_value,
      changed_at,
      changed_by_run_id,
      change_source,
      notes
    ) values (
      new.source_system,
      new.entity_name,
      new.region_code,
      null,
      new.watermark_value,
      now(),
      new.updated_by_run_id,
      'watermarks_trigger_insert',
      new.notes
    );
    return new;
  end if;

  if tg_op = 'UPDATE' then
    if old.watermark_value is not distinct from new.watermark_value then
      return new;
    end if;

    insert into mon.watermark_history (
      source_system,
      entity_name,
      region_code,
      old_watermark_value,
      new_watermark_value,
      changed_at,
      changed_by_run_id,
      change_source,
      notes
    ) values (
      new.source_system,
      new.entity_name,
      new.region_code,
      old.watermark_value,
      new.watermark_value,
      now(),
      new.updated_by_run_id,
      'watermarks_trigger_update',
      new.notes
    );
    return new;
  end if;

  return new;
end;
$$;

drop trigger if exists trg_log_watermark_change on mon.watermarks;
create trigger trg_log_watermark_change
after insert or update on mon.watermarks
for each row
execute function mon.fn_log_watermark_change();

create or replace function mon.fn_block_watermark_history_mutation()
returns trigger
language plpgsql
as $$
begin
  raise exception 'mon.watermark_history is append-only';
end;
$$;

drop trigger if exists trg_block_watermark_history_update on mon.watermark_history;
create trigger trg_block_watermark_history_update
before update on mon.watermark_history
for each row
execute function mon.fn_block_watermark_history_mutation();

drop trigger if exists trg_block_watermark_history_delete on mon.watermark_history;
create trigger trg_block_watermark_history_delete
before delete on mon.watermark_history
for each row
execute function mon.fn_block_watermark_history_mutation();
