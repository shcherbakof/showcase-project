# Docs:
# - artifacts/docs/data/4.2 Оркестрация Airflow end-to-end (MVP).md
# - artifacts/docs/data/3.2.3 STG загрузка vacancies из RAW (MVP).md
# - artifacts/docs/data/3.3.2 Витрины MARTS (MVP).md

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import psycopg2
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.utils.trigger_rule import TriggerRule
from jobs.business_health_excel_report import build_business_health_excel_report
from jobs.stg_marts_pipeline_logic import build_error_summary, compute_pipeline_status, evaluate_quality
from zoneinfo import ZoneInfo


DAG_ID = "stg_marts_pipeline"
MSK_TZ = ZoneInfo("Europe/Moscow")
LOGGER = logging.getLogger(__name__)


def _to_db_params(project_db_uri: str) -> Dict[str, Any]:
    """Convert DB URI into psycopg2 connection parameters."""

    parsed = urlparse(project_db_uri)
    return {
        "host": parsed.hostname,
        "port": parsed.port or 5432,
        "user": parsed.username,
        "password": parsed.password,
        "dbname": (parsed.path or "").lstrip("/"),
        "connect_timeout": int(os.getenv("PROJECT_DB_CONNECT_TIMEOUT_SEC", "10")),
    }


def _parse_iso_datetime(value: str) -> datetime:
    """Parse ISO datetime string."""

    return datetime.fromisoformat(value)


def _date_window_bounds(date_from: str, date_to: str) -> Dict[str, datetime]:
    """Convert date-only bounds in MSK timezone to UTC datetime bounds."""

    from_dt = datetime.fromisoformat(date_from).replace(tzinfo=MSK_TZ)
    to_dt = datetime.fromisoformat(date_to).replace(tzinfo=MSK_TZ)
    window_from = datetime.combine(from_dt.date(), time.min, tzinfo=MSK_TZ).astimezone(timezone.utc)
    window_to = datetime.combine(to_dt.date(), time.max, tzinfo=MSK_TZ).astimezone(timezone.utc)
    return {"window_from": window_from, "window_to": window_to}


def _run_type_from_dag_run(dag_run: Any) -> str:
    """Normalize airflow run type to expected mon.pipeline_runs enum."""

    run_type_raw = getattr(dag_run, "run_type", "scheduled")
    run_type = str(getattr(run_type_raw, "value", run_type_raw)).lower()
    if run_type not in {"scheduled", "manual", "backfill"}:
        return "scheduled"
    return run_type


def prepare_run_context(**context: Any) -> Dict[str, Any]:
    """Build normalized run context and date window for STG/MARTS pipeline."""

    dag_run = context["dag_run"]
    conf = dag_run.conf or {}

    date_from: Optional[str] = conf.get("date_from")
    date_to: Optional[str] = conf.get("date_to")

    if not date_from or not date_to:
        raw_window_to = conf.get("raw_window_to")
        if raw_window_to:
            dt = _parse_iso_datetime(raw_window_to).astimezone(MSK_TZ).date().isoformat()
            date_from = dt
            date_to = dt

    if not date_from or not date_to:
        dis = context.get("data_interval_start")
        now_msk = datetime.now(MSK_TZ).date().isoformat()
        if dis is not None:
            dt = dis.astimezone(MSK_TZ).date().isoformat()
            date_from = dt
            date_to = dt
        else:
            date_from = now_msk
            date_to = now_msk

    result = {
        "run_id": dag_run.run_id,
        "run_type": _run_type_from_dag_run(dag_run),
        "date_from": date_from,
        "date_to": date_to,
        "source_run_id": conf.get("source_run_id"),
        "source_dag_id": conf.get("source_dag_id", "raw_master_regions"),
    }
    LOGGER.info(
        "prepared run context run_id=%s run_type=%s date_from=%s date_to=%s source_run_id=%s",
        result["run_id"],
        result["run_type"],
        result["date_from"],
        result["date_to"],
        result["source_run_id"],
    )
    return result


def refresh_marts(**context: Any) -> Dict[str, Any]:
    """Execute marts refresh SQL function and return affected row counters."""

    ti = context["ti"]
    cfg = ti.xcom_pull(task_ids="prepare_run_context") or {}
    db_uri = os.environ["PROJECT_DB_URI"]

    conn = psycopg2.connect(**_to_db_params(db_uri))
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                select snapshot_rows, market_rows, employer_rows
                from mart.refresh_all_vitrines(%s::date, %s::date)
                """,
                (cfg["date_from"], cfg["date_to"]),
            )
            row = cursor.fetchone() or (0, 0, 0)
        conn.commit()
    finally:
        conn.close()

    result = {
        "snapshot_rows": int(row[0]),
        "market_rows": int(row[1]),
        "employer_rows": int(row[2]),
    }
    LOGGER.info(
        "marts refreshed run_id=%s snapshot_rows=%s market_rows=%s employer_rows=%s",
        cfg.get("run_id"),
        result["snapshot_rows"],
        result["market_rows"],
        result["employer_rows"],
    )
    return result


def run_quality_checks(**context: Any) -> Dict[str, Any]:
    """Run DQ checks for refreshed marts and raise on critical issues."""

    ti = context["ti"]
    cfg = ti.xcom_pull(task_ids="prepare_run_context") or {}
    marts_stats = ti.xcom_pull(task_ids="refresh_marts") or {}
    db_uri = os.environ["PROJECT_DB_URI"]

    conn = psycopg2.connect(**_to_db_params(db_uri))
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                select
                  count(*) filter (where region_norm = 'UNKNOWN' or profession_norm = 'UNKNOWN') as unknown_bucket_rows,
                  coalesce(avg(salary_coverage_pct), 0)::numeric(5,2) as avg_salary_coverage_pct
                from mart.market_daily_kpis
                where dt between %s::date and %s::date
                """,
                (cfg["date_from"], cfg["date_to"]),
            )
            row = cursor.fetchone() or (0, 0)
        conn.commit()
    finally:
        conn.close()

    snapshot_rows = int(marts_stats.get("snapshot_rows", 0))
    market_rows = int(marts_stats.get("market_rows", 0))
    employer_rows = int(marts_stats.get("employer_rows", 0))

    unknown_bucket_rows = int(row[0] or 0)
    avg_salary_coverage_pct = float(row[1] or 0)

    unknown_warn_threshold = int(os.getenv("MART_DQ_UNKNOWN_BUCKET_WARN_ROWS", "1"))
    salary_coverage_warn_threshold = float(os.getenv("MART_DQ_SALARY_COVERAGE_WARN_PCT", "20"))

    result = evaluate_quality(
        snapshot_rows=snapshot_rows,
        market_rows=market_rows,
        employer_rows=employer_rows,
        unknown_bucket_rows=unknown_bucket_rows,
        avg_salary_coverage_pct=avg_salary_coverage_pct,
        unknown_warn_threshold=unknown_warn_threshold,
        salary_coverage_warn_threshold=salary_coverage_warn_threshold,
    )
    LOGGER.info(
        "dq result run_id=%s quality_label=%s critical_count=%s warning_count=%s",
        cfg.get("run_id"),
        result["quality_label"],
        len(result["critical_issues"]),
        len(result["warnings"]),
    )

    if result["critical_issues"]:
        raise RuntimeError(
            "error_code=DQ_CRITICAL "
            + "; ".join(result["critical_issues"])
        )

    return result


def emit_report_quality_marker(**context: Any) -> Dict[str, Any]:
    """Persist JSON marker with aggregated quality and report metadata."""

    ti = context["ti"]
    cfg = ti.xcom_pull(task_ids="prepare_run_context") or {}
    marts_stats = ti.xcom_pull(task_ids="refresh_marts") or {}
    dq = ti.xcom_pull(task_ids="run_quality_checks") or {}
    excel = ti.xcom_pull(task_ids="generate_excel_report") or {}

    quality_label = dq.get("quality_label", "failed")
    critical_issues = dq.get("critical_issues", [])
    warnings = dq.get("warnings", [])
    if excel.get("status") == "no_data":
        warnings.append("warning_code=EXCEL_NO_DATA")

    output_dir = Path(os.getenv("EXCEL_QUALITY_MARKER_DIR", "artifacts/reports/excel_quality"))
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{cfg.get('run_id', 'unknown_run')}.json"

    payload = {
        "dag_id": DAG_ID,
        "run_id": cfg.get("run_id"),
        "source_run_id": cfg.get("source_run_id"),
        "source_dag_id": cfg.get("source_dag_id"),
        "date_from": cfg.get("date_from"),
        "date_to": cfg.get("date_to"),
        "timezone": "Europe/Moscow",
        "quality_label": quality_label,
        "critical_issues": critical_issues,
        "warnings": warnings,
        "snapshot_rows": int(marts_stats.get("snapshot_rows", 0)),
        "market_rows": int(marts_stats.get("market_rows", 0)),
        "employer_rows": int(marts_stats.get("employer_rows", 0)),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "excel_report_path": excel.get("output_path"),
        "excel_report_status": excel.get("status"),
        "excel_report_reason": excel.get("reason"),
    }

    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    result = {
        "quality_label": quality_label,
        "quality_marker_path": str(output_path),
    }
    LOGGER.info(
        "quality marker emitted run_id=%s quality_label=%s marker_path=%s",
        cfg.get("run_id"),
        quality_label,
        result["quality_marker_path"],
    )
    return result


def write_pipeline_run_stats(**context: Any) -> None:
    """Write final mon.pipeline_runs record and propagate critical failure."""

    ti = context["ti"]
    dag_run = context["dag_run"]

    cfg = ti.xcom_pull(task_ids="prepare_run_context") or {}
    marts_stats = ti.xcom_pull(task_ids="refresh_marts") or {}
    dq = ti.xcom_pull(task_ids="run_quality_checks") or {}
    marker = ti.xcom_pull(task_ids="emit_report_quality_marker") or {}
    excel = ti.xcom_pull(task_ids="generate_excel_report") or {}

    failed_tasks = []
    for task_id in (
        "prepare_run_context",
        "refresh_marts",
        "run_quality_checks",
        "generate_excel_report",
        "emit_report_quality_marker",
    ):
        task_instance = dag_run.get_task_instance(task_id)
        if task_instance and task_instance.state in {"failed", "upstream_failed"}:
            failed_tasks.append(task_id)

    quality_label = str(marker.get("quality_label", dq.get("quality_label", "failed")))
    status_data = compute_pipeline_status(failed_tasks=failed_tasks, quality_label=quality_label)
    status = status_data["status"]
    has_critical_error = bool(status_data["has_critical_error"])
    critical_failed_tasks: List[str] = list(status_data["critical_failed_tasks"])
    excel_failed = bool(status_data["excel_failed"])

    error_summary = build_error_summary(
        critical_failed_tasks=critical_failed_tasks,
        excel_failed=excel_failed,
        critical_issues=list(dq.get("critical_issues", [])),
        warnings=list(dq.get("warnings", [])),
        quality_marker_path=marker.get("quality_marker_path"),
        excel_output_path=excel.get("output_path"),
    )

    started_at = dag_run.start_date or datetime.now(timezone.utc)
    finished_at = datetime.now(timezone.utc)
    duration_sec = max(0, int((finished_at - started_at).total_seconds()))

    bounds = _date_window_bounds(cfg["date_from"], cfg["date_to"])

    db_uri = os.environ["PROJECT_DB_URI"]
    conn = psycopg2.connect(**_to_db_params(db_uri))
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                insert into mon.pipeline_runs (
                  run_id,
                  dag_id,
                  run_type,
                  status,
                  started_at,
                  finished_at,
                  duration_sec,
                  window_from,
                  window_to,
                  source_system,
                  items_extracted,
                  raw_rows_inserted,
                  quarantine_rows,
                  max_ingested_at,
                  error_summary
                )
                values (
                  %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                on conflict (run_id) do update set
                  status = excluded.status,
                  finished_at = excluded.finished_at,
                  duration_sec = excluded.duration_sec,
                  window_from = excluded.window_from,
                  window_to = excluded.window_to,
                  items_extracted = excluded.items_extracted,
                  raw_rows_inserted = excluded.raw_rows_inserted,
                  quarantine_rows = excluded.quarantine_rows,
                  max_ingested_at = excluded.max_ingested_at,
                  error_summary = excluded.error_summary
                """,
                (
                    cfg["run_id"],
                    DAG_ID,
                    cfg.get("run_type", "scheduled"),
                    status,
                    started_at,
                    finished_at,
                    duration_sec,
                    bounds["window_from"],
                    bounds["window_to"],
                    "trudvsem",
                    int(marts_stats.get("snapshot_rows", 0)),
                    int(marts_stats.get("market_rows", 0)),
                    int(marts_stats.get("employer_rows", 0)),
                    finished_at,
                    error_summary,
                ),
            )
        conn.commit()
    finally:
        conn.close()
    LOGGER.info(
        "pipeline run stats written run_id=%s status=%s error_summary=%s",
        cfg.get("run_id"),
        status,
        error_summary or "",
    )

    if has_critical_error:
        raise RuntimeError(
            f"error_code=STG_MARTS_PIPELINE_FAILED run_id={cfg['run_id']} "
            "pipeline failed, run stats written"
        )


def generate_excel_report(**context: Any) -> Dict[str, Any]:
    """Generate Excel report artifact from marts data."""

    ti = context["ti"]
    cfg = ti.xcom_pull(task_ids="prepare_run_context") or {}
    project_db_uri = os.environ["PROJECT_DB_URI"]
    output_dir = os.getenv("EXCEL_REPORT_OUTPUT_DIR", "artifacts/reports/excel")
    config_path = os.getenv(
        "EXCEL_REPORT_CONFIG_PATH", "src/jobs/config/business_health_report.json"
    )

    result = build_business_health_excel_report(
        project_db_uri=project_db_uri,
        output_dir=output_dir,
        config_path=config_path,
    )
    result["run_id"] = cfg.get("run_id")
    LOGGER.info(
        "excel generated run_id=%s status=%s output_path=%s",
        result["run_id"],
        result.get("status"),
        result.get("output_path"),
    )
    return result


with DAG(
    dag_id=DAG_ID,
    start_date=datetime(2024, 1, 1),
    schedule="0 7,16 * * *",
    catchup=False,
    max_active_runs=1,
    dagrun_timeout=timedelta(minutes=90),
    default_args={
        "retries": 2,
        "retry_delay": timedelta(minutes=10),
        "execution_timeout": timedelta(minutes=90),
    },
    tags=["stg", "mart", "dq", "excel"],
) as dag:
    t_prepare = PythonOperator(task_id="prepare_run_context", python_callable=prepare_run_context)

    t_refresh = PythonOperator(
        task_id="refresh_marts",
        python_callable=refresh_marts,
        retries=1,
        execution_timeout=timedelta(minutes=45),
    )

    t_dq = PythonOperator(
        task_id="run_quality_checks",
        python_callable=run_quality_checks,
        retries=1,
        execution_timeout=timedelta(minutes=10),
    )

    t_quality_marker = PythonOperator(
        task_id="emit_report_quality_marker",
        python_callable=emit_report_quality_marker,
        retries=1,
        execution_timeout=timedelta(minutes=10),
        trigger_rule=TriggerRule.ALL_DONE,
    )

    t_excel_report = PythonOperator(
        task_id="generate_excel_report",
        python_callable=generate_excel_report,
        retries=1,
        execution_timeout=timedelta(minutes=10),
    )

    t_run_stats = PythonOperator(
        task_id="write_run_stats",
        python_callable=write_pipeline_run_stats,
        trigger_rule=TriggerRule.ALL_DONE,
    )

    t_prepare >> t_refresh >> t_dq >> t_excel_report >> t_quality_marker >> t_run_stats
