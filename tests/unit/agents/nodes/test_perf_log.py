"""Tests for node-level performance_log instrumentation.

Covers PRD 节点级指标 PR1: BaseAgent.__call__ writes a `kind:"node"` entry
on success, record_human_wait builds a gate-wait entry, and readers filter
on `kind` for back-compat.
"""

from __future__ import annotations

from backend.agents.base import BaseAgent
from backend.agents.nodes._base import (
    llm_perf_entry,
    node_perf_entry,
    record_human_wait,
)
from backend.config.models import TaskType


class _DummyAgent(BaseAgent):
    task_type = TaskType.ROUTING
    agent_name = "dummy"
    prompt_file = ""

    def __init__(self, *, result=None, exc=None, llm_entries=None):
        super().__init__()
        self._result = result or {}
        self._exc = exc
        self._llm_entries = llm_entries or []

    async def execute(self, state, store):  # type: ignore[override]
        # Simulate _llm_ainvoke capturing entries during execute() — must happen
        # before any raise so the failure path still records captured cost.
        self._llm_perf_entries = list(self._llm_entries)
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


class _FakeLLMResponse:
    """Minimal stand-in for a LangChain AIMessage with usage metadata."""

    def __init__(self, *, input_tokens, output_tokens, model_name=None):
        self.usage_metadata = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        }
        self.response_metadata = {"model_name": model_name} if model_name else {}
        self.content = "{}"


class TestLlmPerfEntry:
    def test_builds_entry_with_cost_from_canonical_table(self):
        # astron-code-latest: $0.0002 input / $0.0006 output per 1K tokens
        # 1000 in + 500 out -> (1000/1000)*0.0002 + (500/1000)*0.0006 = 0.0005
        resp = _FakeLLMResponse(
            input_tokens=1000, output_tokens=500, model_name="astron-code-latest"
        )
        entry = llm_perf_entry(
            "copywriter",
            resp,
            "astron-code-latest",
            started_at="2026-08-04T00:00:00+00:00",
            completed_at="2026-08-04T00:00:02+00:00",
        )
        assert entry["kind"] == "llm"
        assert entry["agent"] == "copywriter"
        assert entry["model"] == "astron-code-latest"
        assert entry["input_tokens"] == 1000
        assert entry["output_tokens"] == 500
        assert entry["cost_usd"] == round(0.0002 + 0.0003, 6)
        assert entry["timestamp"] == "2026-08-04T00:00:02+00:00"
        assert entry["duration_seconds"] == 2.0

    def test_returns_none_when_no_usage(self):
        # Timeout/degraded path: no response usage -> nothing to record.
        resp = _FakeLLMResponse(input_tokens=0, output_tokens=0)
        entry = llm_perf_entry(
            "evaluator",
            resp,
            "astron-code-latest",
            started_at="2026-08-04T00:00:00+00:00",
            completed_at="2026-08-04T00:00:01+00:00",
        )
        assert entry is None

    def test_falls_back_to_routed_model_when_response_has_no_model_name(self):
        resp = _FakeLLMResponse(input_tokens=100, output_tokens=50, model_name=None)
        entry = llm_perf_entry(
            "analyst",
            resp,
            "astron-code-latest",
            started_at="2026-08-04T00:00:00+00:00",
            completed_at="2026-08-04T00:00:01+00:00",
        )
        assert entry["model"] == "astron-code-latest"

    def test_unknown_model_uses_default_rate(self):
        resp = _FakeLLMResponse(input_tokens=1000, output_tokens=1000, model_name="mystery-model")
        entry = llm_perf_entry(
            "x",
            resp,
            "mystery-model",
            started_at="2026-08-04T00:00:00+00:00",
            completed_at="2026-08-04T00:00:01+00:00",
        )
        # default 0.001/0.005 per 1K -> 0.001 + 0.005 = 0.006
        assert entry["cost_usd"] == round(0.001 + 0.005, 6)


class TestLlmEntryMerge:
    async def test_llm_entries_merged_with_node_entry(self):
        llm_entry = {
            "kind": "llm",
            "agent": "dummy",
            "model": "astron-code-latest",
            "input_tokens": 100,
            "output_tokens": 50,
            "cost_usd": 0.001,
        }
        agent = _DummyAgent(result={"copy_content": {"body": "hi"}}, llm_entries=[llm_entry])
        result = await agent({"retry_count": 0}, store=None)
        # node entry first, then the llm entry
        assert len(result["performance_log"]) == 2
        assert result["performance_log"][0]["kind"] == "node"
        assert result["performance_log"][1]["kind"] == "llm"
        assert result["performance_log"][1]["cost_usd"] == 0.001

    async def test_failure_path_preserves_llm_entries_before_crash(self):
        # An LLM call succeeded (entry captured) but execute later raised;
        # the captured cost must still ride the failed perf entry.
        llm_entry = {"kind": "llm", "cost_usd": 0.002, "model": "astron-code-latest"}
        agent = _DummyAgent(exc=RuntimeError("late crash"), llm_entries=[llm_entry])
        result = await agent({"retry_count": 0}, store=None)
        kinds = [e["kind"] for e in result["performance_log"]]
        assert kinds == ["node", "llm"]
        assert result["performance_log"][0]["status"] == "failed"
        assert result["performance_log"][1]["cost_usd"] == 0.002
