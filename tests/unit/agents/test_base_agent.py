"""Unit tests for BaseAgent class."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.agents.base import BaseAgent
from backend.config.models import TaskType


class TestBaseAgent:
    """Tests for BaseAgent core functionality."""

    def test_core_base_agent_import_compatibility(self):
        """Legacy import path should still expose the canonical BaseAgent."""
        from backend.core.base_agent import BaseAgent as CoreBaseAgent

        assert CoreBaseAgent is BaseAgent

    def test_task_type_attribute(self):
        """Agent has task_type defined."""

        class DummyAgent(BaseAgent):
            task_type = TaskType.WRITING
            agent_name = "dummy"
            prompt_file = "dummy.yaml"

            async def execute(self, state, store):
                return {}

        agent = DummyAgent()
        assert agent.task_type == TaskType.WRITING

    def test_agent_name_attribute(self):
        """Agent has name defined."""

        class DummyAgent(BaseAgent):
            task_type = TaskType.WRITING
            agent_name = "test_agent"
            prompt_file = ""

            async def execute(self, state, store):
                return {}

        agent = DummyAgent()
        assert agent.agent_name == "test_agent"

    def test_load_prompt_existing_file(self, tmp_path):
        """Load prompt from existing YAML file."""
        # Create the expected directory structure under backend/config/prompts
        prompts_dir = (
            Path(__file__).resolve().parent.parent.parent.parent / "backend" / "config" / "prompts"
        )
        prompt_file = prompts_dir / "_test_prompt.yaml"
        prompt_file.write_text(
            'system: "You are a test agent."\nuser_template: "Process this: {topic}"\n'
        )

        class DummyAgent(BaseAgent):
            task_type = TaskType.WRITING
            agent_name = "dummy"
            prompt_file = "_test_prompt.yaml"

            async def execute(self, state, store):
                return {}

        agent = DummyAgent()
        try:
            template = agent._load_prompt()
            assert template["system"] == "You are a test agent."
            assert template["user_template"] == "Process this: {topic}"
        finally:
            prompt_file.unlink(missing_ok=True)

    def test_load_prompt_missing_file(self):
        """Return empty dict when prompt file missing."""

        class DummyAgent(BaseAgent):
            task_type = TaskType.WRITING
            agent_name = "dummy"
            prompt_file = "nonexistent.yaml"

            async def execute(self, state, store):
                return {}

        agent = DummyAgent()
        template = agent._load_prompt()
        assert template == {"system": "", "user_template": ""}

    def test_load_prompt_empty_file_attr(self):
        """Return empty dict when prompt_file is empty."""

        class DummyAgent(BaseAgent):
            task_type = TaskType.WRITING
            agent_name = "dummy"
            prompt_file = ""

            async def execute(self, state, store):
                return {}

        agent = DummyAgent()
        template = agent._load_prompt()
        assert template == {"system": "", "user_template": ""}

    def test_parse_json_response_with_code_block(self):
        """Parse JSON from code block."""

        class DummyAgent(BaseAgent):
            task_type = TaskType.WRITING
            agent_name = "dummy"
            prompt_file = ""

            async def execute(self, state, store):
                return {}

        agent = DummyAgent()
        content = """```json
{"key": "value", "number": 42}
```"""
        result = agent._parse_json_response(content)
        assert result == {"key": "value", "number": 42}

    def test_parse_json_response_without_code_block(self):
        """Parse raw JSON string."""

        class DummyAgent(BaseAgent):
            task_type = TaskType.WRITING
            agent_name = "dummy"
            prompt_file = ""

            async def execute(self, state, store):
                return {}

        agent = DummyAgent()
        content = '{"key": "value", "number": 42}'
        result = agent._parse_json_response(content)
        assert result == {"key": "value", "number": 42}

    def test_parse_json_response_invalid_json(self):
        """Return raw_content on invalid JSON."""

        class DummyAgent(BaseAgent):
            task_type = TaskType.WRITING
            agent_name = "dummy"
            prompt_file = ""

            async def execute(self, state, store):
                return {}

        agent = DummyAgent()
        content = "This is not JSON"
        result = agent._parse_json_response(content)
        assert result == {"raw_content": "This is not JSON"}

    def test_parse_json_response_nested_code_block(self):
        """Parse JSON from nested code block markers."""

        class DummyAgent(BaseAgent):
            task_type = TaskType.WRITING
            agent_name = "dummy"
            prompt_file = ""

            async def execute(self, state, store):
                return {}

        agent = DummyAgent()
        content = """Some text before
```
{"data": [1, 2, 3]}
```
Some text after"""
        result = agent._parse_json_response(content)
        assert result == {"data": [1, 2, 3]}

    @pytest.mark.asyncio
    async def test_recall_memory(self):
        """Recall items from memory store."""

        class DummyAgent(BaseAgent):
            task_type = TaskType.WRITING
            agent_name = "dummy"
            prompt_file = ""

            async def execute(self, state, store):
                return {}

        agent = DummyAgent()
        mock_store = AsyncMock()
        mock_item = MagicMock()
        mock_item.value = {"insight": "Test insight"}
        mock_store.asearch = AsyncMock(return_value=[mock_item])

        result = await agent._recall_memory(
            mock_store,
            account_id="test",
            query="test query",
            namespace="performance_insights",
            limit=5,
        )

        assert len(result) == 1
        assert result[0] == {"insight": "Test insight"}

    @pytest.mark.asyncio
    async def test_call_wraps_execute(self):
        """__call__ wraps execute and adds current_agent."""

        class DummyAgent(BaseAgent):
            task_type = TaskType.WRITING
            agent_name = "test_agent"
            prompt_file = ""

            async def execute(self, state, store):
                return {"phase": "done"}

        agent = DummyAgent()
        mock_state = {"phase": "idle"}
        mock_store = AsyncMock()

        result = await agent(mock_state, store=mock_store)

        assert result["phase"] == "done"
        assert result["current_agent"] == "test_agent"

    @pytest.mark.asyncio
    async def test_call_handles_exception(self):
        """__call__ propagates exceptions as AgentError."""
        from backend.core.error_handling import AgentError

        class DummyAgent(BaseAgent):
            task_type = TaskType.WRITING
            agent_name = "failing_agent"
            prompt_file = ""

            async def execute(self, state, store):
                raise ValueError("Test error")

        agent = DummyAgent()
        mock_state = {"retry_count": 0}
        mock_store = AsyncMock()

        with pytest.raises(AgentError) as exc_info:
            await agent(mock_state, store=mock_store)

        assert "failing_agent" in str(exc_info.value)
        assert "Test error" in str(exc_info.value)

    def test_model_property_returns_model(self):
        """model property returns configured LLM."""

        class DummyAgent(BaseAgent):
            task_type = TaskType.WRITING
            agent_name = "dummy"
            prompt_file = ""

            async def execute(self, state, store):
                return {}

        with patch("backend.agents.base.get_model") as mock_get_model:
            mock_model = MagicMock()
            mock_get_model.return_value = mock_model

            agent = DummyAgent()
            model = agent.model

            mock_get_model.assert_called_once_with("writing")
            assert model == mock_model

    def test_prompt_template_property(self):
        """prompt_template property loads template once."""

        class DummyAgent(BaseAgent):
            task_type = TaskType.WRITING
            agent_name = "dummy"
            prompt_file = ""

            async def execute(self, state, store):
                return {}

        agent = DummyAgent()
        # First access
        template1 = agent.prompt_template
        # Second access (cached)
        template2 = agent.prompt_template

        assert template1 == template2
        assert agent._prompt_template is not None
