# Docs:
# - artifacts/docs/data/3.1.4.2 RAW batch write + quarantine (MVP).md
# - artifacts/docs/data/3.1.5.2 Проверка идемпотентности RAW.md

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Protocol, Sequence, Tuple

from psycopg2.extras import Json, execute_values


@dataclass(frozen=True)
class RawWriteContext:
    """Common metadata applied to all rows written within one API response batch."""

    run_id: str
    endpoint: str
    request_params: Dict[str, Any]
    http_status: int
    source_system: str = "trudvsem"
    request_url: Optional[str] = None
    response_meta: Optional[Dict[str, Any]] = None
    ingested_at: Optional[datetime] = None


@dataclass(frozen=True)
class BatchWriteResult:
    """Write summary for one batch."""

    items_total: int
    raw_candidates: int
    raw_rows_inserted: int
    raw_rows_skipped_conflict: int
    quarantine_candidates: int
    quarantine_rows_inserted: int
    max_source_modified_at: Optional[datetime]
    max_ingested_at: Optional[datetime]


class CursorLike(Protocol):
    """Minimal DB cursor protocol required by batch writer."""

    rowcount: int

    def execute(self, query: str, params: Optional[Tuple[Any, ...]] = None) -> None:
        ...


class ConnectionLike(Protocol):
    """Minimal DB connection protocol required by batch writer."""

    def cursor(self) -> Any:
        ...

    def commit(self) -> None:
        ...

    def rollback(self) -> None:
        ...


RAW_INSERT_SQL = """
INSERT INTO raw.vacancies (
  run_id,
  ingested_at,
  source_system,
  endpoint,
  request_params,
  http_status,
  payload,
  vacancy_id,
  source_modified_at_raw,
  source_modified_at,
  region_code_raw,
  response_meta,
  request_url,
  payload_sha256
) VALUES %s
ON CONFLICT (source_system, vacancy_id, source_modified_at_raw) DO NOTHING
"""


QUARANTINE_INSERT_SQL = """
INSERT INTO raw.quarantine (
  run_id,
  ingested_at,
  source_system,
  endpoint,
  request_params,
  http_status,
  payload,
  error_type,
  error_reason,
  vacancy_id_raw
) VALUES %s
"""


class RawBatchWriter:
    """Batch writer for raw.vacancies and raw.quarantine."""

    def __init__(
        self,
        connection: ConnectionLike,
        *,
        batch_size: int = 500,
        execute_values_fn: Callable[..., None] = execute_values,
    ) -> None:
        self.connection = connection
        self.batch_size = batch_size
        self.execute_values_fn = execute_values_fn

    def write_batch(self, items: Sequence[Dict[str, Any]], context: RawWriteContext) -> BatchWriteResult:
        """Write one batch of payload items into raw and quarantine tables."""
        ingested_at = context.ingested_at or datetime.now(timezone.utc)

        raw_rows: List[Tuple[Any, ...]] = []
        quarantine_rows: List[Tuple[Any, ...]] = []
        max_source_modified_at: Optional[datetime] = None

        for item in items:
            row, quarantine_row = self._prepare_rows(item=item, context=context, ingested_at=ingested_at)
            if row is not None:
                raw_rows.append(row)
                source_modified_at = row[9]
                if isinstance(source_modified_at, datetime):
                    if max_source_modified_at is None or source_modified_at > max_source_modified_at:
                        max_source_modified_at = source_modified_at
            if quarantine_row is not None:
                quarantine_rows.append(quarantine_row)

        raw_inserted = 0
        quarantine_inserted = 0

        try:
            with self.connection.cursor() as cursor:
                if raw_rows:
                    raw_inserted = self._insert_values(cursor=cursor, sql=RAW_INSERT_SQL, rows=raw_rows)
                if quarantine_rows:
                    quarantine_inserted = self._insert_values(
                        cursor=cursor,
                        sql=QUARANTINE_INSERT_SQL,
                        rows=quarantine_rows,
                    )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

        return BatchWriteResult(
            items_total=len(items),
            raw_candidates=len(raw_rows),
            raw_rows_inserted=raw_inserted,
            raw_rows_skipped_conflict=len(raw_rows) - raw_inserted,
            quarantine_candidates=len(quarantine_rows),
            quarantine_rows_inserted=quarantine_inserted,
            max_source_modified_at=max_source_modified_at,
            max_ingested_at=ingested_at if raw_inserted > 0 or quarantine_inserted > 0 else None,
        )

    def _insert_values(self, *, cursor: CursorLike, sql: str, rows: Sequence[Tuple[Any, ...]]) -> int:
        inserted = 0
        for chunk in _chunked(rows, self.batch_size):
            self.execute_values_fn(cursor, sql, chunk, page_size=self.batch_size)
            inserted += max(0, int(cursor.rowcount))
        return inserted

    def _prepare_rows(
        self,
        *,
        item: Dict[str, Any],
        context: RawWriteContext,
        ingested_at: datetime,
    ) -> Tuple[Optional[Tuple[Any, ...]], Optional[Tuple[Any, ...]]]:
        if not isinstance(item, dict):
            quarantine_row = _build_quarantine_row(
                context=context,
                ingested_at=ingested_at,
                payload=None,
                error_type="INVALID_PAYLOAD_FORMAT",
                error_reason=f"expected dict payload, got {type(item).__name__}",
                vacancy_id_raw=None,
            )
            return None, quarantine_row

        vacancy_id = _extract_text(item.get("id"))
        source_modified_at_raw = _extract_text(item.get("date_modify"))
        region_code_raw = _extract_region_code(item)

        missing = []
        if vacancy_id is None:
            missing.append("id")
        if source_modified_at_raw is None:
            missing.append("date_modify")
        if region_code_raw is None:
            missing.append("region.region_code")

        if missing:
            quarantine_row = _build_quarantine_row(
                context=context,
                ingested_at=ingested_at,
                payload=item,
                error_type="MISSING_REQUIRED_FIELD",
                error_reason=f"missing required fields: {', '.join(missing)}",
                vacancy_id_raw=vacancy_id,
            )
            return None, quarantine_row

        payload_sha256 = hashlib.sha256(
            json.dumps(item, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ).hexdigest()

        raw_row = (
            context.run_id,
            ingested_at,
            context.source_system,
            context.endpoint,
            Json(context.request_params),
            context.http_status,
            Json(item),
            vacancy_id,
            source_modified_at_raw,
            _parse_source_modified_at(source_modified_at_raw),
            region_code_raw,
            Json(context.response_meta) if context.response_meta is not None else None,
            context.request_url,
            payload_sha256,
        )
        return raw_row, None


def _build_quarantine_row(
    *,
    context: RawWriteContext,
    ingested_at: datetime,
    payload: Optional[Dict[str, Any]],
    error_type: str,
    error_reason: str,
    vacancy_id_raw: Optional[str],
) -> Tuple[Any, ...]:
    return (
        context.run_id,
        ingested_at,
        context.source_system,
        context.endpoint,
        Json(context.request_params),
        context.http_status,
        Json(payload) if payload is not None else None,
        error_type,
        error_reason,
        vacancy_id_raw,
    )


def _extract_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str) and value.strip() == "":
        return None
    return str(value)


def _extract_region_code(payload: Dict[str, Any]) -> Optional[str]:
    region = payload.get("region")
    if not isinstance(region, dict):
        return None
    return _extract_text(region.get("region_code"))


def _parse_source_modified_at(value: str) -> Optional[datetime]:
    formats = ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ")
    for fmt in formats:
        try:
            parsed = datetime.strptime(value, fmt)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def _chunked(rows: Sequence[Tuple[Any, ...]], size: int) -> Iterable[List[Tuple[Any, ...]]]:
    for idx in range(0, len(rows), size):
        yield list(rows[idx : idx + size])
