"""S3-7 用量聚合：按 UTC 日 × scene × model 聚合与 totals。"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.services.usage_service import get_usage


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class FakeSession:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, statement):
        return FakeResult(self.rows)


def test_usage_aggregates_rows_and_totals() -> None:
    rows = [
        (
            date(2026, 11, 1),
            "qa",
            "qwen-plus",
            2,
            0,
            100,
            50,
            150,
            Decimal("0.0002"),
            1200,
        ),
        (
            date(2026, 11, 1),
            "embed",
            "text-embedding-v4",
            3,
            1,
            300,
            0,
            300,
            Decimal("0.0001"),
            80,
        ),
    ]
    report = get_usage(FakeSession(rows), range_key="7d")
    assert report.range == "7d"
    assert (report.end_date - report.start_date).days == 6
    assert report.totals.calls == 5
    assert report.totals.failed_calls == 1
    assert report.totals.total_tokens == 450
    assert report.totals.cost_yuan == pytest.approx(0.0003)
    assert report.totals.avg_latency_ms == 256
    assert [item.scene for item in report.items] == ["qa", "embed"]


def test_usage_empty_range() -> None:
    report = get_usage(FakeSession([]), range_key="1d")
    assert report.items == []
    assert report.totals.calls == 0
    assert report.totals.cost_yuan == 0.0
    assert report.totals.avg_latency_ms == 0