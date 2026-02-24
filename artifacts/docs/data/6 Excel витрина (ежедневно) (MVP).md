# 6 Excel витрина (ежедневно) (MVP)

Документ фиксирует реализацию блока `6` из [`artifacts/docs/data/3. Шаги выполнения checklist.md`](3.%20Шаги%20выполнения%20checklist.md) на базе согласований из [`artifacts/docs/data/6.1 Ручные исследования перед реализацией Excel витрины (MVP).md`](6.1%20Ручные%20исследования%20перед%20реализацией%20Excel%20витрины%20(MVP).md).

## 1) Что реализовано

- Автоматическая генерация Excel-отчёта Business Health после сборки MARTS и DQ-gate.
- Русскоязычная структура файла (включая титульный лист `Легенда`).
- Правило `no_data`: файл создаётся всегда с явной причиной на русском.
- Конфиг контактов вынесен в JSON (`team/email/note`), без `env`.

## 2) Ключевые артефакты

- [`src/jobs/business_health_excel_report.py`](../../../src/jobs/business_health_excel_report.py)
- [`src/jobs/config/business_health_report.json`](../../../src/jobs/config/business_health_report.json)
- [`airflow/dags/stg_marts_pipeline_dag.py`](../../../airflow/dags/stg_marts_pipeline_dag.py)
- [`artifacts/docs/data/6.2 Генерация Excel витрины Business Health (MVP).md`](6.2%20Генерация%20Excel%20витрины%20Business%20Health%20(MVP).md)
- [`artifacts/docs/data/6.3 Руководство по Excel витрине Business Health (MVP).md`](6.3%20Руководство%20по%20Excel%20витрине%20Business%20Health%20(MVP).md)

## 3) Источники (утвержденный вариант B)

- `mon.v_business_health_*` для `Сводка` и `Исключения`.
- `mart.*` для Top-листов и детализации.
