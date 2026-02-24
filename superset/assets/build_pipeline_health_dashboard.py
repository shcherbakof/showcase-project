#!/usr/bin/env python3
# Docs:
# - artifacts/docs/data/5.1.2 подготовка UI сборка дашборда Data Health (MVP).md
# - artifacts/docs/data/5.1.3 Руководство по дашборду Pipeline & Data Health (MVP).md

import json
import logging
from typing import Any


DASHBOARD_TITLE = "Pipeline & Data Health (MVP)"
DASHBOARD_SLUG = "pipeline-data-health-mvp"
LOGGER = logging.getLogger(__name__)

SLICE_SPECS = [
    {
        "slice_name": "[MVP] Status Cards",
        "schema": "mon",
        "table": "v_pipeline_health_status_cards",
        "columns": [
            "dt",
            "latest_run_status",
            "quality_label",
            "freshness_delay_min",
            "raw_rows_today",
            "stg_rows_today",
            "mart_rows_today",
            "dq_warning_count",
            "dq_error_count",
            "checked_at",
        ],
        "row_limit": 50,
    },
    {
        "slice_name": "[MVP] Freshness Snapshot",
        "schema": "mon",
        "table": "v_pipeline_health_freshness_current",
        "columns": [
            "latest_run_id",
            "latest_run_status",
            "quality_label",
            "last_success_run_time",
            "max_raw_ingested_at",
            "max_stg_source_modified_at",
            "freshness_delay_min",
            "freshness_severity",
        ],
        "row_limit": 50,
    },
    {
        "slice_name": "[MVP] Volumes Daily",
        "schema": "mon",
        "table": "v_pipeline_health_volumes_daily",
        "columns": [
            "dt",
            "raw_rows",
            "stg_rows",
            "mart_rows",
            "raw_rows_diff_pct",
            "stg_rows_diff_pct",
            "mart_rows_diff_pct",
        ],
        "row_limit": 1000,
    },
    {
        "slice_name": "[MVP] DQ Daily",
        "schema": "mon",
        "table": "v_pipeline_health_dq_daily",
        "columns": [
            "dt",
            "total_rows",
            "unknown_region_pct",
            "unknown_profession_pct",
            "active_without_salary_pct",
            "critical_emptiness",
        ],
        "row_limit": 1000,
    },
    {
        "slice_name": "[MVP] DQ Current",
        "schema": "mon",
        "table": "v_pipeline_health_dq_current",
        "columns": [
            "dt",
            "total_rows",
            "unknown_region_pct",
            "unknown_profession_pct",
            "active_without_salary_pct",
            "critical_emptiness",
            "source_modified_at_future_rows",
            "source_modified_at_null_rows",
            "salary_range_invalid_rows",
        ],
        "row_limit": 50,
    },
    {
        "slice_name": "[MVP] Last Runs",
        "schema": "mon",
        "table": "v_pipeline_health_last_runs",
        "columns": [
            "run_id",
            "dag_id",
            "status",
            "quality_label",
            "started_at",
            "finished_at",
            "duration_sec",
            "error_summary",
        ],
        "row_limit": 100,
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
    # Ensure dataset columns are synced from DB view/table metadata.
    dataset.fetch_metadata()
    return dataset


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
    params = build_table_params(dataset, spec["columns"], spec["row_limit"])

    slc = db.session.query(Slice).filter(Slice.slice_name == spec["slice_name"]).one_or_none()
    if slc is None:
        slc = Slice(slice_name=spec["slice_name"])
        db.session.add(slc)

    slc.datasource_id = dataset.id
    slc.datasource_type = "table"
    slc.datasource_name = f"{spec['schema']}.{spec['table']}"
    slc.viz_type = "table"
    slc.params = params
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
    dashboard.json_metadata = json.dumps(
        {"timed_refresh_immune_slices": [], "color_scheme": ""}, ensure_ascii=False
    )
    return dashboard


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
