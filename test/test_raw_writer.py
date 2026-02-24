import unittest
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.trudvsem.raw_writer import BatchWriteResult, RawBatchWriter, RawWriteContext


class _FakeCursor:
    def __init__(self) -> None:
        self.rowcount = 0

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        return None


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


class _ExecuteValuesSpy:
    def __init__(self, inserted_raw_per_call: int, inserted_quarantine_per_call: int) -> None:
        self.inserted_raw_per_call = inserted_raw_per_call
        self.inserted_quarantine_per_call = inserted_quarantine_per_call
        self.calls: List[Dict[str, Any]] = []

    def __call__(
        self,
        cursor: _FakeCursor,
        sql: str,
        rows: Sequence[Tuple[Any, ...]],
        page_size: Optional[int] = None,
    ) -> None:
        self.calls.append({"sql": sql, "rows": list(rows), "page_size": page_size})
        if "raw.vacancies" in sql:
            cursor.rowcount = self.inserted_raw_per_call
        elif "raw.quarantine" in sql:
            cursor.rowcount = self.inserted_quarantine_per_call
        else:
            cursor.rowcount = 0


def _valid_item(vacancy_id: str = "id-1") -> Dict[str, Any]:
    return {
        "id": vacancy_id,
        "date_modify": "2026-02-20T13:34:06+0300",
        "region": {"region_code": "6600000000000"},
        "name": "Some vacancy",
    }


class RawWriterTests(unittest.TestCase):
    def test_write_batch_sends_invalid_items_to_quarantine(self) -> None:
        conn = _FakeConnection()
        spy = _ExecuteValuesSpy(inserted_raw_per_call=1, inserted_quarantine_per_call=2)
        writer = RawBatchWriter(conn, batch_size=100, execute_values_fn=spy)
        context = RawWriteContext(
            run_id="run-1",
            endpoint="/api/v1/vacancies",
            request_params={"offset": 1, "limit": 100},
            http_status=200,
            ingested_at=datetime(2026, 2, 21, 10, 0, 0, tzinfo=timezone.utc),
        )

        result = writer.write_batch(
            [
                _valid_item("id-1"),
                {"id": "id-2", "date_modify": "2026-02-20T13:34:06+0300", "region": {}},
                {"date_modify": "2026-02-20T13:34:06+0300", "region": {"region_code": "7700000000000"}},
            ],
            context,
        )

        self.assertEqual(result.items_total, 3)
        self.assertEqual(result.raw_candidates, 1)
        self.assertEqual(result.raw_rows_inserted, 1)
        self.assertEqual(result.raw_rows_skipped_conflict, 0)
        self.assertEqual(result.quarantine_candidates, 2)
        self.assertEqual(result.quarantine_rows_inserted, 2)
        self.assertIsNotNone(result.max_source_modified_at)
        self.assertEqual(result.max_ingested_at, datetime(2026, 2, 21, 10, 0, 0, tzinfo=timezone.utc))
        self.assertEqual(conn.commits, 1)
        self.assertEqual(conn.rollbacks, 0)
        self.assertEqual(len(spy.calls), 2)

    def test_write_batch_computes_skipped_conflicts(self) -> None:
        conn = _FakeConnection()
        spy = _ExecuteValuesSpy(inserted_raw_per_call=1, inserted_quarantine_per_call=0)
        writer = RawBatchWriter(conn, batch_size=100, execute_values_fn=spy)
        context = RawWriteContext(
            run_id="run-2",
            endpoint="/api/v1/vacancies",
            request_params={"offset": 1, "limit": 100},
            http_status=200,
        )

        result: BatchWriteResult = writer.write_batch([_valid_item("id-1"), _valid_item("id-2")], context)

        self.assertEqual(result.raw_candidates, 2)
        self.assertEqual(result.raw_rows_inserted, 1)
        self.assertEqual(result.raw_rows_skipped_conflict, 1)
        self.assertEqual(result.quarantine_candidates, 0)
        self.assertEqual(result.quarantine_rows_inserted, 0)
        self.assertIsNotNone(result.max_source_modified_at)
        self.assertIsNotNone(result.max_ingested_at)

    def test_write_batch_rolls_back_on_insert_failure(self) -> None:
        conn = _FakeConnection()

        def broken_execute_values(
            cursor: _FakeCursor,
            sql: str,
            rows: Sequence[Tuple[Any, ...]],
            page_size: Optional[int] = None,
        ) -> None:
            raise RuntimeError("db unavailable")

        writer = RawBatchWriter(conn, batch_size=100, execute_values_fn=broken_execute_values)
        context = RawWriteContext(
            run_id="run-3",
            endpoint="/api/v1/vacancies",
            request_params={"offset": 1, "limit": 100},
            http_status=200,
        )

        with self.assertRaises(RuntimeError):
            writer.write_batch([_valid_item("id-1")], context)

        self.assertEqual(conn.commits, 0)
        self.assertEqual(conn.rollbacks, 1)


if __name__ == "__main__":
    unittest.main()
