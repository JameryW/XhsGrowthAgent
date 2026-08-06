"""Tests for scripts/collect_latency.py — JSON extraction + aggregation."""

from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from scripts.collect_latency import (  # noqa: E402
    _EVENT_MARKER,
    _extract_json,
    _fetch_lines,
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


def test_marker_matches_spaced_and_compact():
    # backend/api/latency.py emits via json.dumps → space after the colon.
    spaced = '{"event": "http_latency", "endpoint": "/list", "total_ms": 5.0}'
    compact = '{"event":"http_latency","endpoint":"/status","total_ms":3.0}'
    non_latency = '{"event": "other", "endpoint": "/x"}'
    assert _EVENT_MARKER.search(spaced) is not None
    assert _EVENT_MARKER.search(compact) is not None
    assert _EVENT_MARKER.search(non_latency) is None


def test_fetch_lines_yields_spaced_marker(tmp_path: Path) -> None:
    # Real prod format: json.dumps output has a space after the colon.
    spaced_line = (
        '{"event": "http_latency", "endpoint": "/list", "total_ms": 5.0, '
        '"db_ms": 4.0, "serialize_ms": 1.0}'
    )
    log = tmp_path / "latency.log"
    log.write_text(
        "2026-08-06 10:00:00 noise line\n"
        f"2026-08-06 10:00:01 {spaced_line}\n"
        "2026-08-06 10:00:02 more noise\n",
        encoding="utf-8",
    )
    args = type("Args", (), {"file": str(log), "since": "", "container": ""})()
    lines = list(_fetch_lines(args))
    assert len(lines) == 1
    obj = _extract_json(lines[0])
    assert obj is not None
    assert obj["endpoint"] == "/list"
    assert obj["total_ms"] == 5.0


def test_fetch_lines_yields_compact_marker(tmp_path: Path) -> None:
    # Backward compat: older log lines may use the compact form.
    compact_line = (
        '{"event":"http_latency","endpoint":"/status","total_ms":3.0,'
        '"db_ms":1.0,"serialize_ms":1.0}'
    )
    log = tmp_path / "compact.log"
    log.write_text(f"ts {compact_line}\n", encoding="utf-8")
    args = type("Args", (), {"file": str(log), "since": "", "container": ""})()
    lines = list(_fetch_lines(args))
    assert len(lines) == 1
    obj = _extract_json(lines[0])
    assert obj is not None
    assert obj["endpoint"] == "/status"


def test_fetch_lines_skips_non_latency(tmp_path: Path) -> None:
    log = tmp_path / "other.log"
    log.write_text(
        '{"event": "other", "endpoint": "/x", "total_ms": 1.0}\nplain text line\n',
        encoding="utf-8",
    )
    args = type("Args", (), {"file": str(log), "since": "", "container": ""})()
    assert list(_fetch_lines(args)) == []


def test_aggregate_from_spaced_marker_lines(tmp_path: Path) -> None:
    # End-to-end: spaced-marker prod-format lines → sane per-endpoint
    # p50/p95/avg + per-segment p50.
    log = tmp_path / "prod.log"
    log.write_text(
        '{"event": "http_latency", "endpoint": "/list", "phase": "ok", '
        '"total_ms": 5.0, "db_ms": 4.0, "serialize_ms": 1.0}\n'
        '{"event": "http_latency", "endpoint": "/list", "phase": "ok", '
        '"total_ms": 15.0, "db_ms": 10.0, "serialize_ms": 2.0}\n'
        '{"event": "http_latency", "endpoint": "/status", "phase": "completed", '
        '"total_ms": 20.0, "aget_state_ms": 8.0, "db_ms": 2.0, "serialize_ms": 5.0}\n',
        encoding="utf-8",
    )
    args = type("Args", (), {"file": str(log), "since": "", "container": ""})()
    records = [obj for line in _fetch_lines(args) if (obj := _extract_json(line)) is not None]
    assert len(records) == 3

    buf = io.StringIO()
    with redirect_stdout(buf):
        aggregate(records)
    out = buf.getvalue()

    # /list n=2 → p50=5.0, p95=15.0, avg=10.0; /status n=1 → all 20.0
    assert "/list" in out
    assert "/status" in out
    assert "completed" in out
    # header present
    assert "p50_ms" in out and "p95_ms" in out and "avg_ms" in out
    # per-segment p50 columns emitted
    assert "db=" in out
    assert "serialize=" in out
