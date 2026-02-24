# Docs:
# - artifacts/docs/data/3.1.10.3 Master-DAG + Watermark: реализация и валидация.md
# - artifacts/docs/data/3.1.10.4 Как запускать DAG-и и что проверять после запуска.md
# - artifacts/docs/data/4.2 Оркестрация Airflow end-to-end (MVP).md

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict
from urllib.parse import urlparse

import psycopg2
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.operators.trigger_dagrun import TriggerDagRunOperator
from jobs.raw_master_regions_logic import compute_window_to


DAG_ID = "raw_master_regions"
CHILD_DAG_ID = "raw_ingest_vacancies"
DOWNSTREAM_DAG_ID = "stg_marts_pipeline"
SOURCE_SYSTEM = "trudvsem"
ENTITY_NAME = "vacancies"
REGIONS = ("66", "77", "78")
LOGGER = logging.getLogger(__name__)


def _to_iso(dt: datetime) -> str:
    """Convert datetime to ISO-8601 string in UTC."""

    return dt.astimezone(timezone.utc).isoformat()


def _from_iso(value: str) -> datetime:
    """Parse ISO-8601 datetime string."""

    return datetime.fromisoformat(value)


def _to_db_params(project_db_uri: str) -> Dict[str, Any]:
    """Convert DB URI to psycopg2 connection parameters."""

    parsed = urlparse(project_db_uri)
    return {
        "host": parsed.hostname,
        "port": parsed.port or 5432,
        "user": parsed.username,
        "password": parsed.password,
        "dbname": (parsed.path or "").lstrip("/"),
        "connect_timeout": int(os.getenv("PROJECT_DB_CONNECT_TIMEOUT_SEC", "10")),
    }


def _get_or_create_watermark(
    *, conn: Any, region_code: str, default_value: datetime
) -> datetime:
    """Return current watermark for region; initialize with default if absent."""

    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO mon.watermarks (source_system, entity_name, region_code, watermark_value, notes)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (source_system, entity_name, region_code) DO NOTHING
            """,
            (
                SOURCE_SYSTEM,
                ENTITY_NAME,
                region_code,
                default_value,
                "auto-init by master dag",
            ),
        )
        cursor.execute(
            """
            SELECT watermark_value
            FROM mon.watermarks
            WHERE source_system = %s
              AND entity_name = %s
              AND region_code = %s
            """,
            (SOURCE_SYSTEM, ENTITY_NAME, region_code),
        )
        row = cursor.fetchone()
        if not row:
            raise RuntimeError(f"error_code=WATERMARK_NOT_FOUND region={region_code}")
        return row[0]


def prepare_region_run(*, region_code: str, **context: Any) -> Dict[str, Any]:
    """Build child RAW run configuration for one region."""

    dag_run = context["dag_run"]
    conf = dag_run.conf or {}
    project_db_uri = os.environ["PROJECT_DB_URI"]

    default_window_from_raw = str(
        conf.get(
            "default_window_from",
            os.getenv("RAW_WATERMARK_INITIAL_VALUE", "2025-01-01T00:00:00+00:00"),
        )
    )
    safety_lag_sec = int(
        conf.get("safety_lag_sec", os.getenv("RAW_MASTER_SAFETY_LAG_SEC", "300"))
    )
    pause_between_regions_sec = int(
        conf.get(
            "pause_between_regions_sec",
            os.getenv("RAW_MASTER_PAUSE_BETWEEN_REGIONS_SEC", "60"),
        )
    )

    default_window_from = _from_iso(default_window_from_raw)

    conn = psycopg2.connect(**_to_db_params(project_db_uri))
    try:
        window_from = _get_or_create_watermark(
            conn=conn,
            region_code=region_code,
            default_value=default_window_from,
        )
        conn.commit()
    finally:
        conn.close()

    window_to = compute_window_to(
        window_from=window_from,
        safety_lag_sec=safety_lag_sec,
        now_utc=datetime.now(timezone.utc),
    )

    child_run_id = f"{dag_run.run_id}__region_{region_code}"

    result = {
        "region_code": region_code,
        "window_from": _to_iso(window_from),
        "window_to": _to_iso(window_to),
        "limit": int(conf.get("limit", 100)),
        "max_pages": int(conf.get("max_pages", 500)),
        "max_items": int(conf.get("max_items", 50_000)),
        "child_run_id": child_run_id,
        "pause_between_regions_sec": pause_between_regions_sec,
    }
    LOGGER.info(
        "prepared region run region=%s run_id=%s window_from=%s window_to=%s",
        region_code,
        child_run_id,
        result["window_from"],
        result["window_to"],
    )
    return result


def update_region_watermark(
    *, region_code: str, prepare_task_id: str, **context: Any
) -> None:
    """Advance region watermark to successful child run upper bound."""

    ti = context["ti"]
    cfg = ti.xcom_pull(task_ids=prepare_task_id) or {}
    if not cfg:
        raise RuntimeError(f"error_code=EMPTY_REGION_CONFIG task_id={prepare_task_id}")

    window_to = _from_iso(cfg["window_to"])
    child_run_id = cfg["child_run_id"]

    project_db_uri = os.environ["PROJECT_DB_URI"]
    conn = psycopg2.connect(**_to_db_params(project_db_uri))
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO mon.watermarks (
                  source_system,
                  entity_name,
                  region_code,
                  watermark_value,
                  updated_at,
                  updated_by_run_id,
                  notes
                ) VALUES (%s, %s, %s, %s, now(), %s, %s)
                ON CONFLICT (source_system, entity_name, region_code) DO UPDATE SET
                  watermark_value = GREATEST(mon.watermarks.watermark_value, EXCLUDED.watermark_value),
                  updated_at = now(),
                  updated_by_run_id = EXCLUDED.updated_by_run_id,
                  notes = EXCLUDED.notes
                """,
                (
                    SOURCE_SYSTEM,
                    ENTITY_NAME,
                    region_code,
                    window_to,
                    child_run_id,
                    "updated by raw_master_regions",
                ),
            )
        conn.commit()
        LOGGER.info(
            "watermark updated region=%s run_id=%s watermark_value=%s",
            region_code,
            child_run_id,
            window_to.isoformat(),
        )
    finally:
        conn.close()


def wait_between_regions(*, prepare_task_id: str, **context: Any) -> None:
    """Pause between sequential region runs to reduce source pressure."""

    ti = context["ti"]
    cfg = ti.xcom_pull(task_ids=prepare_task_id) or {}
    seconds = int(cfg.get("pause_between_regions_sec", 0))
    if seconds > 0:
        LOGGER.info("pause between regions seconds=%s task_id=%s", seconds, prepare_task_id)
        time.sleep(seconds)


with DAG(
    dag_id=DAG_ID,
    start_date=datetime(2024, 1, 1),
    schedule="0 7,16 * * *",
    catchup=False,
    max_active_runs=1,
    tags=["raw", "master", "regions"],
) as dag:
    t_prepare_66 = PythonOperator(
        task_id="prepare_region_66",
        python_callable=prepare_region_run,
        op_kwargs={"region_code": "66"},
    )
    t_trigger_66 = TriggerDagRunOperator(
        task_id="trigger_region_66",
        trigger_dag_id=CHILD_DAG_ID,
        trigger_run_id="{{ ti.xcom_pull(task_ids='prepare_region_66')['child_run_id'] }}",
        conf={
            "region_code": "{{ ti.xcom_pull(task_ids='prepare_region_66')['region_code'] }}",
            "window_from": "{{ ti.xcom_pull(task_ids='prepare_region_66')['window_from'] }}",
            "window_to": "{{ ti.xcom_pull(task_ids='prepare_region_66')['window_to'] }}",
            "limit": "{{ ti.xcom_pull(task_ids='prepare_region_66')['limit'] }}",
            "max_pages": "{{ ti.xcom_pull(task_ids='prepare_region_66')['max_pages'] }}",
            "max_items": "{{ ti.xcom_pull(task_ids='prepare_region_66')['max_items'] }}",
        },
        wait_for_completion=True,
        poke_interval=30,
        allowed_states=["success"],
        failed_states=["failed"],
        reset_dag_run=True,
    )
    t_update_66 = PythonOperator(
        task_id="update_watermark_66",
        python_callable=update_region_watermark,
        op_kwargs={"region_code": "66", "prepare_task_id": "prepare_region_66"},
    )
    t_pause_66 = PythonOperator(
        task_id="pause_after_66",
        python_callable=wait_between_regions,
        op_kwargs={"prepare_task_id": "prepare_region_66"},
    )

    t_prepare_77 = PythonOperator(
        task_id="prepare_region_77",
        python_callable=prepare_region_run,
        op_kwargs={"region_code": "77"},
    )
    t_trigger_77 = TriggerDagRunOperator(
        task_id="trigger_region_77",
        trigger_dag_id=CHILD_DAG_ID,
        trigger_run_id="{{ ti.xcom_pull(task_ids='prepare_region_77')['child_run_id'] }}",
        conf={
            "region_code": "{{ ti.xcom_pull(task_ids='prepare_region_77')['region_code'] }}",
            "window_from": "{{ ti.xcom_pull(task_ids='prepare_region_77')['window_from'] }}",
            "window_to": "{{ ti.xcom_pull(task_ids='prepare_region_77')['window_to'] }}",
            "limit": "{{ ti.xcom_pull(task_ids='prepare_region_77')['limit'] }}",
            "max_pages": "{{ ti.xcom_pull(task_ids='prepare_region_77')['max_pages'] }}",
            "max_items": "{{ ti.xcom_pull(task_ids='prepare_region_77')['max_items'] }}",
        },
        wait_for_completion=True,
        poke_interval=30,
        allowed_states=["success"],
        failed_states=["failed"],
        reset_dag_run=True,
    )
    t_update_77 = PythonOperator(
        task_id="update_watermark_77",
        python_callable=update_region_watermark,
        op_kwargs={"region_code": "77", "prepare_task_id": "prepare_region_77"},
    )
    t_pause_77 = PythonOperator(
        task_id="pause_after_77",
        python_callable=wait_between_regions,
        op_kwargs={"prepare_task_id": "prepare_region_77"},
    )

    t_prepare_78 = PythonOperator(
        task_id="prepare_region_78",
        python_callable=prepare_region_run,
        op_kwargs={"region_code": "78"},
    )
    t_trigger_78 = TriggerDagRunOperator(
        task_id="trigger_region_78",
        trigger_dag_id=CHILD_DAG_ID,
        trigger_run_id="{{ ti.xcom_pull(task_ids='prepare_region_78')['child_run_id'] }}",
        conf={
            "region_code": "{{ ti.xcom_pull(task_ids='prepare_region_78')['region_code'] }}",
            "window_from": "{{ ti.xcom_pull(task_ids='prepare_region_78')['window_from'] }}",
            "window_to": "{{ ti.xcom_pull(task_ids='prepare_region_78')['window_to'] }}",
            "limit": "{{ ti.xcom_pull(task_ids='prepare_region_78')['limit'] }}",
            "max_pages": "{{ ti.xcom_pull(task_ids='prepare_region_78')['max_pages'] }}",
            "max_items": "{{ ti.xcom_pull(task_ids='prepare_region_78')['max_items'] }}",
        },
        wait_for_completion=True,
        poke_interval=30,
        allowed_states=["success"],
        failed_states=["failed"],
        reset_dag_run=True,
    )
    t_update_78 = PythonOperator(
        task_id="update_watermark_78",
        python_callable=update_region_watermark,
        op_kwargs={"region_code": "78", "prepare_task_id": "prepare_region_78"},
    )
    t_trigger_stg_marts = TriggerDagRunOperator(
        task_id="trigger_stg_marts_pipeline",
        trigger_dag_id=DOWNSTREAM_DAG_ID,
        trigger_run_id="{{ dag_run.run_id }}__stg_marts",
        conf={
            "source_dag_id": DAG_ID,
            "source_run_id": "{{ dag_run.run_id }}",
            "raw_window_from": "{{ ti.xcom_pull(task_ids='prepare_region_78')['window_from'] }}",
            "raw_window_to": "{{ ti.xcom_pull(task_ids='prepare_region_78')['window_to'] }}",
        },
        wait_for_completion=True,
        poke_interval=30,
        allowed_states=["success"],
        failed_states=["failed"],
        reset_dag_run=True,
    )

    t_prepare_66 >> t_trigger_66 >> t_update_66 >> t_pause_66
    t_pause_66 >> t_prepare_77 >> t_trigger_77 >> t_update_77 >> t_pause_77
    t_pause_77 >> t_prepare_78 >> t_trigger_78 >> t_update_78 >> t_trigger_stg_marts
