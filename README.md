# Market Monitoring Pipeline (API «Работа России»)

Проект разработан мной совместно с OpenAI Codex 5.3. Цель репозитория — показать мою практику совместной разработки с AI-агентом

## TL;DR

Пайплайн мониторинга рынка труда:

- Инкрементально забирает вакансии/работодателей из API
- Раскладывает по слоям RAW/STG/MART в локальный postgreSQL, развернутый в докере
- Считает популярные метрики: медианы, перцентили
- Проверяет качество данных
- Визуализирует в Superset: два демонстрационных дашборда "Метрики качества данных" и "Метрики бизнеса"
- Формирует ежедневный Excel-отчет, сгружая в папку `artifacts/reports/excel/`

## Что демонстрирует

- Популярную архитектуру и реализацию data-пайплайна end-to-end (Airflow + Postgres + Superset + Excel)
- Идемпотентность загрузки и watermark-инкремент
- DQ и мониторинг надежности данных
- Воспроизводимость окружения (docker compose, Makefile-таргеты)
- Совместную работу с OpenAI Codex 5.3

## Быстрый старт

Требования: `docker`, `docker compose`, `make`.

```bash
make up-all
make init-db
make smoke
```

## Где смотреть результат

- Excel-отчеты (пример артефактов): [`artifacts/reports/excel/`](/artifacts/reports/excel/)
- Рабочая документация и история сессий: [`artifacts/docs/`](/artifacts/docs/)

## Документация

- Навигатор по документации/артефактам: [`artifacts/docs/README.md`](artifacts/docs/README.md)
- Описание проекта (SoT): [`artifacts/docs/data/1. Описание проекта.md`](artifacts/docs/data/1.%20Описание%20проекта.md)
- Описание работы с OpenAI Codex 5.3: [`artifacts/docs/AI_COLLABORATION.md`](artifacts/docs/AI_COLLABORATION.md)
