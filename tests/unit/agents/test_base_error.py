"""Tests for BaseAgent error handling (stateful retry path).

After prd 07-07-remove-handle-agent-error-dead-code, BaseAgent.__call__
no longer raises AgentError on execute() failure. Instead it returns
handle_agent_error(e, state) — a state update dict with phase=ERROR,
error=str, retry_count+1, current_agent — so LangGraph merges it and
downstream routers (should_plan/orchestrator) can read retry_count for
stateful cross-super-step retry.
"""

from backend.agents.base import BaseAgent
from backend.config.models import TaskType
from backend.state.enums import WorkflowPhase


class FailingAgent(BaseAgent):
    task_type = TaskType.ROUTING
    agent_name = "failing_agent"
    prompt_file = ""

    async def execute(self, state, store):
        raise ValueError("Intentional test failure")


class TestBaseAgentErrorState:
    async def test_base_agent_returns_error_state(self):
        """__call__ returns an error state update (not raises) on failure."""
        agent = FailingAgent()
        result = await agent({"session_id": "test", "retry_count": 0}, store=None)

        assert result["phase"] == WorkflowPhase.ERROR
        assert "Intentional test failure" in result["error"]
        assert result["retry_count"] == 1
        assert result["current_agent"] == "failing_agent"

    async def test_base_agent_increments_retry_count(self):
        """Each failure increments retry_count from state."""
        agent = FailingAgent()
        result = await agent({"session_id": "test", "retry_count": 2}, store=None)

        assert result["retry_count"] == 3

    async def test_base_agent_failed_perf_entry(self):
        """A failed call writes a status=failed perf entry (now possible
        because __call__ returns a dict instead of raising)."""
        agent = FailingAgent()
        result = await agent({"retry_count": 0}, store=None)

        assert result["performance_log"][0]["status"] == "failed"
        assert result["performance_log"][0]["agent"] == "failing_agent"
        assert result["performance_log"][0]["retries"] == 1

    async def test_base_agent_clears_stale_error_on_success(self):
        """Successful execution should clear stale error field."""

        class SuccessAgent(BaseAgent):
            task_type = TaskType.ROUTING
            agent_name = "success_agent"
            prompt_file = ""

            async def execute(self, state, store):
                return {"phase": "completed"}

        agent = SuccessAgent()
        state = {"session_id": "test", "error": "stale error"}

        result = await agent(state, store=None)

        assert result.get("error") is None, "Stale error should be cleared"
