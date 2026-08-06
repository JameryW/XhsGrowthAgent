"""Unit tests for CopywriterAgent."""

import logging
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

        with (
            patch.object(type(agent), "model", new_callable=PropertyMock) as mock_model_prop,
            patch(
                "backend.tools.content.de_ai_taste.polish_copy",
                new=AsyncMock(
                    return_value={
                        "selected_title": "🔥 美食探店攻略",
                        "body_text": "今天给大家分享...",
                        "cta": "",
                        "tone": "亲切",
                        "changes": [],
                        "ai_signals_found": [],
                        "polished": False,
                        "method": "llm",
                    }
                ),
            ),
        ):
            mock_model = MagicMock()
            mock_model.ainvoke = AsyncMock(return_value=mock_response)
            mock_model_prop.return_value = mock_model

            result = await agent.execute(mock_state, store=mock_store)

        assert "copy_content" in result
        assert result["phase"] == WorkflowPhase.CREATING
        assert len(result["copy_content"]["title_candidates"]) == 2

    @pytest.fixture
    def _mock_de_ai(self):
        """Avoid real LLM polish during copywriter unit tests."""

        async def _identity(**kwargs):
            return {
                "selected_title": kwargs.get("selected_title") or "",
                "body_text": kwargs.get("body_text") or "",
                "cta": kwargs.get("cta") or "",
                "tone": kwargs.get("tone") or "",
                "changes": [],
                "ai_signals_found": [],
                "polished": False,
                "method": "skip",
            }

        with patch(
            "backend.tools.content.de_ai_taste.polish_copy",
            new=AsyncMock(side_effect=_identity),
        ) as mock:
            yield mock

    @pytest.mark.asyncio
    async def test_execute_recalls_past_content(self, agent, mock_state, mock_store, _mock_de_ai):
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

            await agent.execute(mock_state, store=mock_store)

        # Memory was recalled
        assert mock_store.asearch.called

    @pytest.mark.asyncio
    async def test_execute_recalls_audience_prefs(self, agent, mock_state, mock_store, _mock_de_ai):
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

            await agent.execute(mock_state, store=mock_store)

        # Multiple recall calls
        assert mock_store.asearch.call_count >= 2

    @pytest.mark.asyncio
    async def test_execute_recalls_memory_concurrently(
        self, agent, mock_state, mock_store, _mock_de_ai
    ):
        """The 4 memory recalls run via one asyncio.gather (not 4 serial awaits).

        Non-vacuous: patches ``asyncio.gather`` in the copywriter module and
        asserts it's awaited exactly once with 4 awaitables. If the recalls
        are reverted to 4 serial ``await`` assignments, ``asyncio.gather`` is
        never called and this test fails.
        """
        import asyncio as _asyncio

        mock_response = MagicMock()
        mock_response.content = '{"title_candidates": [], "body_text": ""}'

        real_gather = _asyncio.gather
        gather_calls: list[tuple[tuple, dict]] = []

        async def _fake_gather(*awaitables, **kwargs):
            gather_calls.append((awaitables, kwargs))
            # Drive the coroutines the way real gather would, preserving order.
            return list(await real_gather(*awaitables, **kwargs))

        with (
            patch.object(type(agent), "model", new_callable=PropertyMock) as mock_model_prop,
            patch("backend.agents.copywriter.asyncio.gather", new=_fake_gather),
        ):
            mock_model = MagicMock()
            mock_model.ainvoke = AsyncMock(return_value=mock_response)
            mock_model_prop.return_value = mock_model

            await agent.execute(mock_state, store=mock_store)

        assert len(gather_calls) == 1, "memory recalls must be gathered in one call"
        awaitables, _ = gather_calls[0]
        assert len(awaitables) == 4, "expected exactly 4 concurrent recalls"

    @pytest.mark.asyncio
    async def test_execute_handles_empty_plan(self, agent, mock_store, _mock_de_ai):
        """Execute handles empty content plan."""
        mock_state = {"account_id": "test", "content_plan": {}}

        mock_response = MagicMock()
        mock_response.content = '{"title_candidates": ["默认标题"], "body_text": ""}'

        with patch.object(type(agent), "model", new_callable=PropertyMock) as mock_model_prop:
            mock_model = MagicMock()
            mock_model.ainvoke = AsyncMock(return_value=mock_response)
            mock_model_prop.return_value = mock_model

            result = await agent.execute(mock_state, store=mock_store)

        assert "copy_content" in result

    @pytest.mark.asyncio
    async def test_execute_handles_invalid_json(self, agent, mock_state, mock_store, _mock_de_ai):
        """Execute handles invalid LLM response."""
        mock_response = MagicMock()
        mock_response.content = "Not valid JSON"

        with patch.object(type(agent), "model", new_callable=PropertyMock) as mock_model_prop:
            mock_model = MagicMock()
            mock_model.ainvoke = AsyncMock(return_value=mock_response)
            mock_model_prop.return_value = mock_model

            result = await agent.execute(mock_state, store=mock_store)

        # Should still return copy_content with raw_content
        assert "copy_content" in result
        assert result["copy_content"].get("raw_content") == "Not valid JSON"

    @pytest.mark.asyncio
    async def test_execute_with_key_points(self, agent, mock_store, _mock_de_ai):
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

            result = await agent.execute(mock_state, store=mock_store)

        assert result["phase"] == WorkflowPhase.CREATING

    @pytest.mark.asyncio
    async def test_execute_applies_de_ai_taste_polish(self, agent, mock_state, mock_store):
        """Post-generation polish rewrites body and records de_ai metadata."""
        mock_response = MagicMock()
        mock_response.content = """{
          "selected_title": "在当今社会好物",
          "title_candidates": ["在当今社会好物"],
          "body_text": "综上所述赋能生活",
          "cta": "欢迎在评论区留言交流。",
          "tone": "专业"
        }"""

        with (
            patch.object(type(agent), "model", new_callable=PropertyMock) as mock_model_prop,
            patch(
                "backend.tools.content.de_ai_taste.polish_copy",
                new=AsyncMock(
                    return_value={
                        "selected_title": "用了一周真实感受",
                        "body_text": "自己用下来真的省事",
                        "cta": "评论区聊聊你的用法。",
                        "tone": "口语",
                        "changes": ["去套话"],
                        "ai_signals_found": ["综上所述"],
                        "polished": True,
                        "method": "llm",
                    }
                ),
            ) as mock_polish,
        ):
            mock_model = MagicMock()
            mock_model.ainvoke = AsyncMock(return_value=mock_response)
            mock_model_prop.return_value = mock_model
            result = await agent.execute(mock_state, store=mock_store)

        copy = result["copy_content"]
        assert copy["selected_title"] == "用了一周真实感受"
        assert copy["body_text"] == "自己用下来真的省事"
        assert copy["de_ai_polished"] is True
        assert copy["de_ai_method"] == "llm"
        assert copy["de_ai_changes"] == ["去套话"]
        mock_polish.assert_awaited_once()

    def test_agent_attributes(self, agent):
        """Verify agent class attributes."""
        assert agent.agent_name == "copywriter"
        assert agent.prompt_file == "copywriter.yaml"

    @pytest.mark.asyncio
    async def test_style_variants_retries_on_empty_then_succeeds(self, agent):
        """First LLM call returns empty variants, retry returns valid variants."""
        empty_response = MagicMock()
        empty_response.content = '{"variants": []}'

        valid_response = MagicMock()
        valid_response.content = """{
          "variants": [
            {
              "version_id": "style_a",
              "style_name": "专业测评",
              "title": "测试标题",
              "body": "正文内容",
              "hashtags": ["#标签"],
              "tone": "理性",
              "style_suggestion": "简洁",
              "visual_style": "极简"
            }
          ]
        }"""

        state = {
            "account_id": "test",
            "content_plan": {"selected_topic": "美食"},
            "blogger_notes": [{"title": "参考", "body": "正文"}],
        }

        with patch.object(type(agent), "model", new_callable=PropertyMock) as mock_model_prop:
            mock_model = MagicMock()
            mock_model.ainvoke = AsyncMock(side_effect=[empty_response, valid_response])
            mock_model_prop.return_value = mock_model

            result = await agent._generate_style_variants(
                state,
                {},
                state["blogger_notes"],
                "system prompt",
                "美食",
            )

        assert len(result) == 1
        assert result[0]["style_name"] == "专业测评"
        # ainvoke called twice: first attempt + one retry
        assert mock_model.ainvoke.call_count == 2

    @pytest.mark.asyncio
    async def test_style_variants_empty_after_retry_logs_error(self, agent, caplog):
        """Both LLM calls return empty variants → returns [] and logs error."""
        empty_response = MagicMock()
        empty_response.content = "not json at all"

        state = {
            "account_id": "test",
            "content_plan": {"selected_topic": "美食"},
            "blogger_notes": [{"title": "参考", "body": "正文"}],
        }

        with patch.object(type(agent), "model", new_callable=PropertyMock) as mock_model_prop:
            mock_model = MagicMock()
            mock_model.ainvoke = AsyncMock(return_value=empty_response)
            mock_model_prop.return_value = mock_model

            with caplog.at_level(
                logging.WARNING,
                logger="xhs_growth.agents.copywriter",
            ):
                result = await agent._generate_style_variants(
                    state,
                    {},
                    state["blogger_notes"],
                    "system prompt",
                    "美食",
                )

        assert result == []
        assert mock_model.ainvoke.call_count == 2
        # warning on first attempt + error after retry
        assert any("empty on first attempt" in r.message for r in caplog.records)
        assert any("empty after retry" in r.message for r in caplog.records)
