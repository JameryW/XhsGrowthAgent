"""Tests for tool-path LLM cost capture via the ContextVar accumulator.

Covers the prd (08-06-track-tool-llm-cost-enrich-with-llm): enrich_with_llm
calls made inside tools bypass BaseAgent._llm_ainvoke, so their token cost was
invisible to the /analytics/costs reader. A ContextVar (_tool_llm_cost) set by
BaseAgent.__call__ before execute() lets enrich_with_llm append kind:"llm"
entries; __call__ drains them into self._llm_perf_entries so they ride
performance_log. Approach A — no signature changes.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from backend.agents.base import BaseAgent
from backend.agents.nodes._base import _tool_llm_cost
from backend.config.models import TaskType
from backend.services.llm_enrichment import LLMEnrichmentService


class _FakeResponse:
    """Minimal stand-in for a LangChain AIMessage with usage metadata."""

    def __init__(self, *, input_tokens: int, output_tokens: int) -> None:
        self.usage_metadata = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        }
        self.response_metadata = {}  # no model_name → falls back to routed id
        self.content = '{"result": "ok"}'


class TestEnrichCostCapture:
    """enrich_with_llm appends to the ContextVar only when an agent set it."""

    async def test_enrich_captures_cost_in_contextvar_scope(self):
        # Simulate the BaseAgent.__call__ scope: ContextVar set to a live list.
        bucket: list[dict] = []
        token = _tool_llm_cost.set(bucket)
        try:
            service = LLMEnrichmentService()
            fake_model = MagicMock()
            fake_model.ainvoke = AsyncMock(
                return_value=_FakeResponse(input_tokens=100, output_tokens=50)
            )
            with patch.object(service, "_get_model", return_value=fake_model):
                result = await service.enrich_with_llm(
                    task_type=TaskType.POLISH,
                    prompt_template={"system": "s", "user_template": "u"},
                    input_data={},
                )
            # Call still returns the parsed result
            assert result == {"result": "ok"}
        finally:
            _tool_llm_cost.reset(token)

        # One kind:"llm" entry was appended, tagged tool:polish, with cost.
        assert len(bucket) == 1
        entry = bucket[0]
        assert entry["kind"] == "llm"
        assert entry["agent"] == "tool:polish"
        assert entry["input_tokens"] == 100
        assert entry["output_tokens"] == 50
        assert entry["cost_usd"] > 0

    async def test_enrich_no_crash_when_contextvar_unset(self):
        # omp/manual standalone path: ContextVar at default None. Capture is
        # skipped and the call still succeeds.
        assert _tool_llm_cost.get() is None
        service = LLMEnrichmentService()
        fake_model = MagicMock()
        fake_model.ainvoke = AsyncMock(
            return_value=_FakeResponse(input_tokens=100, output_tokens=50)
        )
        with patch.object(service, "_get_model", return_value=fake_model):
            result = await service.enrich_with_llm(
                task_type=TaskType.POLISH,
                prompt_template={"system": "s", "user_template": "u"},
                input_data={},
            )
        assert result == {"result": "ok"}
        # Still None — no scope was set, nothing appended, no crash.
        assert _tool_llm_cost.get() is None

    async def test_capture_failure_does_not_break_call(self):
        # A bug in the capture path (e.g. llm_perf_entry raising) must never
        # trip the fallback — the call returns the parsed result.
        bucket: list[dict] = []
        token = _tool_llm_cost.set(bucket)
        try:
            service = LLMEnrichmentService()
            fake_model = MagicMock()
            fake_model.ainvoke = AsyncMock(
                return_value=_FakeResponse(input_tokens=100, output_tokens=50)
            )
            with (
                patch.object(service, "_get_model", return_value=fake_model),
                patch(
                    "backend.agents.nodes._base.llm_perf_entry",
                    side_effect=RuntimeError("capture boom"),
                ),
            ):
                result = await service.enrich_with_llm(
                    task_type=TaskType.POLISH,
                    prompt_template={"system": "s", "user_template": "u"},
                    input_data={},
                )
            assert result == {"result": "ok"}
            assert bucket == []  # capture failed, nothing appended
        finally:
            _tool_llm_cost.reset(token)


class _ToolCallingAgent(BaseAgent):
    """Agent whose execute() runs enrich_with_llm (the workflow path)."""

    task_type = TaskType.POLISH
    agent_name = "copywriter"
    prompt_file = ""

    def __init__(self, *, service: LLMEnrichmentService) -> None:
        super().__init__()
        self._service = service

    async def execute(self, state, store):  # type: ignore[override]
        self._reset_llm_perf()  # real agents reset at execute() start
        await self._service.enrich_with_llm(
            task_type=TaskType.POLISH,
            prompt_template={"system": "s", "user_template": "u"},
            input_data={},
        )
        return {"copy_content": {"body": "polished"}}


class TestBaseAgentDrainsToolEntries:
    """BaseAgent.__call__ drains the ContextVar into performance_log."""

    async def test_baseagent_call_drains_tool_entries_into_perf_log(self):
        service = LLMEnrichmentService()
        fake_model = MagicMock()
        fake_model.ainvoke = AsyncMock(
            return_value=_FakeResponse(input_tokens=100, output_tokens=50)
        )
        patch_get_model = patch.object(service, "_get_model", return_value=fake_model)

        agent = _ToolCallingAgent(service=service)
        with patch_get_model:
            result = await agent({"retry_count": 0}, store=None)

        perf = result["performance_log"]
        kinds = [e["kind"] for e in perf]
        # node entry + the tool-path llm entry drained from the ContextVar
        assert kinds == ["node", "llm"]
        tool_entry = perf[1]
        assert tool_entry["agent"] == "tool:polish"
        assert tool_entry["cost_usd"] > 0
        # execute result still flows through
        assert result["copy_content"] == {"body": "polished"}
        # ContextVar reset to default after __call__ (no scope leaked)
        assert _tool_llm_cost.get() is None

    async def test_no_leakage_across_executes(self):
        # Two consecutive __call__ invocations: entries from the first must NOT
        # appear in the second's perf_log (set/reset token isolation).
        service = LLMEnrichmentService()
        fake_model = MagicMock()
        fake_model.ainvoke = AsyncMock(
            return_value=_FakeResponse(input_tokens=100, output_tokens=50)
        )
        patch_get_model = patch.object(service, "_get_model", return_value=fake_model)

        agent = _ToolCallingAgent(service=service)
        with patch_get_model:
            first = await agent({"retry_count": 0}, store=None)
            second = await agent({"retry_count": 0}, store=None)

        first_llm = [e for e in first["performance_log"] if e["kind"] == "llm"]
        second_llm = [e for e in second["performance_log"] if e["kind"] == "llm"]
        # Each call captured exactly one tool entry; no duplication/leakage.
        assert len(first_llm) == 1
        assert len(second_llm) == 1
        assert first_llm[0] is not second_llm[0]

    async def test_failure_path_drains_tool_entries_before_crash(self):
        # execute() runs enrich_with_llm (entry captured) then raises; the
        # captured cost must still ride the failed perf entry.
        service = LLMEnrichmentService()
        fake_model = MagicMock()
        fake_model.ainvoke = AsyncMock(
            return_value=_FakeResponse(input_tokens=100, output_tokens=50)
        )
        patch_get_model = patch.object(service, "_get_model", return_value=fake_model)

        class _CrashAgent(_ToolCallingAgent):
            async def execute(self, state, store):  # type: ignore[override]
                self._reset_llm_perf()  # real agents reset at execute() start
                await self._service.enrich_with_llm(
                    task_type=TaskType.POLISH,
                    prompt_template={"system": "s", "user_template": "u"},
                    input_data={},
                )
                raise RuntimeError("late crash")

        agent = _CrashAgent(service=service)
        with patch_get_model:
            result = await agent({"retry_count": 0}, store=None)

        kinds = [e["kind"] for e in result["performance_log"]]
        assert kinds == ["node", "llm"]
        assert result["performance_log"][0]["status"] == "failed"
        assert result["performance_log"][1]["agent"] == "tool:polish"
        assert result["performance_log"][1]["cost_usd"] > 0
        assert _tool_llm_cost.get() is None
