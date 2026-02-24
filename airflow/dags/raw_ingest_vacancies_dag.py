# Docs:
# - artifacts/docs/data/3.1.5.1 DAG raw_ingest_vacancies (MVP).md
# - artifacts/docs/data/4.2 Оркестрация Airflow end-to-end (MVP).md
# - artifacts/docs/data/3.1.10.4 Как запускать DAG-и и что проверять после запуска.md

from __future__ import annotations

import os
import json
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import psycopg2
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.utils.trigger_rule import TriggerRule

try:
    from trudvsem.fetch_layer import FetchConfig, FetchDiagnostics, SafetyLimits, TrudvsemFetcher
    from trudvsem.raw_writer import BatchWriteResult, RawBatchWriter, RawWriteContext
    from trudvsem.run_metrics import (
        PipelineRunContext,
        PipelineRunsWriter,
        RunMetricsAccumulator,
    )
except ImportError:
    from src.trudvsem.fetch_layer import FetchConfig, FetchDiagnostics, SafetyLimits, TrudvsemFetcher
    from src.trudvsem.raw_writer import BatchWriteResult, RawBatchWriter, RawWriteContext
    from src.trudvsem.run_metrics import (
        PipelineRunContext,
        PipelineRunsWriter,
        RunMetricsAccumulator,
    )


DAG_ID = "raw_ingest_vacancies"


def _to_iso(dt: datetime) -> str:
    """Convert datetime to ISO-8601 string in UTC."""
    return dt.astimezone(timezone.utc).isoformat()


def _from_iso(value: str) -> datetime:
    """Parse ISO-8601 datetime string."""
    return datetime.fromisoformat(value)


def _to_db_params(project_db_uri: str) -> Dict[str, Any]:
    """Convert DB URI into psycopg2 connection params with connect timeout."""
    parsed = urlparse(project_db_uri)
    return {
        "host": parsed.hostname,
        "port": parsed.port or 5432,
        "user": parsed.username,
        "password": parsed.password,
        "dbname": (parsed.path or "").lstrip("/"),
        "connect_timeout": int(os.getenv("PROJECT_DB_CONNECT_TIMEOUT_SEC", "10")),
    }


def _safe_run_id(value: str) -> str:
    """Sanitize run_id for safe artifact filename usage."""
    return "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in value)


def _artifact_path(run_id: str, suffix: str) -> str:
    """Build artifact path in /tmp for intermediate JSON payload."""
    return f"/tmp/raw_ingest_{_safe_run_id(run_id)}_{suffix}.json"


def compute_window(**context: Any) -> Dict[str, Any]:
    """Compute ingest window and runtime parameters for current DAG run."""
    dag_run = context["dag_run"]
    conf = dag_run.conf or {}
    run_type_raw = getattr(dag_run, "run_type", "scheduled")
    run_type = str(getattr(run_type_raw, "value", run_type_raw)).lower()
    if run_type not in {"scheduled", "manual", "backfill"}:
        run_type = "scheduled"
    run_id = dag_run.run_id

    manual_from = conf.get("window_from")
    manual_to = conf.get("window_to")
    if manual_from and manual_to:
        window_from = _from_iso(manual_from)
        window_to = _from_iso(manual_to)
    else:
        dis = context.get("data_interval_start")
        die = context.get("data_interval_end")
        now = datetime.now(timezone.utc)
        window_from = dis if dis is not None else now
        window_to = die if die is not None else now

    return {
        "run_id": run_id,
        "run_type": run_type,
        "window_from": _to_iso(window_from),
        "window_to": _to_iso(window_to),
        "region_code": conf.get("region_code"),
        "limit": int(conf.get("limit", 100)),
        "max_pages": int(conf.get("max_pages", 500)),
        "max_items": int(conf.get("max_items", 50_000)),
    }


def fetch_pages(**context: Any) -> Dict[str, Any]:
    """Fetch API pages and persist them as temporary JSON artifact."""
    ti = context["ti"]
    cfg = ti.xcom_pull(task_ids="compute_window") or {}
    fetcher = TrudvsemFetcher(
        FetchConfig(
            limit=int(cfg.get("limit", 100)),
            safety=SafetyLimits(
                max_pages=int(cfg.get("max_pages", 500)),
                max_items=int(cfg.get("max_items", 50_000)),
            ),
        )
    )
    pages: List[Dict[str, Any]] = []
    for page in fetcher.iter_pages(
        modified_from=cfg["window_from"],
        modified_to=cfg["window_to"],
        region_code=cfg.get("region_code"),
    ):
        pages.append(
            {
                "items": page.items,
                "request_params": page.request_params,
                "request_url": page.request_url,
                "http_status": page.http_status,
                "response_meta": page.response_meta,
            }
        )

    pages_path = _artifact_path(cfg["run_id"], "pages")
    with open(pages_path, "w", encoding="utf-8") as out:
        json.dump(pages, out, ensure_ascii=False)

    return {
        "run_id": cfg["run_id"],
        "run_type": cfg["run_type"],
        "window_from": cfg["window_from"],
        "window_to": cfg["window_to"],
        "pages_path": pages_path,
        "fetch_diagnostics": asdict(fetcher.diagnostics),
    }


def extract_items(**context: Any) -> Dict[str, Any]:
    """Transform fetched pages into write-ready batch structure."""
    ti = context["ti"]
    data = ti.xcom_pull(task_ids="fetch_pages") or {}
    pages_path = data.get("pages_path")
    with open(pages_path, "r", encoding="utf-8") as src:
        pages = json.load(src)
    batches: List[Dict[str, Any]] = []
    items_extracted = 0
    for page in pages:
        items = page.get("items", [])
        items_extracted += len(items)
        batches.append(
            {
                "items": items,
                "request_params": page.get("request_params") or {},
                "request_url": page.get("request_url"),
                "http_status": int(page.get("http_status") or 0),
                "response_meta": page.get("response_meta"),
            }
        )

    batches_path = _artifact_path(data["run_id"], "batches")
    with open(batches_path, "w", encoding="utf-8") as out:
        json.dump(batches, out, ensure_ascii=False)

    data["batches_path"] = batches_path
    data["items_extracted_by_extract"] = items_extracted
    return data


def write_raw(**context: Any) -> Dict[str, Any]:
    """Write extracted batches into raw.vacancies/raw.quarantine and persist write results."""
    ti = context["ti"]
    data = ti.xcom_pull(task_ids="extract_items") or {}
    batches_path = data.get("batches_path")
    with open(batches_path, "r", encoding="utf-8") as src:
        batches = json.load(src)
    db_uri = os.environ["PROJECT_DB_URI"]
    conn = psycopg2.connect(**_to_db_params(db_uri))
    writer = RawBatchWriter(conn)

    try:
        write_results: List[Dict[str, Any]] = []
        for batch in batches:
            ctx = RawWriteContext(
                run_id=data["run_id"],
                endpoint="/api/v1/vacancies",
                request_params=batch["request_params"],
                http_status=batch["http_status"],
                request_url=batch.get("request_url"),
                response_meta=batch.get("response_meta"),
            )
            result = writer.write_batch(batch["items"], ctx)
            write_results.append(
                {
                    **asdict(result),
                    "max_source_modified_at": _to_iso(result.max_source_modified_at)
                    if result.max_source_modified_at
                    else None,
                    "max_ingested_at": _to_iso(result.max_ingested_at) if result.max_ingested_at else None,
                }
            )
    finally:
        conn.close()

    write_results_path = _artifact_path(data["run_id"], "write_results")
    with open(write_results_path, "w", encoding="utf-8") as out:
        json.dump(write_results, out, ensure_ascii=False)

    data["write_results_path"] = write_results_path
    return data


def write_run_stats(**context: Any) -> None:
    """Build and write final mon.pipeline_runs record even when upstream tasks fail."""
    ti = context["ti"]
    dag_run = context["dag_run"]
    compute_data = ti.xcom_pull(task_ids="compute_window") or {}
    fetch_data = ti.xcom_pull(task_ids="fetch_pages") or {}
    write_data = ti.xcom_pull(task_ids="write_raw") or {}

    fetch_diag_dict = fetch_data.get("fetch_diagnostics") if fetch_data else None
    fetch_diag = FetchDiagnostics(**fetch_diag_dict) if fetch_diag_dict else FetchDiagnostics()
    write_results: List[Dict[str, Any]] = []
    if write_data and write_data.get("write_results_path"):
        with open(write_data["write_results_path"], "r", encoding="utf-8") as src:
            write_results = json.load(src)

    acc = RunMetricsAccumulator()
    acc.add_fetch_diagnostics(fetch_diag)
    for result_dict in write_results:
        result = BatchWriteResult(
            items_total=int(result_dict["items_total"]),
            raw_candidates=int(result_dict["raw_candidates"]),
            raw_rows_inserted=int(result_dict["raw_rows_inserted"]),
            raw_rows_skipped_conflict=int(result_dict["raw_rows_skipped_conflict"]),
            quarantine_candidates=int(result_dict["quarantine_candidates"]),
            quarantine_rows_inserted=int(result_dict["quarantine_rows_inserted"]),
            max_source_modified_at=_from_iso(result_dict["max_source_modified_at"])
            if result_dict.get("max_source_modified_at")
            else None,
            max_ingested_at=_from_iso(result_dict["max_ingested_at"]) if result_dict.get("max_ingested_at") else None,
        )
        acc.add_batch_result(result)

    has_critical_error = False
    for task in ("compute_window", "fetch_pages", "extract_items", "write_raw"):
        task_instance = dag_run.get_task_instance(task)
        if task_instance and task_instance.state in {"failed", "upstream_failed"}:
            has_critical_error = True
            acc.add_error(f"upstream task failed: {task}")

    run_context = PipelineRunContext(
        run_id=compute_data.get("run_id", dag_run.run_id),
        dag_id=DAG_ID,
        run_type=compute_data.get("run_type", "scheduled"),
        started_at=dag_run.start_date or datetime.now(timezone.utc),
        window_from=_from_iso(compute_data["window_from"]) if compute_data.get("window_from") else None,
        window_to=_from_iso(compute_data["window_to"]) if compute_data.get("window_to") else None,
        source_system="trudvsem",
    )
    record = acc.build_record(
        context=run_context,
        has_critical_error=has_critical_error,
        finished_at=datetime.now(timezone.utc),
    )

    db_uri = os.environ["PROJECT_DB_URI"]
    conn = psycopg2.connect(**_to_db_params(db_uri))
    try:
        PipelineRunsWriter(conn).write(record)
    finally:
        conn.close()

    if has_critical_error:
        raise RuntimeError(
            f"error_code=RAW_INGEST_UPSTREAM_FAILURE run_id={run_context.run_id} "
            "raw ingest finished with upstream failures, run stats written"
        )


with DAG(
    dag_id=DAG_ID,
    start_date=datetime(2024, 1, 1),
    schedule="@daily",
    catchup=False,
    tags=["raw", "mvp"],
) as dag:
    t_compute_window = PythonOperator(task_id="compute_window", python_callable=compute_window)
    t_fetch_pages = PythonOperator(task_id="fetch_pages", python_callable=fetch_pages)
    t_extract_items = PythonOperator(task_id="extract_items", python_callable=extract_items)
    t_write_raw = PythonOperator(task_id="write_raw", python_callable=write_raw)
    t_write_run_stats = PythonOperator(
        task_id="write_run_stats",
        python_callable=write_run_stats,
        trigger_rule=TriggerRule.ALL_DONE,
    )

    t_compute_window >> t_fetch_pages >> t_extract_items >> t_write_raw >> t_write_run_stats
