# Docs:
# - artifacts/docs/data/3.1.10.2 Контракт watermark для регулярной загрузки регионов 66 77 78.md
# - artifacts/docs/data/3.1.10.3 Master-DAG + Watermark: реализация и валидация.md

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def compute_window_to(*, window_from: datetime, safety_lag_sec: int, now_utc: datetime) -> datetime:
    """Compute upper window bound using safety lag and monotonic lower bound."""

    window_to = now_utc.astimezone(timezone.utc) - timedelta(seconds=max(0, safety_lag_sec))
    if window_to <= window_from:
        return window_from
    return window_to
