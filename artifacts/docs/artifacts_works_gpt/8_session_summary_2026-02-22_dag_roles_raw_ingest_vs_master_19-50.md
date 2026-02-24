# Session Summary — 2026-02-22 (DAG roles: raw_ingest_vacancies vs raw_master_regions)

## Контекст запроса

Проведен целевой разбор двух документов и соответствующей DAG-реализации:
- [`artifacts/docs/data/3.1.5.1 DAG raw_ingest_vacancies (MVP).md`](../data/3.1.5.1%20DAG%20raw_ingest_vacancies%20(MVP).md)
- [`artifacts/docs/data/3.1.10.3 Master-DAG + Watermark: реализация и валидация.md`](../data/3.1.10.3%20Master-DAG%20+%20Watermark:%20реализация%20и%20валидация.md)
- [`airflow/dags/raw_ingest_vacancies_dag.py`](../../../airflow/dags/raw_ingest_vacancies_dag.py)
- [`airflow/dags/raw_master_regions_dag.py`](../../../airflow/dags/raw_master_regions_dag.py)

Цель: уточнить сценарии выполнения RAW-контура и зафиксировать операционные выводы.

## Что проанализировано

### 1) Сценарии `raw_ingest_vacancies`
- DAG выполняет атомарный ingest-конвейер:
  - `compute_window -> fetch_pages -> extract_items -> write_raw -> write_run_stats`.
- Поддерживает ручной override окна/региона через `dag_run.conf`.
- Может запускаться по собственному расписанию, а также как child-run из master DAG.
- `write_run_stats` с `ALL_DONE` фиксирует метрики даже при падении upstream.

### 2) Сценарии `raw_master_regions`
- DAG реализует регулярную оркестрацию регионов `66 -> 77 -> 78` последовательно.
- Для каждого региона:
  - читает/инициализирует `window_from` из `mon.watermarks`,
  - рассчитывает `window_to = now - safety_lag`,
  - триггерит `raw_ingest_vacancies` и ждет `success`,
  - обновляет watermark только после успешного child-run.
- Таким образом master является управляющим контуром регулярного инкремента.

### 3) Пересечения запусков и поведение записи в RAW
- `raw_master_regions` напрямую в `raw.vacancies` не пишет; записи делает child DAG `raw_ingest_vacancies`.
- При пересечении запусков на одинаковом окне/регионе:
  - дубли версий в `raw.vacancies` не создаются,
  - действует уникальность `(source_system, vacancy_id, source_modified_at_raw)` + `ON CONFLICT DO NOTHING`,
  - в метриках второго прогона растет `raw_rows_skipped_conflict`,
  - в `mon.pipeline_runs` остаются отдельные записи по run_id.

## Выводы

1. Роли DAG разделены корректно:
- `raw_ingest_vacancies` — исполнитель загрузки,
- `raw_master_regions` — оркестратор регулярки и watermark-политики.

2. Операционный режим:
- для ежедневной загрузки основной вход должен быть через `raw_master_regions`;
- `raw_ingest_vacancies` стоит использовать как сервисный DAG для ad-hoc/отладки/точечных прогонов.

3. Конкурирующие прогоны безопасны для RAW-данных (за счет dedup), но создают лишнюю нагрузку и шум в мониторинге run-метрик.

## Изменения в документации

Обновлен файл:
- [`artifacts/docs/data/3.1.5.1 DAG raw_ingest_vacancies (MVP).md`](../data/3.1.5.1%20DAG%20raw_ingest_vacancies%20(MVP).md)

Добавлен новый начальный блок под заголовком:
- контекст роли child-DAG в связке с master;
- рекомендуемый режим эксплуатации;
- описание поведения при пересечении запусков.
