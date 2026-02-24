import unittest
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Tuple

from src.trudvsem.fetch_layer import FetchDiagnostics
from src.trudvsem.raw_writer import BatchWriteResult
from src.trudvsem.run_metrics import PipelineRunContext, PipelineRunsWriter, RunMetricsAccumulator


class _FakeCursor:
    def __init__(self) -> None:
        self.last_sql: Optional[str] = None
        self.last_params: Optional[Tuple[Any, ...]] = None
        self.rowcount = 1

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        return None

    def execute(self, query: str, params: Optional[Tuple[Any, ...]] = None) -> None:
        self.last_sql = query
        self.last_params = params


class _FakeConnection:
    def __init__(self) -> None:
        self.cursor_obj = _FakeCursor()
        self.commits = 0
        self.rollbacks = 0

    def cursor(self) -> _FakeCursor:
        return self.cursor_obj

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class RunMetricsTests(unittest.TestCase):
    def test_build_record_success(self) -> None:
        acc = RunMetricsAccumulator()
        acc.add_fetch_diagnostics(
            FetchDiagnostics(
                requests_total=2,
                requests_success=2,
                items_extracted=2,
            )
        )
        acc.add_batch_result(
            BatchWriteResult(
                items_total=2,
                raw_candidates=2,
                raw_rows_inserted=2,
                raw_rows_skipped_conflict=0,
                quarantine_candidates=0,
                quarantine_rows_inserted=0,
                max_source_modified_at=datetime(2026, 2, 21, 10, 0, tzinfo=timezone.utc),
                max_ingested_at=datetime(2026, 2, 21, 10, 5, tzinfo=timezone.utc),
            )
        )
        ctx = PipelineRunContext(
            run_id="run-success",
            dag_id="raw_ingest_vacancies",
            started_at=datetime(2026, 2, 21, 10, 0, tzinfo=timezone.utc),
        )
        record = acc.build_record(context=ctx, finished_at=ctx.started_at + timedelta(seconds=30))

        self.assertEqual(record.status, "success")
        self.assertEqual(record.duration_sec, 30)
        self.assertEqual(record.raw_rows_inserted, 2)
        self.assertIsNone(record.error_summary)

    def test_build_record_partial_on_quarantine(self) -> None:
        acc = RunMetricsAccumulator()
        acc.add_fetch_diagnostics(FetchDiagnostics(requests_total=1, requests_success=1, items_extracted=1))
        acc.add_batch_result(
            BatchWriteResult(
                items_total=1,
                raw_candidates=0,
                raw_rows_inserted=0,
                raw_rows_skipped_conflict=0,
                quarantine_candidates=1,
                quarantine_rows_inserted=1,
                max_source_modified_at=None,
                max_ingested_at=datetime(2026, 2, 21, 11, 0, tzinfo=timezone.utc),
            )
        )
        ctx = PipelineRunContext(
            run_id="run-partial",
            dag_id="raw_ingest_vacancies",
            started_at=datetime(2026, 2, 21, 11, 0, tzinfo=timezone.utc),
        )
        record = acc.build_record(context=ctx, finished_at=ctx.started_at + timedelta(seconds=15))

        self.assertEqual(record.status, "partial")
        self.assertIn("quarantine_rows=1", record.error_summary or "")

    def test_build_record_failed_without_progress_and_errors(self) -> None:
        acc = RunMetricsAccumulator()
        acc.add_fetch_diagnostics(
            FetchDiagnostics(
                requests_total=3,
                requests_success=0,
                items_extracted=0,
                http_5xx_count=2,
                timeout_count=1,
            )
        )
        ctx = PipelineRunContext(
            run_id="run-failed",
            dag_id="raw_ingest_vacancies",
            started_at=datetime(2026, 2, 21, 12, 0, tzinfo=timezone.utc),
        )
        record = acc.build_record(context=ctx, finished_at=ctx.started_at + timedelta(seconds=10))

        self.assertEqual(record.status, "failed")
        self.assertIn("http_5xx=2", record.error_summary or "")

    def test_pipeline_runs_writer_upserts_record(self) -> None:
        acc = RunMetricsAccumulator()
        acc.add_fetch_diagnostics(FetchDiagnostics(requests_total=1, requests_success=1, items_extracted=1))
        acc.add_batch_result(
            BatchWriteResult(
                items_total=1,
                raw_candidates=1,
                raw_rows_inserted=1,
                raw_rows_skipped_conflict=0,
                quarantine_candidates=0,
                quarantine_rows_inserted=0,
                max_source_modified_at=datetime(2026, 2, 21, 12, 30, tzinfo=timezone.utc),
                max_ingested_at=datetime(2026, 2, 21, 12, 31, tzinfo=timezone.utc),
            )
        )
        ctx = PipelineRunContext(
            run_id="run-write",
            dag_id="raw_ingest_vacancies",
            started_at=datetime(2026, 2, 21, 12, 30, tzinfo=timezone.utc),
        )
        record = acc.build_record(context=ctx, finished_at=ctx.started_at + timedelta(seconds=5))
        conn = _FakeConnection()
        writer = PipelineRunsWriter(conn)
        writer.write(record)

        self.assertEqual(conn.commits, 1)
        self.assertEqual(conn.rollbacks, 0)
        self.assertIsNotNone(conn.cursor_obj.last_sql)
        self.assertIn("INSERT INTO mon.pipeline_runs", conn.cursor_obj.last_sql or "")
        self.assertEqual((conn.cursor_obj.last_params or ())[0], "run-write")


if __name__ == "__main__":
    unittest.main()
