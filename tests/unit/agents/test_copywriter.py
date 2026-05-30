"""Unit tests for CopywriterAgent."""

from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from backend.agents.copywriter import CopywriterAgent
from backend.state.schema import WorkflowPhase


class TestCopywriterAgent:
    """Tests for CopywriterAgent content generation."""

    @pytest.fixture
    def agent(self):
        """Create copywriter instance."""
        return CopywriterAgent()

    @pytest.fixture
    def mock_store(self):
        """Mock LangGraph store."""
        store = AsyncMock()
        store.asearch = AsyncMock(return_value=[])
        return store

    @pytest.fixture
    def mock_state(self):
        """Mock state with content plan."""
        return {
            "account_id": "test_account",
            "phase": WorkflowPhase.PLANNING,
            "content_plan": {
                "selected_topic": "美食探店",
                "content_angle": "攻略分享",
                "target_audience": "美食爱好者",
                "content_type": "图文笔记",
            },
        }

    @pytest.mark.asyncio
    async def test_execute_returns_copy_content(self, agent, mock_state, mock_store):
        """Execute returns copy_content in result."""
        mock_response = MagicMock()
        mock_response.content = """```json
{
  "title_candidates": ["🔥 美食探店攻略", "超实用美食分享"],
  "body_text": "今天给大家分享...",
  "hashtags": ["#美食", "#探店"],
  "hook_type": "情感钩子"
}
```"""

        with patch.object(type(agent), "model", new_callable=PropertyMock) as mock_model_prop:
            mock_model = MagicMock()
            mock_model.ainvoke = AsyncMock(return_value=mock_response)
            mock_model_prop.return_value = mock_model

            _result = await agent.execute(mock_state, store=mock_store)

        assert "copy_content" in result
        assert result["phase"] == WorkflowPhase.CREATING
        assert len(result["copy_content"]["title_candidates"]) == 2

    @pytest.mark.asyncio
    async def test_execute_recalls_past_content(self, agent, mock_state, mock_store):
        """Execute recalls similar past content."""
        mock_item = MagicMock()
        mock_item.value = {"title": "历史爆款", "engagement_rate": 0.1}
        mock_store.asearch = AsyncMock(return_value=[mock_item])

        mock_response = MagicMock()
        mock_response.content = '{"title_candidates": [], "body_text": ""}'

        with patch.object(type(agent), "model", new_callable=PropertyMock) as mock_model_prop:
            mock_model = MagicMock()
            mock_model.ainvoke = AsyncMock(return_value=mock_response)
            mock_model_prop.return_value = mock_model

            _result = await agent.execute(mock_state, store=mock_store)

        # Memory was recalled
        assert mock_store.asearch.called

    @pytest.mark.asyncio
    async def test_execute_recalls_audience_prefs(self, agent, mock_state, mock_store):
        """Execute recalls audience preferences."""
        mock_pref = MagicMock()
        mock_pref.value = {"preference": "喜欢实用内容"}
        mock_store.asearch = AsyncMock(return_value=[mock_pref])

        mock_response = MagicMock()
        mock_response.content = '{"title_candidates": [], "body_text": ""}'

        with patch.object(type(agent), "model", new_callable=PropertyMock) as mock_model_prop:
            mock_model = MagicMock()
            mock_model.ainvoke = AsyncMock(return_value=mock_response)
            mock_model_prop.return_value = mock_model

            _result = await agent.execute(mock_state, store=mock_store)

        # Multiple recall calls
        assert mock_store.asearch.call_count >= 2

    @pytest.mark.asyncio
    async def test_execute_handles_empty_plan(self, agent, mock_store):
        """Execute handles empty content plan."""
        mock_state = {"account_id": "test", "content_plan": {}}

        mock_response = MagicMock()
        mock_response.content = '{"title_candidates": ["默认标题"], "body_text": ""}'

        with patch.object(type(agent), "model", new_callable=PropertyMock) as mock_model_prop:
            mock_model = MagicMock()
            mock_model.ainvoke = AsyncMock(return_value=mock_response)
            mock_model_prop.return_value = mock_model

            _result = await agent.execute(mock_state, store=mock_store)

        assert "copy_content" in result

    @pytest.mark.asyncio
    async def test_execute_handles_invalid_json(self, agent, mock_state, mock_store):
        """Execute handles invalid LLM response."""
        mock_response = MagicMock()
        mock_response.content = "Not valid JSON"

        with patch.object(type(agent), "model", new_callable=PropertyMock) as mock_model_prop:
            mock_model = MagicMock()
            mock_model.ainvoke = AsyncMock(return_value=mock_response)
            mock_model_prop.return_value = mock_model

            _result = await agent.execute(mock_state, store=mock_store)

        # Should still return copy_content with raw_content
        assert "copy_content" in result
        assert result["copy_content"].get("raw_content") == "Not valid JSON"

    @pytest.mark.asyncio
    async def test_execute_with_key_points(self, agent, mock_store):
        """Execute includes key points in generation."""
        mock_state = {
            "account_id": "test",
            "content_plan": {
                "selected_topic": "美食",
                "key_points": ["要点1", "要点2"],
            },
        }

        mock_response = MagicMock()
        mock_response.content = '{"title_candidates": [], "body_text": ""}'

        with patch.object(type(agent), "model", new_callable=PropertyMock) as mock_model_prop:
            mock_model = MagicMock()
            mock_model.ainvoke = AsyncMock(return_value=mock_response)
            mock_model_prop.return_value = mock_model

            _result = await agent.execute(mock_state, store=mock_store)

        assert result["phase"] == WorkflowPhase.CREATING

    def test_agent_attributes(self, agent):
        """Verify agent class attributes."""
        assert agent.agent_name == "copywriter"
        assert agent.prompt_file == "copywriter.yaml"