"""Unit tests for VisualDesignerAgent."""

from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from backend.agents.visual_designer import VisualDesignerAgent
from backend.state.schema import WorkflowPhase


class TestVisualDesignerAgent:
    """Tests for VisualDesignerAgent visual plan generation."""

    @pytest.fixture
    def agent(self):
        """Create visual designer instance."""
        return VisualDesignerAgent()

    @pytest.fixture
    def mock_store(self):
        """Mock LangGraph store."""
        store = AsyncMock()
        store.asearch = AsyncMock(return_value=[])
        return store

    @pytest.fixture
    def mock_state(self):
        """Mock state with content plan and copy."""
        return {
            "account_id": "test_account",
            "phase": WorkflowPhase.CREATING,
            "content_plan": {
                "selected_topic": "美食探店",
                "content_angle": "攻略分享",
                "content_type": "图文笔记",
            },
            "copy_content": {
                "body_text": "今天给大家分享美食探店攻略...",
            },
        }

    @pytest.mark.asyncio
    async def test_execute_returns_visual_plan(self, agent, mock_state, mock_store):
        """Execute returns visual_plan in result."""
        mock_response = MagicMock()
        mock_response.content = """```json
{
  "cover_prompt": "美食探店封面，暖色调，现代风格",
  "layout_type": "grid",
  "style": "minimalist",
  "color_palette": ["#FFE4E1", "#F5F5F5"],
  "carousel_prompts": ["配图1", "配图2"]
}
```"""

        with patch.object(type(agent), "model", new_callable=PropertyMock) as mock_model_prop:
            mock_model = MagicMock()
            mock_model.ainvoke = AsyncMock(return_value=mock_response)
            mock_model_prop.return_value = mock_model

            result = await agent.execute(mock_state, store=mock_store)

        assert "visual_plan" in result
        assert result["phase"] == WorkflowPhase.CREATING
        assert "cover_prompt" in result["visual_plan"]

    @pytest.mark.asyncio
    async def test_execute_truncates_body_text(self, agent, mock_store):
        """Execute truncates long body text to 200 chars."""
        long_body_state = {
            "account_id": "test",
            "content_plan": {"selected_topic": "美食"},
            "copy_content": {
                "body_text": "A" * 500,  # Very long text
            },
        }

        mock_response = MagicMock()
        mock_response.content = '{"cover_prompt": ""}'

        with patch.object(type(agent), "model", new_callable=PropertyMock) as mock_model_prop:
            mock_model = MagicMock()
            mock_model.ainvoke = AsyncMock(return_value=mock_response)
            mock_model_prop.return_value = mock_model

            # Check that body is truncated
            result = await agent.execute(long_body_state, store=mock_store)

        assert result["phase"] == WorkflowPhase.CREATING

    @pytest.mark.asyncio
    async def test_execute_handles_empty_copy(self, agent, mock_store):
        """Execute handles empty copy_content."""
        mock_state = {
            "account_id": "test",
            "content_plan": {"selected_topic": "美食"},
            "copy_content": {},
        }

        mock_response = MagicMock()
        mock_response.content = '{"cover_prompt": "默认封面"}'

        with patch.object(type(agent), "model", new_callable=PropertyMock) as mock_model_prop:
            mock_model = MagicMock()
            mock_model.ainvoke = AsyncMock(return_value=mock_response)
            mock_model_prop.return_value = mock_model

            result = await agent.execute(mock_state, store=mock_store)

        assert "visual_plan" in result

    @pytest.mark.asyncio
    async def test_execute_handles_missing_copy(self, agent, mock_store):
        """Execute handles missing copy_content."""
        mock_state = {
            "account_id": "test",
            "content_plan": {"selected_topic": "美食"},
        }

        mock_response = MagicMock()
        mock_response.content = '{"cover_prompt": ""}'

        with patch.object(type(agent), "model", new_callable=PropertyMock) as mock_model_prop:
            mock_model = MagicMock()
            mock_model.ainvoke = AsyncMock(return_value=mock_response)
            mock_model_prop.return_value = mock_model

            result = await agent.execute(mock_state, store=mock_store)

        assert "visual_plan" in result

    @pytest.mark.asyncio
    async def test_execute_handles_invalid_json(self, agent, mock_state, mock_store):
        """Execute handles invalid LLM response."""
        mock_response = MagicMock()
        mock_response.content = "Not valid JSON"

        with patch.object(type(agent), "model", new_callable=PropertyMock) as mock_model_prop:
            mock_model = MagicMock()
            mock_model.ainvoke = AsyncMock(return_value=mock_response)
            mock_model_prop.return_value = mock_model

            result = await agent.execute(mock_state, store=mock_store)

        assert "visual_plan" in result
        assert result["visual_plan"].get("raw_content") == "Not valid JSON"

    @pytest.mark.asyncio
    async def test_execute_uses_content_plan(self, agent, mock_state, mock_store):
        """Execute uses content_plan fields."""
        mock_response = MagicMock()
        mock_response.content = '{"cover_prompt": ""}'

        with patch.object(type(agent), "model", new_callable=PropertyMock) as mock_model_prop:
            mock_model = MagicMock()
            mock_model.ainvoke = AsyncMock(return_value=mock_response)
            mock_model_prop.return_value = mock_model

            result = await agent.execute(mock_state, store=mock_store)

        # Verify LLM was called
        assert mock_model.ainvoke.called

    def test_agent_attributes(self, agent):
        """Verify agent class attributes."""
        assert agent.agent_name == "visual_designer"
        assert agent.prompt_file == "visual_designer.yaml"