"""Regression lock for PR #307: brief_analyzer_node and shooting_planner_node
must route through BaseAgent.__call__, not agent.execute() directly.

__call__ converts agent exceptions into the error state (phase=ERROR, error,
retry_count) for stateful retry; a direct execute() call would raise into the
graph, skip the perf-log entry, and never clear stale errors. These tests fail
if either node regresses to calling execute() directly.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.agents.nodes.brief_analyzer import _agent as _brief_agent
from backend.agents.nodes.brief_analyzer import brief_analyzer_node
from backend.agents.nodes.shooting_planner import _agent as _shooting_agent
from backend.agents.nodes.shooting_planner import shooting_planner_node
from backend.state.enums import WorkflowPhase


async def _failing_execute(self, state, store):
    raise RuntimeError("agent LLM failed")


class TestBriefAnalyzerCallContract:
    @pytest.mark.asyncio
    async def test_failure_returns_error_state_not_raise(self):
        state = {
            "session_id": "test-brief-err",
            "phase": WorkflowPhase.BRIEFING,
            "retry_count": 0,
        }
        with patch.object(type(_brief_agent), "execute", _failing_execute):
            result = await brief_analyzer_node(state, store=None)
        assert result.get("phase") == WorkflowPhase.ERROR
        assert "agent LLM failed" in result.get("error", "")
        assert result.get("retry_count") == 1
        assert result.get("current_agent") == "brief_analyzer"

    @pytest.mark.asyncio
    async def test_success_sets_current_agent(self):
        state = {
            "session_id": "test-brief-ok",
            "phase": WorkflowPhase.BRIEFING,
            "retry_count": 0,
        }

        async def _ok_execute(self, state, store):
            return {"brief_content": {"brand_name": "ACME"}}

        with patch.object(type(_brief_agent), "execute", _ok_execute):
            result = await brief_analyzer_node(state, store=None)
        assert result.get("current_agent") == "brief_analyzer"
        assert result.get("brief_content") == {"brand_name": "ACME"}
        # __call__ clears stale errors on success
        assert result.get("error") is None


class TestShootingPlannerCallContract:
    @pytest.mark.asyncio
    async def test_failure_returns_error_state_not_raise(self):
        state = {
            "session_id": "test-sp-err",
            "phase": WorkflowPhase.CREATING,
            "retry_count": 0,
        }
        with patch.object(type(_shooting_agent), "execute", _failing_execute):
            result = await shooting_planner_node(state, store=None)
        assert result.get("phase") == WorkflowPhase.ERROR
        assert "agent LLM failed" in result.get("error", "")
        assert result.get("retry_count") == 1
        assert result.get("current_agent") == "shooting_planner"

    @pytest.mark.asyncio
    async def test_success_sets_current_agent(self):
        state = {
            "session_id": "test-sp-ok",
            "phase": WorkflowPhase.CREATING,
            "retry_count": 0,
        }

        async def _ok_execute(self, state, store):
            return {"shooting_plan": {"scenes": []}}

        with patch.object(type(_shooting_agent), "execute", _ok_execute):
            result = await shooting_planner_node(state, store=None)
        assert result.get("current_agent") == "shooting_planner"
        assert result.get("shooting_plan") == {"scenes": []}
        assert result.get("error") is None
