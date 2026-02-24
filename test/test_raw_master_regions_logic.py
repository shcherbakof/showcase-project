import unittest
from datetime import datetime, timezone

from src.jobs.raw_master_regions_logic import compute_window_to


class RawMasterRegionsLogicTests(unittest.TestCase):
    def test_compute_window_to_with_positive_lag(self) -> None:
        window_from = datetime(2026, 2, 23, 10, 0, tzinfo=timezone.utc)
        now_utc = datetime(2026, 2, 23, 11, 0, tzinfo=timezone.utc)

        result = compute_window_to(window_from=window_from, safety_lag_sec=300, now_utc=now_utc)

        self.assertEqual(result, datetime(2026, 2, 23, 10, 55, tzinfo=timezone.utc))

    def test_compute_window_to_not_less_than_from(self) -> None:
        window_from = datetime(2026, 2, 23, 10, 0, tzinfo=timezone.utc)
        now_utc = datetime(2026, 2, 23, 10, 1, tzinfo=timezone.utc)

        result = compute_window_to(window_from=window_from, safety_lag_sec=600, now_utc=now_utc)

        self.assertEqual(result, window_from)


if __name__ == "__main__":
    unittest.main()
