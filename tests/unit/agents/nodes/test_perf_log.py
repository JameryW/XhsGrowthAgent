"""Tests for node-level performance_log instrumentation.

Covers PRD 节点级指标 PR1: BaseAgent.__call__ writes a `kind:"node"` entry
on success, record_human_wait builds a gate-wait entry, and readers filter
on `kind` for back-compat.
"""

from __future__ import annotations

from backend.agents.base import BaseAgent
from backend.agents.nodes._base import (
    node_perf_entry,
    record_human_wait,
)
from backend.config.models import TaskType


class _DummyAgent(BaseAgent):
    task_type = TaskType.ROUTING
    agent_name = "dummy"
    prompt_file = ""

    def __init__(self, *, result=None, exc=None):
        super().__init__()
        self._result = result or {}
        self._exc = exc

    async def execute(self, state, store):  # type: ignore[override]
        if self._exc:
            raise self._exc
        return dict(self._result)


class TestNodePerfEntry:
    def test_schema_has_kind_node(self):
        e = node_perf_entry(
            "copywriter",
            started_at="2026-07-06T00:00:00+00:00",
            completed_at="2026-07-06T00:00:03+00:00",
            status="success",
            error=None,
            retries=0,
        )
        assert e["kind"] == "node"
        assert e["agent"] == "copywriter"
        assert e["duration_seconds"] == 3.0
        assert e["status"] == "success"
        assert e["error"] is None
        assert e["retries"] == 0

    def test_duration_zero_on_parse_failure(self):
        e = node_perf_entry(
            "x",
            started_at="not-a-date",
            completed_at="also-bad",
            status="success",
            error=None,
            retries=0,
        )
        assert e["duration_seconds"] == 0.0


class TestCallTiming:
    async def test_success_writes_node_entry(self):
        agent = _DummyAgent(result={"copy_content": {"body": "hi"}})
        state = {"retry_count": 0}
        result = await agent(state, store=None)
        assert result["performance_log"][0]["kind"] == "node"
        assert result["performance_log"][0]["agent"] == "dummy"
        assert result["performance_log"][0]["status"] == "success"
        assert result["performance_log"][0]["retries"] == 0
        # execute result still flows through
        assert result["copy_content"] == {"body": "hi"}

    async def test_retries_sourced_from_state(self):
        agent = _DummyAgent(result={})
        result = await agent({"retry_count": 2}, store=None)
        assert result["performance_log"][0]["retries"] == 2

    async def test_failure_returns_error_state_with_failed_entry(self):
        # After prd 07-07: __call__ returns handle_agent_error(e, state)
        # instead of raising. The returned dict includes a status=failed
        # perf entry (now possible because we return, not raise).
        agent = _DummyAgent(exc=RuntimeError("boom"))
        from backend.state.enums import WorkflowPhase

        result = await agent({"retry_count": 0}, store=None)
        assert result["phase"] == WorkflowPhase.ERROR
        assert "boom" in result["error"]
        assert result["retry_count"] == 1
        assert result["performance_log"][0]["status"] == "failed"
        assert result["performance_log"][0]["agent"] == "dummy"
        assert result["performance_log"][0]["retries"] == 1

    async def test_timer_failure_does_not_break_node(self, monkeypatch):
        # If node_perf_entry throws, the node must still return its result.
        agent = _DummyAgent(result={"copy_content": {"body": "ok"}})

        def boom(*a, **kw):
            raise RuntimeError("timer broken")

        monkeypatch.setattr("backend.agents.nodes._base.node_perf_entry", boom)
        result = await agent({}, store=None)
        # No perf entry (timer failed), but the execute result survives
        assert result["copy_content"] == {"body": "ok"}
        assert "performance_log" not in result


class TestRecordHumanWait:
    def test_computes_wait_from_last_node_entry(self):
        state = {
            "performance_log": [
                {
                    "kind": "node",
                    "agent": "visual_designer",
                    "started_at": "2026-07-06T00:00:00+00:00",
                    "completed_at": "2026-07-06T00:00:05+00:00",
                    "duration_seconds": 5.0,
                    "status": "success",
                    "error": None,
                    "retries": 0,
                }
            ]
        }
        entry = record_human_wait(state, "review_gate", now_iso="2026-07-06T00:05:05+00:00")
        assert entry["kind"] == "human_wait"
        assert entry["gate"] == "review_gate"
        assert entry["entered_at"] == "2026-07-06T00:00:05+00:00"
        assert entry["resumed_at"] == "2026-07-06T00:05:05+00:00"
        assert entry["wait_seconds"] == 300.0

    def test_no_prior_node_entry_yields_empty_entered(self):
        entry = record_human_wait({}, "review_gate", now_iso="2026-07-06T00:05:05+00:00")
        assert entry["entered_at"] == ""
        assert entry["wait_seconds"] == 0.0

    def test_skips_llm_and_human_wait_entries_when_finding_entered(self):
        # entered_at must come from a node entry, not an llm/human_wait entry
        state = {
            "performance_log": [
                {"kind": "llm", "completed_at": "2026-07-06T00:00:01+00:00"},
                {
                    "kind": "node",
                    "completed_at": "2026-07-06T00:00:05+00:00",
                },
            ]
        }
        entry = record_human_wait(state, "review_gate", now_iso="2026-07-06T00:01:05+00:00")
        assert entry["entered_at"] == "2026-07-06T00:00:05+00:00"

    def test_back_compat_no_kind_treated_as_node(self):
        # Pre-kind entries (no `kind`) are the legacy node schema — must still
        # serve as entered_at source.
        state = {
            "performance_log": [
                {"completed_at": "2026-07-06T00:00:05+00:00"},  # no kind
            ]
        }
        entry = record_human_wait(state, "review_gate", now_iso="2026-07-06T00:01:05+00:00")
        assert entry["entered_at"] == "2026-07-06T00:00:05+00:00"
