"""Tests for node-level performance_log instrumentation.

Covers PRD 节点级指标 PR1: BaseAgent.__call__ writes a `kind:"node"` entry
on success, record_human_wait builds a gate-wait entry, and readers filter
on `kind` for back-compat.
"""

from __future__ import annotations

import pytest

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

    async def test_failure_reraises_no_perf_in_result(self):
        # On exception __call__ re-raises (LangGraph retry needs it); no dict
        # is returned, so no perf entry can be written mid-exception. The
        # retry's next successful call records the attempt count via retries.
        agent = _DummyAgent(exc=RuntimeError("boom"))
        from backend.core.error_handling import AgentError

        with pytest.raises(AgentError):
            await agent({}, store=None)

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


class TestLLMInstrumentation:
    """PRD 节点级指标 PR2: _InstrumentedModel records kind:"llm" entries."""

    async def test_ainvoke_records_llm_entry_with_cost(self):
        from unittest.mock import AsyncMock, MagicMock

        from backend.agents.base import BaseAgent, _InstrumentedModel
        from backend.config.models import TaskType

        class _A(BaseAgent):
            task_type = TaskType.WRITING
            agent_name = "llm_test"
            prompt_file = ""

            async def execute(self, state, store):  # type: ignore[override]
                return {}

        agent = _A()
        raw = MagicMock()
        raw.model = "claude-sonnet-4-20250514"
        raw.ainvoke = AsyncMock()
        raw.ainvoke.return_value = MagicMock(
            usage_metadata={"input_tokens": 1000, "output_tokens": 500}
        )

        instrumented = _InstrumentedModel(raw, agent)
        await instrumented.ainvoke("msgs")

        assert len(agent._perf_buffer) == 1
        entry = agent._perf_buffer[0]
        assert entry["kind"] == "llm"
        assert entry["model"] == "claude-sonnet-4-20250514"
        assert entry["input_tokens"] == 1000
        assert entry["output_tokens"] == 500
        # 1000/1000 * 0.003 + 500/1000 * 0.015 = 0.003 + 0.0075 = 0.0105
        assert entry["cost_usd"] == round(0.0105, 6)

    async def test_ainvoke_returns_original_response(self):
        from unittest.mock import AsyncMock, MagicMock

        from backend.agents.base import BaseAgent, _InstrumentedModel
        from backend.config.models import TaskType

        class _A(BaseAgent):
            task_type = TaskType.WRITING
            agent_name = "llm_test2"
            prompt_file = ""

            async def execute(self, state, store):  # type: ignore[override]
                return {}

        agent = _A()
        raw = MagicMock()
        raw.model = "gpt-4o"
        original_resp = MagicMock(usage_metadata={})
        raw.ainvoke = AsyncMock(return_value=original_resp)

        instrumented = _InstrumentedModel(raw, agent)
        result = await instrumented.ainvoke("msgs")
        assert result is original_resp

    async def test_instrument_failure_does_not_break_call(self):
        from unittest.mock import AsyncMock, MagicMock

        from backend.agents.base import BaseAgent, _InstrumentedModel
        from backend.config.models import TaskType

        class _A(BaseAgent):
            task_type = TaskType.WRITING
            agent_name = "llm_test3"
            prompt_file = ""

            async def execute(self, state, store):  # type: ignore[override]
                return {}

        agent = _A()
        raw = MagicMock()
        raw.model = "claude-sonnet-4-20250514"
        # usage_metadata access raises → instrumentation must swallow, not break
        resp = MagicMock()
        type(resp).usage_metadata = property(
            lambda self: (_ for _ in ()).throw(RuntimeError("nope"))
        )
        raw.ainvoke = AsyncMock(return_value=resp)

        instrumented = _InstrumentedModel(raw, agent)
        result = await instrumented.ainvoke("msgs")
        assert result is resp
        assert agent._perf_buffer == []

    async def test_call_flushes_llm_buffer_with_node_entry(self):

        from backend.agents.base import BaseAgent
        from backend.config.models import TaskType

        class _A(BaseAgent):
            task_type = TaskType.WRITING
            agent_name = "flush_test"
            prompt_file = ""

            async def execute(self, state, store):  # type: ignore[override]
                # simulate an LLM call during execute
                self._perf_buffer.append({"kind": "llm", "model": "x", "cost_usd": 0.01})
                return {}

        agent = _A()
        result = await agent({}, store=None)
        kinds = [e["kind"] for e in result["performance_log"]]
        assert kinds == ["node", "llm"]
        assert agent._perf_buffer == []  # flushed


class TestRippleInstrumentation:
    """PRD 节点级指标 PR2: _time_ripple buffers kind:"ripple" entries.

    Uses object.__new__ to bypass the conftest auto-mock of
    RippleService.get_instance (which returns a MagicMock for the rest of
    the suite).
    """

    def _fresh_svc(self):
        from backend.services.ripple_service import RippleService

        svc = object.__new__(RippleService)
        svc._ripple_perf = []
        return svc

    async def test_time_ripple_records_success_entry(self):
        from backend.services.ripple_service import _time_ripple

        svc = self._fresh_svc()

        @_time_ripple("predict_spread")
        async def fake_call(self, topic):  # type: ignore[no-untyped-def]
            return {"topic": topic}

        await fake_call(svc, topic="t")  # type: ignore[arg-type]

        entries = svc.drain_ripple_perf()
        assert len(entries) == 1
        assert entries[0]["kind"] == "ripple"
        assert entries[0]["operation"] == "predict_spread"
        assert entries[0]["status"] == "success"
        assert entries[0]["duration_seconds"] >= 0.0

    async def test_time_ripple_records_failed_entry_and_reraises(self):
        import pytest

        from backend.services.ripple_service import _time_ripple

        svc = self._fresh_svc()

        @_time_ripple("validate_pmf")
        async def boom(self, *a, **kw):  # type: ignore[no-untyped-def]
            raise RuntimeError("ripple down")

        with pytest.raises(RuntimeError):
            await boom(svc)  # type: ignore[arg-type]

        entries = svc.drain_ripple_perf()
        assert len(entries) == 1
        assert entries[0]["status"] == "failed"

    def test_drain_ripple_perf_clears_buffer(self):
        svc = self._fresh_svc()
        svc._ripple_perf.append({"kind": "ripple", "operation": "x"})
        first = svc.drain_ripple_perf()
        assert len(first) == 1
        assert svc.drain_ripple_perf() == []
