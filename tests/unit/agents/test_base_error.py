"""Tests for BaseAgent error handling."""

import pytest

from backend.agents.base import BaseAgent
from backend.config.models import TaskType
from backend.core.error_handling import AgentError


class FailingAgent(BaseAgent):
    task_type = TaskType.ROUTING
    agent_name = "failing_agent"
    prompt_file = ""

    async def execute(self, state, store):
        raise ValueError("Intentional test failure")


@pytest.mark.asyncio
async def test_base_agent_propagates_exception():
    """BaseAgent should propagate exceptions, not swallow them."""
    agent = FailingAgent()

    with pytest.raises(AgentError) as exc_info:
        await agent({"session_id": "test"}, store=None)

    assert "Intentional test failure" in str(exc_info.value)


@pytest.mark.asyncio
async def test_base_agent_clears_stale_error_on_success():
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
