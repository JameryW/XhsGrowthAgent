"""Node latency aggregation — a report that hides gaps is worse than none."""

from __future__ import annotations

from backend.services.node_latency import HOTSPOT_SHARE, aggregate


def _node(agent: str, start: str, end: str, *, error: str = "") -> dict:
    from datetime import datetime

    duration = (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()
    return {
        "kind": "node",
        "agent": agent,
        "started_at": start,
        "completed_at": end,
        "duration_seconds": duration,
        "status": "completed",
        "error": error or None,
        "retries": 0,
    }


class TestNoData:
    def test_empty_is_a_finding_not_zeros(self):
        report = aggregate([])
        assert report.has_data is False
        assert report.verdict == "no_data"
        assert report.total_node_seconds == 0.0

    def test_non_node_entries_are_ignored(self):
        report = aggregate([{"kind": "llm", "agent": "x", "duration_seconds": 5}])
        assert report.has_data is False
        assert report.node_entries == 0

    def test_unparseable_durations_are_counted_not_dropped(self):
        report = aggregate(
            [
                _node("a", "2026-10-18T10:00:00", "2026-10-18T10:00:10"),
                {"kind": "node", "agent": "b"},
            ]
        )
        assert report.has_data is True
        assert report.skipped_entries == 1
        assert any("lacked a numeric duration" in r for r in report.reasons)


class TestAggregation:
    def test_shares_sum_to_one(self):
        events = [
            _node("analyst", "2026-10-18T10:00:00", "2026-10-18T10:00:10"),
            _node("writer", "2026-10-18T10:00:10", "2026-10-18T10:00:30"),
            _node("publisher", "2026-10-18T10:00:30", "2026-10-18T10:00:40"),
        ]
        report = aggregate(events)
        assert abs(sum(a.share for a in report.agents) - 1.0) < 1e-6
        assert report.agents[0].agent == "writer"  # sorted by total desc

    def test_errors_are_counted_per_agent(self):
        events = [
            _node("a", "2026-10-18T10:00:00", "2026-10-18T10:00:05", error="boom"),
            _node("a", "2026-10-18T10:00:05", "2026-10-18T10:00:10"),
        ]
        report = aggregate(events)
        assert report.agents[0].errors == 1
        assert report.agents[0].calls == 2


class TestVerdict:
    def test_fully_serial_run_is_node_bound(self):
        events = [
            _node("a", "2026-10-18T10:00:00", "2026-10-18T10:00:10"),
            _node("b", "2026-10-18T10:00:10", "2026-10-18T10:00:30"),
        ]
        report = aggregate(events)
        assert report.serial_ratio == 1.0
        assert report.verdict == "node_bound"

    def test_overlapping_time_reports_existing_parallelism(self):
        both = [
            _node("a", "2026-10-18T10:00:00", "2026-10-18T10:00:10"),
            _node("b", "2026-10-18T10:00:00", "2026-10-18T10:00:10"),
        ]
        report = aggregate(both)
        assert report.serial_ratio == 2.0
        assert report.verdict == "parallel_time_present"

    def test_low_serial_ratio_is_waiting_not_parallel(self):
        # 5s of node work inside a 10s wall clock: the other 5s is a wait
        # (approval / external call), which more agents cannot shorten.
        # 5s of node work inside a 10s wall (the marker pins the wall clock).
        report = aggregate(
            [
                _node("a", "2026-10-18T10:00:00", "2026-10-18T10:00:05"),
                {
                    "kind": "node",
                    "agent": "marker",
                    "duration_seconds": 0,
                    "started_at": "2026-10-18T10:00:10",
                    "completed_at": "2026-10-18T10:00:10",
                },
            ]
        )
        assert report.serial_ratio < 0.9
        assert report.verdict == "waiting_not_parallel"

    def test_hotspot_is_named(self):
        events = [
            _node("slow", "2026-10-18T10:00:00", "2026-10-18T10:00:45"),
            _node("fast", "2026-10-18T10:00:45", "2026-10-18T10:00:50"),
        ]
        report = aggregate(events)
        assert report.agents[0].share >= HOTSPOT_SHARE
        assert any("hotspot: slow" in r for r in report.reasons)

    def test_missing_timestamps_leave_verdict_insufficient(self):
        report = aggregate([{"kind": "node", "agent": "a", "duration_seconds": 3}])
        assert report.has_data is True
        assert report.verdict == "insufficient_evidence"
        assert any("no timestamps" in r for r in report.reasons)
