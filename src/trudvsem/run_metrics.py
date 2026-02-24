# Docs:
# - artifacts/docs/data/3.1.4.3 Run metrics + mon.pipeline_runs (MVP).md
# - artifacts/docs/data/3.1.6.1 Smoke RAW — первый прогон.md

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, List, Literal, Optional, Protocol, Tuple

from .fetch_layer import FetchDiagnostics
from .raw_writer import BatchWriteResult

RunType = Literal["scheduled", "manual", "backfill"]
RunStatus = Literal["success", "partial", "failed"]


@dataclass(frozen=True)
class PipelineRunContext:
    """Immutable run context used for final write into mon.pipeline_runs."""

    run_id: str
    dag_id: str
    run_type: RunType = "scheduled"
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    window_from: Optional[datetime] = None
    window_to: Optional[datetime] = None
    source_system: str = "trudvsem"


@dataclass
class PipelineRunMetrics:
    """Aggregated metrics collected during one ingest run."""

    requests_total: int = 0
    requests_success: int = 0
    http_429_count: int = 0
    http_5xx_count: int = 0
    parse_error_count: int = 0
    items_extracted: int = 0
    raw_rows_inserted: int = 0
    raw_rows_skipped_conflict: int = 0
    quarantine_rows: int = 0
    max_source_modified_at: Optional[datetime] = None
    max_ingested_at: Optional[datetime] = None
    timeout_count: int = 0
    connection_error_count: int = 0
    terminal_http_error_count: int = 0
    partial_hint: bool = False
    ended_by_http_500_boundary: bool = False
    error_messages: List[str] = field(default_factory=list)

    def add_error(self, message: str) -> None:
        """Append technical error message to summary pool."""
        if message:
            self.error_messages.append(message)


@dataclass(frozen=True)
class PipelineRunRecord:
    """Final snapshot written into mon.pipeline_runs."""

    run_id: str
    dag_id: str
    run_type: RunType
    status: RunStatus
    started_at: datetime
    finished_at: datetime
    duration_sec: int
    window_from: Optional[datetime]
    window_to: Optional[datetime]
    source_system: str
    requests_total: int
    requests_success: int
    http_429_count: int
    http_5xx_count: int
    parse_error_count: int
    items_extracted: int
    raw_rows_inserted: int
    raw_rows_skipped_conflict: int
    quarantine_rows: int
    max_source_modified_at: Optional[datetime]
    max_ingested_at: Optional[datetime]
    error_summary: Optional[str]


class CursorLike(Protocol):
    """Minimal DB cursor protocol required by run stats writer."""

    rowcount: int

    def execute(self, query: str, params: Optional[Tuple[Any, ...]] = None) -> None:
        ...


class ConnectionLike(Protocol):
    """Minimal DB connection protocol required by run stats writer."""

    def cursor(self) -> Any:
        ...

    def commit(self) -> None:
        ...

    def rollback(self) -> None:
        ...


UPSERT_PIPELINE_RUN_SQL = """
INSERT INTO mon.pipeline_runs (
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
  requests_total,
  requests_success,
  http_429_count,
  http_5xx_count,
  parse_error_count,
  items_extracted,
  raw_rows_inserted,
  raw_rows_skipped_conflict,
  quarantine_rows,
  max_source_modified_at,
  max_ingested_at,
  error_summary
) VALUES (
  %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
  %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
)
ON CONFLICT (run_id) DO UPDATE SET
  dag_id = EXCLUDED.dag_id,
  run_type = EXCLUDED.run_type,
  status = EXCLUDED.status,
  started_at = EXCLUDED.started_at,
  finished_at = EXCLUDED.finished_at,
  duration_sec = EXCLUDED.duration_sec,
  window_from = EXCLUDED.window_from,
  window_to = EXCLUDED.window_to,
  source_system = EXCLUDED.source_system,
  requests_total = EXCLUDED.requests_total,
  requests_success = EXCLUDED.requests_success,
  http_429_count = EXCLUDED.http_429_count,
  http_5xx_count = EXCLUDED.http_5xx_count,
  parse_error_count = EXCLUDED.parse_error_count,
  items_extracted = EXCLUDED.items_extracted,
  raw_rows_inserted = EXCLUDED.raw_rows_inserted,
  raw_rows_skipped_conflict = EXCLUDED.raw_rows_skipped_conflict,
  quarantine_rows = EXCLUDED.quarantine_rows,
  max_source_modified_at = EXCLUDED.max_source_modified_at,
  max_ingested_at = EXCLUDED.max_ingested_at,
  error_summary = EXCLUDED.error_summary
"""


class RunMetricsAccumulator:
    """Collects fetch/write counters and builds final pipeline run record."""

    def __init__(self) -> None:
        self.metrics = PipelineRunMetrics()

    def add_fetch_diagnostics(self, diagnostics: FetchDiagnostics) -> None:
        """Merge counters collected by fetch layer."""
        self.metrics.requests_total += diagnostics.requests_total
        self.metrics.requests_success += diagnostics.requests_success
        self.metrics.http_429_count += diagnostics.http_429_count
        self.metrics.http_5xx_count += diagnostics.http_5xx_count
        self.metrics.parse_error_count += diagnostics.parse_error_count
        self.metrics.items_extracted += diagnostics.items_extracted
        self.metrics.timeout_count += diagnostics.timeout_count
        self.metrics.connection_error_count += diagnostics.connection_error_count
        self.metrics.terminal_http_error_count += diagnostics.terminal_http_error_count
        if diagnostics.stopped_reason == "http_500_boundary_after_data":
            self.metrics.ended_by_http_500_boundary = True
        if diagnostics.stopped_reason in {"max_pages_reached", "max_items_reached"}:
            self.metrics.partial_hint = True
            self.metrics.add_error(f"safety stop reached: {diagnostics.stopped_reason}")

    def add_batch_result(self, result: BatchWriteResult) -> None:
        """Merge counters produced by raw writer."""
        self.metrics.raw_rows_inserted += result.raw_rows_inserted
        self.metrics.raw_rows_skipped_conflict += result.raw_rows_skipped_conflict
        self.metrics.quarantine_rows += result.quarantine_rows_inserted
        self.metrics.max_source_modified_at = _max_dt(
            self.metrics.max_source_modified_at, result.max_source_modified_at
        )
        self.metrics.max_ingested_at = _max_dt(self.metrics.max_ingested_at, result.max_ingested_at)

    def add_error(self, message: str) -> None:
        """Attach additional technical error to summary."""
        self.metrics.add_error(message)

    def build_record(
        self,
        *,
        context: PipelineRunContext,
        has_critical_error: bool = False,
        finished_at: Optional[datetime] = None,
    ) -> PipelineRunRecord:
        """Compute final status and pack all metrics into DB-ready record."""
        finished = finished_at or datetime.now(timezone.utc)
        duration = max(0, int((finished - context.started_at).total_seconds()))
        status = _compute_status(metrics=self.metrics, has_critical_error=has_critical_error)
        error_summary = _build_error_summary(metrics=self.metrics, has_critical_error=has_critical_error)
        return PipelineRunRecord(
            run_id=context.run_id,
            dag_id=context.dag_id,
            run_type=context.run_type,
            status=status,
            started_at=context.started_at,
            finished_at=finished,
            duration_sec=duration,
            window_from=context.window_from,
            window_to=context.window_to,
            source_system=context.source_system,
            requests_total=self.metrics.requests_total,
            requests_success=self.metrics.requests_success,
            http_429_count=self.metrics.http_429_count,
            http_5xx_count=self.metrics.http_5xx_count,
            parse_error_count=self.metrics.parse_error_count,
            items_extracted=self.metrics.items_extracted,
            raw_rows_inserted=self.metrics.raw_rows_inserted,
            raw_rows_skipped_conflict=self.metrics.raw_rows_skipped_conflict,
            quarantine_rows=self.metrics.quarantine_rows,
            max_source_modified_at=self.metrics.max_source_modified_at,
            max_ingested_at=self.metrics.max_ingested_at,
            error_summary=error_summary,
        )


class PipelineRunsWriter:
    """Writes final run record into mon.pipeline_runs."""

    def __init__(self, connection: ConnectionLike) -> None:
        self.connection = connection

    def write(self, record: PipelineRunRecord) -> None:
        """Upsert run record into mon.pipeline_runs."""
        params = (
            record.run_id,
            record.dag_id,
            record.run_type,
            record.status,
            record.started_at,
            record.finished_at,
            record.duration_sec,
            record.window_from,
            record.window_to,
            record.source_system,
            record.requests_total,
            record.requests_success,
            record.http_429_count,
            record.http_5xx_count,
            record.parse_error_count,
            record.items_extracted,
            record.raw_rows_inserted,
            record.raw_rows_skipped_conflict,
            record.quarantine_rows,
            record.max_source_modified_at,
            record.max_ingested_at,
            record.error_summary,
        )
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(UPSERT_PIPELINE_RUN_SQL, params)
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise


def _compute_status(*, metrics: PipelineRunMetrics, has_critical_error: bool) -> RunStatus:
    if has_critical_error:
        return "failed"

    effective_http_5xx_count = 0 if metrics.ended_by_http_500_boundary else metrics.http_5xx_count
    had_transient_or_http_errors = (
        metrics.http_429_count > 0
        or effective_http_5xx_count > 0
        or metrics.timeout_count > 0
        or metrics.connection_error_count > 0
        or metrics.terminal_http_error_count > 0
        or metrics.parse_error_count > 0
    )
    has_progress = metrics.items_extracted > 0 or metrics.raw_rows_inserted > 0

    if not has_progress and had_transient_or_http_errors:
        return "failed"

    if metrics.quarantine_rows > 0 or had_transient_or_http_errors or metrics.partial_hint:
        return "partial"

    return "success"


def _build_error_summary(*, metrics: PipelineRunMetrics, has_critical_error: bool) -> Optional[str]:
    parts: List[str] = []
    if has_critical_error:
        parts.append("critical_error")
    if metrics.http_429_count:
        parts.append(f"http_429={metrics.http_429_count}")
    if metrics.http_5xx_count:
        parts.append(f"http_5xx={metrics.http_5xx_count}")
    if metrics.ended_by_http_500_boundary:
        parts.append("stop_reason=http_500_boundary_after_data")
    if metrics.timeout_count:
        parts.append(f"timeouts={metrics.timeout_count}")
    if metrics.connection_error_count:
        parts.append(f"connection_errors={metrics.connection_error_count}")
    if metrics.parse_error_count:
        parts.append(f"parse_errors={metrics.parse_error_count}")
    if metrics.quarantine_rows:
        parts.append(f"quarantine_rows={metrics.quarantine_rows}")
    if metrics.error_messages:
        parts.extend(metrics.error_messages[:3])
    if not parts:
        return None
    summary = "; ".join(parts)
    return summary[:1000]


def _max_dt(left: Optional[datetime], right: Optional[datetime]) -> Optional[datetime]:
    if left is None:
        return right
    if right is None:
        return left
    return left if left >= right else right
