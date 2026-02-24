# Docs:
# - artifacts/docs/data/3.1.5.3 Ручной backfill CLI (MVP).md
# - artifacts/docs/data/3.1 raw_data_actions_checklist.md
# - artifacts/docs/artifacts_works_gpt/2_session_summary_2026-02-21_20-24.md

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import psycopg2

try:
    from trudvsem.fetch_layer import FetchConfig, SafetyLimits, TrudvsemFetcher
    from trudvsem.raw_writer import RawBatchWriter, RawWriteContext
    from trudvsem.run_metrics import PipelineRunContext, PipelineRunsWriter, RunMetricsAccumulator
except ImportError:
    from src.trudvsem.fetch_layer import FetchConfig, SafetyLimits, TrudvsemFetcher
    from src.trudvsem.raw_writer import RawBatchWriter, RawWriteContext
    from src.trudvsem.run_metrics import PipelineRunContext, PipelineRunsWriter, RunMetricsAccumulator


LOGGER = logging.getLogger("raw_backfill")
_STOP_REQUESTED = False


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse CLI arguments for manual backfill run."""

    parser = argparse.ArgumentParser(
        description="Ручной backfill RAW-инжеста с записью в raw.* и mon.pipeline_runs"
    )
    parser.add_argument("--window-from", required=True, help="ISO datetime, например 2026-02-21T00:00:00+00:00")
    parser.add_argument("--window-to", required=True, help="ISO datetime, например 2026-02-21T23:59:59+00:00")
    parser.add_argument("--region-code", default=None, help="Опциональный код региона")
    parser.add_argument("--limit", type=int, default=100, help="Размер страницы API")
    parser.add_argument("--max-pages", type=int, default=500, help="Safety stop по числу страниц")
    parser.add_argument("--max-items", type=int, default=50000, help="Safety stop по числу элементов")
    parser.add_argument("--run-id", default=None, help="Опциональный явный run_id")
    parser.add_argument("--dag-id", default="raw_ingest_vacancies", help="Идентификатор DAG для mon.pipeline_runs")
    parser.add_argument("--db-uri", default=None, help="Переопределение DB URI; иначе используется PROJECT_DB_URI")
    parser.add_argument("--dry-run", action="store_true", help="Только fetch/агрегация, без записи в БД")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return parser.parse_args(argv)


def _to_db_params(project_db_uri: str) -> Dict[str, Any]:
    """Convert SQLAlchemy-like URI into psycopg2 connection parameters."""

    parsed = urlparse(project_db_uri)
    return {
        "host": parsed.hostname,
        "port": parsed.port or 5432,
        "user": parsed.username,
        "password": parsed.password,
        "dbname": (parsed.path or "").lstrip("/"),
        "connect_timeout": int(os.getenv("PROJECT_DB_CONNECT_TIMEOUT_SEC", "10")),
    }


def _parse_iso(value: str) -> datetime:
    """Parse ISO datetime string into datetime object."""

    return datetime.fromisoformat(value)


def _signal_handler(signum: int, _frame: Any) -> None:
    """Handle SIGINT/SIGTERM and request graceful shutdown."""
    global _STOP_REQUESTED
    _STOP_REQUESTED = True
    LOGGER.warning("Получен сигнал завершения: signum=%s. Запрос на graceful shutdown.", signum)


def run_backfill(args: argparse.Namespace) -> int:
    """Execute manual backfill and return process exit code."""
    global _STOP_REQUESTED
    _STOP_REQUESTED = False

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    started_at = datetime.now(timezone.utc)
    run_id = args.run_id or f"backfill-{uuid.uuid4()}"
    window_from = _parse_iso(args.window_from)
    window_to = _parse_iso(args.window_to)

    fetcher = TrudvsemFetcher(
        FetchConfig(
            limit=args.limit,
            safety=SafetyLimits(max_pages=args.max_pages, max_items=args.max_items),
        )
    )
    metrics = RunMetricsAccumulator()
    has_critical_error = False

    project_db_uri = args.db_uri or os.getenv("PROJECT_DB_URI")
    if not args.dry_run and not project_db_uri:
        raise RuntimeError("error_code=CONFIG_MISSING_PROJECT_DB_URI PROJECT_DB_URI is required")

    conn = None
    raw_writer = None
    pipeline_writer = None
    if not args.dry_run:
        conn = psycopg2.connect(**_to_db_params(project_db_uri))
        raw_writer = RawBatchWriter(conn)
        pipeline_writer = PipelineRunsWriter(conn)

    try:
        for page in fetcher.iter_pages(
            modified_from=window_from.isoformat(),
            modified_to=window_to.isoformat(),
            region_code=args.region_code,
        ):
            if _STOP_REQUESTED:
                metrics.metrics.partial_hint = True
                metrics.add_error("error_code=GRACEFUL_SHUTDOWN requested by signal")
                LOGGER.warning("Остановлено по сигналу. Завершаем backfill корректно. run_id=%s", run_id)
                break

            if args.dry_run:
                continue

            write_context = RawWriteContext(
                run_id=run_id,
                endpoint="/api/v1/vacancies",
                request_params=page.request_params,
                http_status=page.http_status,
                request_url=page.request_url,
                response_meta=page.response_meta,
            )
            batch_result = raw_writer.write_batch(page.items, write_context)
            metrics.add_batch_result(batch_result)

        metrics.add_fetch_diagnostics(fetcher.diagnostics)
    except Exception as exc:
        has_critical_error = True
        metrics.add_fetch_diagnostics(fetcher.diagnostics)
        metrics.add_error(f"error_code=BACKFILL_RUNTIME_ERROR {exc}")
        LOGGER.exception("backfill failed run_id=%s error_code=BACKFILL_RUNTIME_ERROR", run_id)
    finally:
        run_context = PipelineRunContext(
            run_id=run_id,
            dag_id=args.dag_id,
            run_type="backfill",
            started_at=started_at,
            window_from=window_from,
            window_to=window_to,
            source_system="trudvsem",
        )
        record = metrics.build_record(
            context=run_context,
            has_critical_error=has_critical_error,
            finished_at=datetime.now(timezone.utc),
        )

        if pipeline_writer is not None:
            pipeline_writer.write(record)
        if conn is not None:
            conn.close()

        LOGGER.info("Итог backfill: run_id=%s status=%s dry_run=%s", record.run_id, record.status, args.dry_run)
        LOGGER.info(
            "Счетчики запросов: requests_total=%s requests_success=%s",
            record.requests_total,
            record.requests_success,
        )
        LOGGER.info(
            "Счетчики данных: items_extracted=%s raw_rows_inserted=%s raw_rows_skipped_conflict=%s quarantine_rows=%s",
            record.items_extracted,
            record.raw_rows_inserted,
            record.raw_rows_skipped_conflict,
            record.quarantine_rows,
        )
        LOGGER.info("error_summary=%s", record.error_summary or "")

    return 1 if has_critical_error else 0


def main(argv: Optional[list[str]] = None) -> int:
    """Entry-point for command line execution."""
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)
    args = _parse_args(argv)
    return run_backfill(args)


if __name__ == "__main__":
    sys.exit(main())
