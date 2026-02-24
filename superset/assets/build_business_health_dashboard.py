#!/usr/bin/env python3
# Docs:
# - artifacts/docs/data/5.2.2 Подготовка UI сборка дашборда Business Health (MVP).md
# - artifacts/docs/data/5.2.3 Руководство по дашборду Business Health (MVP).md

import json
import logging
from typing import Any


DASHBOARD_TITLE = "Business Health (MVP)"
DASHBOARD_SLUG = "business-health-mvp"
TIME_FILTER_ID = "NATIVE_FILTER-BH-TIME-RANGE"
TIME_FILTER_NAME = "КРАСНАЯ КНОПКА: Период (14/30/90)"
LOGGER = logging.getLogger(__name__)

COLUMN_ALIASES_BY_TABLE: dict[str, dict[str, str]] = {
    "v_business_health_kpi_cards": {
        "dt": "Дата",
        "active_vacancies_today": "Активные вакансии (сегодня)",
        "new_vacancies_today": "Новые вакансии (сегодня)",
        "closed_vacancies_today": "Закрытые вакансии (сегодня)",
        "net_change_today": "Чистое изменение (сегодня)",
        "salary_coverage_pct_today": "Доля вакансий с зарплатой (%)",
        "median_salary_mid_today": "Медианная зарплата",
        "p25_salary_mid_today": "Зарплата p25",
        "p75_salary_mid_today": "Зарплата p75",
        "active_change_pct_dod": "Изменение активных DoD (%)",
        "active_drop_severity": "Сигнал падения активности",
        "checked_at": "Время расчета",
    },
    "v_business_health_dynamics_daily": {
        "dt": "Дата",
        "active_cnt": "Активные вакансии",
        "new_cnt": "Новые вакансии",
        "closed_cnt": "Закрытые вакансии",
        "net_change": "Чистое изменение",
        "active_cnt_prev": "Активные вакансии (вчера)",
        "active_change_pct": "Изменение активных DoD (%)",
        "active_drop_severity": "Сигнал падения активности",
    },
    "v_business_health_salary_daily": {
        "dt": "Дата",
        "active_cnt": "Активные вакансии",
        "active_with_salary_cnt": "Активные с указанной зарплатой",
        "salary_coverage_pct": "Доля вакансий с зарплатой (%)",
        "p25_salary_mid": "Зарплата p25",
        "median_salary_mid": "Медианная зарплата",
        "p75_salary_mid": "Зарплата p75",
    },
    "v_business_health_top_regions_current": {
        "dt": "Дата",
        "rank_no": "Место",
        "region_norm": "Регион",
        "active_vacancies": "Активные вакансии",
        "active_share_pct": "Доля активных (%)",
    },
    "v_business_health_top_professions_current": {
        "dt": "Дата",
        "rank_no": "Место",
        "profession_norm": "Профессия",
        "active_vacancies": "Активные вакансии",
        "active_share_pct": "Доля активных (%)",
    },
    "v_business_health_top_employers_current": {
        "dt": "Дата",
        "rank_no": "Место",
        "employer_key": "Работодатель",
        "region_norm": "Регион",
        "unknown_employer_flag": "Неизвестный работодатель",
        "active_vacancies": "Активные вакансии",
        "new_vacancies": "Новые вакансии",
        "closed_vacancies": "Закрытые вакансии",
        "active_share_pct": "Доля активных (%)",
    },
}

SLICE_SPECS = [
    {
        "slice_name": "[MVP-BH] KPI Карточки",
        "schema": "mon",
        "table": "v_business_health_kpi_cards",
        "columns": [
            "dt",
            "active_vacancies_today",
            "new_vacancies_today",
            "closed_vacancies_today",
            "net_change_today",
            "salary_coverage_pct_today",
            "median_salary_mid_today",
            "p25_salary_mid_today",
            "p75_salary_mid_today",
            "active_change_pct_dod",
            "active_drop_severity",
            "checked_at",
        ],
        "row_limit": 50,
    },
    {
        "slice_name": "[MVP-BH] Динамика рынка",
        "schema": "mon",
        "table": "v_business_health_dynamics_daily",
        "columns": [
            "dt",
            "active_cnt",
            "new_cnt",
            "closed_cnt",
            "net_change",
            "active_cnt_prev",
            "active_change_pct",
            "active_drop_severity",
        ],
        "row_limit": 1000,
    },
    {
        "slice_name": "[MVP-BH] Зарплатные тренды",
        "schema": "mon",
        "table": "v_business_health_salary_daily",
        "columns": [
            "dt",
            "active_cnt",
            "active_with_salary_cnt",
            "salary_coverage_pct",
            "p25_salary_mid",
            "median_salary_mid",
            "p75_salary_mid",
        ],
        "row_limit": 1000,
    },
    {
        "slice_name": "[MVP-BH] Топ регионов",
        "schema": "mon",
        "table": "v_business_health_top_regions_current",
        "columns": [
            "dt",
            "rank_no",
            "region_norm",
            "active_vacancies",
            "active_share_pct",
        ],
        "row_limit": 50,
    },
    {
        "slice_name": "[MVP-BH] Топ профессий",
        "schema": "mon",
        "table": "v_business_health_top_professions_current",
        "columns": [
            "dt",
            "rank_no",
            "profession_norm",
            "active_vacancies",
            "active_share_pct",
        ],
        "row_limit": 50,
    },
    {
        "slice_name": "[MVP-BH] Топ работодателей",
        "schema": "mon",
        "table": "v_business_health_top_employers_current",
        "columns": [
            "dt",
            "rank_no",
            "employer_key",
            "region_norm",
            "unknown_employer_flag",
            "active_vacancies",
            "new_vacancies",
            "closed_vacancies",
            "active_share_pct",
        ],
        "row_limit": 50,
    },
]


def get_dataset(db: Any, SqlaTable: Any, schema: str, table: str) -> Any:
    dataset = (
        db.session.query(SqlaTable)
        .filter(SqlaTable.schema == schema, SqlaTable.table_name == table)
        .one_or_none()
    )
    if dataset is None:
        raise RuntimeError(f"Dataset not found: {schema}.{table}")
    dataset.fetch_metadata()
    apply_column_aliases(dataset, table)
    return dataset


def apply_column_aliases(dataset: Any, table_name: str) -> None:
    alias_map = COLUMN_ALIASES_BY_TABLE.get(table_name, {})
    if not alias_map:
        return
    for col in dataset.columns:
        alias = alias_map.get(col.column_name)
        if alias:
            col.verbose_name = alias


def build_table_params(dataset: Any, columns: list[str], row_limit: int) -> str:
    form_data: dict[str, Any] = {
        "datasource": f"{dataset.id}__table",
        "viz_type": "table",
        "query_mode": "raw",
        "all_columns": columns,
        "row_limit": row_limit,
        "show_cell_bars": False,
        "table_timestamp_format": "smart_date",
    }
    return json.dumps(form_data, ensure_ascii=False)


def upsert_slice(db: Any, SqlaTable: Any, Slice: Any, spec: dict[str, Any]) -> Any:
    dataset = get_dataset(db, SqlaTable, spec["schema"], spec["table"])
    actual_columns = {c.column_name for c in dataset.columns}
    missing_columns = [c for c in spec["columns"] if c not in actual_columns]
    if missing_columns:
        raise RuntimeError(
            f"Missing columns in dataset {spec['schema']}.{spec['table']}: {missing_columns}"
        )

    slc = db.session.query(Slice).filter(Slice.slice_name == spec["slice_name"]).one_or_none()
    if slc is None:
        slc = Slice(slice_name=spec["slice_name"])
        db.session.add(slc)

    slc.datasource_id = dataset.id
    slc.datasource_type = "table"
    slc.datasource_name = f"{spec['schema']}.{spec['table']}"
    slc.viz_type = "table"
    slc.params = build_table_params(dataset, spec["columns"], spec["row_limit"])
    slc.query_context = None
    slc.cache_timeout = None
    return slc


def build_position_json(slices: list[Any]) -> str:
    layout: dict[str, Any] = {"DASHBOARD_VERSION_KEY": "v2"}
    layout["ROOT_ID"] = {
        "id": "ROOT_ID",
        "type": "ROOT",
        "children": ["GRID_ID"],
        "parents": [],
    }

    row_ids: list[str] = []
    chart_node_counter = 1
    for row_idx in range(0, len(slices), 2):
        row_id = f"ROW-{row_idx // 2 + 1}"
        row_ids.append(row_id)

        row_children: list[str] = []
        for col_idx in range(2):
            slice_idx = row_idx + col_idx
            if slice_idx >= len(slices):
                break
            slc = slices[slice_idx]
            chart_node_id = f"CHART-{chart_node_counter}"
            chart_node_counter += 1
            row_children.append(chart_node_id)

            layout[chart_node_id] = {
                "id": chart_node_id,
                "type": "CHART",
                "children": [],
                "parents": [row_id, "GRID_ID", "ROOT_ID"],
                "meta": {
                    "chartId": slc.id,
                    "height": 50,
                    "width": 6,
                    "sliceName": slc.slice_name,
                    "uuid": str(slc.uuid) if slc.uuid else None,
                },
            }

        layout[row_id] = {
            "id": row_id,
            "type": "ROW",
            "children": row_children,
            "parents": ["GRID_ID", "ROOT_ID"],
            "meta": {"background": "BACKGROUND_TRANSPARENT"},
        }

    layout["GRID_ID"] = {
        "id": "GRID_ID",
        "type": "GRID",
        "children": row_ids,
        "parents": ["ROOT_ID"],
    }
    return json.dumps(layout, ensure_ascii=False)


def upsert_dashboard(db: Any, Dashboard: Any, slices: list[Any]) -> Any:
    dashboard = (
        db.session.query(Dashboard)
        .filter(Dashboard.dashboard_title == DASHBOARD_TITLE)
        .one_or_none()
    )
    if dashboard is None:
        dashboard = Dashboard(dashboard_title=DASHBOARD_TITLE)
        db.session.add(dashboard)

    dashboard.slug = DASHBOARD_SLUG
    dashboard.published = True
    dashboard.slices = slices
    dashboard.position_json = build_position_json(slices)
    dashboard.json_metadata = build_json_metadata(slices)
    return dashboard


def build_json_metadata(slices: list[Any]) -> str:
    # Time filter target: all datasets in this dashboard by the shared dt column.
    targets = []
    seen_dataset_ids: set[int] = set()
    for slc in slices:
        if slc.datasource_id in seen_dataset_ids:
            continue
        seen_dataset_ids.add(slc.datasource_id)
        targets.append(
            {
                "datasetId": slc.datasource_id,
                "column": {"name": "dt"},
            }
        )

    metadata: dict[str, Any] = {
        "timed_refresh_immune_slices": [],
        "color_scheme": "",
        "show_native_filters": True,
        "native_filter_configuration": [
            {
                "id": TIME_FILTER_ID,
                "name": TIME_FILTER_NAME,
                "description": "Быстрый выбор периода для бизнес-обзора.",
                "filterType": "filter_time",
                "targets": targets,
                "defaultDataMask": {
                    "extraFormData": {"time_range": "Last 30 days"},
                    "filterState": {"label": "Last 30 days", "value": "Last 30 days"},
                },
                "scope": {"rootPath": ["ROOT_ID"], "excluded": []},
                "controlValues": {"enableEmptyFilter": False},
            }
        ],
    }
    return json.dumps(metadata, ensure_ascii=False)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    from superset.app import create_app

    app = create_app()
    with app.app_context():
        from superset.connectors.sqla.models import SqlaTable
        from superset.extensions import db
        from superset.models.dashboard import Dashboard
        from superset.models.slice import Slice

        slices: list[Any] = []
        for spec in SLICE_SPECS:
            slices.append(upsert_slice(db, SqlaTable, Slice, spec))
        db.session.flush()
        dashboard = upsert_dashboard(db, Dashboard, slices)
        db.session.commit()
        LOGGER.info(
            "dashboard upserted id=%s slug=%s slices=%s",
            dashboard.id,
            dashboard.slug,
            len(slices),
        )


if __name__ == "__main__":
    main()
