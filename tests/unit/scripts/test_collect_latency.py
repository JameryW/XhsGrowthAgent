"""Tests for scripts/collect_latency.py — JSON extraction + aggregation."""

from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from scripts.collect_latency import (  # noqa: E402
    _extract_json,
    aggregate,
)

_RAW_LINE = (
    "2026-08-06 10:00:00 xhs_growth.api.latency: "
    '{"event":"http_latency","endpoint":"/status","thread_id":"t1",'
    '"phase":"completed","total_ms":12.3,"aget_state_ms":4.1,'
    '"db_ms":1.2,"serialize_ms":3.0}'
)


def test_extract_json_strips_log_prefix():
    obj = _extract_json(_RAW_LINE)
    assert obj is not None
    assert obj["endpoint"] == "/status"
    assert obj["total_ms"] == 12.3


def test_extract_json_returns_none_for_non_latency_line():
    assert _extract_json("some other log line {not json}") is None
    assert _extract_json('{"event":"other","total_ms":1}') is None


def test_extract_json_returns_none_when_no_brace():
    assert _extract_json("no json here at all") is None


def test_aggregate_groups_by_endpoint_and_phase():
    records = [
        {
            "event": "http_latency",
            "endpoint": "/status",
            "phase": "completed",
            "total_ms": 10.0,
            "aget_state_ms": 4.0,
            "db_ms": 1.0,
            "serialize_ms": 3.0,
        },
        {
            "event": "http_latency",
            "endpoint": "/status",
            "phase": "completed",
            "total_ms": 20.0,
            "aget_state_ms": 8.0,
            "db_ms": 2.0,
            "serialize_ms": 5.0,
        },
        {
            "event": "http_latency",
            "endpoint": "/list",
            "phase": "ok",
            "total_ms": 40.0,
            "db_ms": 30.0,
            "serialize_ms": 8.0,
        },
    ]
    buf = io.StringIO()
    with redirect_stdout(buf):
        aggregate(records)
    out = buf.getvalue()
    assert "/status" in out
    assert "/list" in out
    assert "completed" in out
    assert "Phase breakdown" in out
    # p50 of [10, 20] is 10.0 (nearest-rank); /list single = 40.0
    assert "10.0" in out
    assert "40.0" in out


def test_aggregate_handles_missing_segment_fields():
    # /account-totals has count_ms not db_ms/serialize_ms/aget_state_ms
    records = [
        {
            "event": "http_latency",
            "endpoint": "/account-totals",
            "phase": "ok",
            "total_ms": 5.0,
            "count_ms": 2.0,
        },
    ]
    buf = io.StringIO()
    with redirect_stdout(buf):
        aggregate(records)
    out = buf.getvalue()
    assert "/account-totals" in out
    assert "count=2.0" in out
