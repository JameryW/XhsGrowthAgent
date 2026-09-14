"""Unit tests for CopywriterAgent."""

import asyncio
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
        """The memory recalls run via one asyncio.gather (not serial awaits).

        Non-vacuous: patches ``asyncio.gather`` in the copywriter module and
        asserts it's awaited exactly once with 3 awaitables. If the recalls
        are reverted to serial ``await`` assignments, ``asyncio.gather`` is
        never called with that arity and this test fails.
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

        assert len(gather_calls) >= 1, "memory recalls must be gathered"
        # The memory-recall gather is the one with 3 awaitables (recall_style +
        # recall_materials + _recall_memories batching both pipeline namespaces
        # through recall_namespaces). Other gathers (2-way deposit, the
        # pipeline's internal 2-namespace batch) fire with a different arity —
        # discriminate by content, not by total call count.
        recall_gathers = [c for c in gather_calls if len(c[0]) == 3]
        assert len(recall_gathers) == 1, "expected exactly one 3-awaitable recall gather"
        awaitables, _ = recall_gathers[0]
        assert len(awaitables) == 3, "expected exactly 3 concurrent recall sources"

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

    @pytest.mark.asyncio
    async def test_deposit_material_gathered_concurrently(
        self, agent, mock_state, mock_store, _mock_de_ai
    ):
        """Title + opening material deposits run concurrently (gather), not serially.

        Discriminator: peak in-flight deposit_material calls must reach 2 when
        both selected_title and body_text are present. Serial awaits would peak
        at 1. Also asserts material_id is still surfaced to used_material_ids
        despite the entries being mutated inside the gathered coroutines.
        """
        mock_response = MagicMock()
        mock_response.content = """{
          "selected_title": "标题A",
          "title_candidates": ["标题A"],
          "body_text": "开头正文内容",
          "cta": "",
          "tone": "口语"
        }"""

        in_flight = 0
        peak = 0

        async def _probe(self_cm, entry):
            nonlocal in_flight, peak
            in_flight += 1
            peak = max(peak, in_flight)
            await asyncio.sleep(0)  # yield so the sibling coroutine can start
            entry["material_id"] = "mid_" + entry.get("category", "x")
            in_flight -= 1

        with (
            patch.object(type(agent), "model", new_callable=PropertyMock) as mock_model_prop,
            patch(
                "backend.memory.creative.CreativeMemory.deposit_material",
                new=_probe,
            ),
        ):
            mock_model = MagicMock()
            mock_model.ainvoke = AsyncMock(return_value=mock_response)
            mock_model_prop.return_value = mock_model
            result = await agent.execute(mock_state, store=mock_store)

        assert peak == 2, f"deposits not gathered concurrently (peak={peak})"
        ids = result["copy_content"].get("used_material_ids", [])
        assert ids == ["mid_标题模板", "mid_文案片段"], ids

    @pytest.mark.asyncio
    async def test_deposit_material_single_when_no_body(
        self, agent, mock_state, mock_store, _mock_de_ai
    ):
        """Only title present (no body_text) → single deposit, peak stays 1."""
        mock_response = MagicMock()
        mock_response.content = """{
          "selected_title": "标题A",
          "title_candidates": ["标题A"],
          "body_text": "",
          "cta": "",
          "tone": "口语"
        }"""

        in_flight = 0
        peak = 0

        async def _probe(self_cm, entry):
            nonlocal in_flight, peak
            in_flight += 1
            peak = max(peak, in_flight)
            await asyncio.sleep(0)
            entry["material_id"] = "mid_" + entry.get("category", "x")
            in_flight -= 1

        with (
            patch.object(type(agent), "model", new_callable=PropertyMock) as mock_model_prop,
            patch(
                "backend.memory.creative.CreativeMemory.deposit_material",
                new=_probe,
            ),
        ):
            mock_model = MagicMock()
            mock_model.ainvoke = AsyncMock(return_value=mock_response)
            mock_model_prop.return_value = mock_model
            result = await agent.execute(mock_state, store=mock_store)

        assert peak == 1, f"expected single deposit (peak={peak})"
        ids = result["copy_content"].get("used_material_ids", [])
        assert ids == ["mid_标题模板"], ids

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


class TestCopywriterContextPipeline:
    """S4-2 迁移契约：双 ns recall 走 S2 管线、prompt 走 compile_prompt、
    降级可观测、L4 记忆段逐字等价（D3'）。"""

    @pytest.fixture
    def agent(self):
        return CopywriterAgent()

    @pytest.fixture
    def mock_store(self):
        store = AsyncMock()
        store.asearch = AsyncMock(return_value=[])
        return store

    @pytest.fixture
    def mock_state(self):
        return {
            "account_id": "test_account",
            "content_plan": {
                "selected_topic": "美食探店",
                "content_angle": "攻略分享",
                "target_audience": "美食爱好者",
                "content_type": "图文笔记",
            },
        }

    def _mock_model(self, agent, content: str, captured: dict):
        mock_response = MagicMock()
        mock_response.content = content
        mock_model = MagicMock()

        async def _capture(messages, **kwargs):
            captured["messages"] = messages
            return mock_response

        mock_model.ainvoke = _capture
        agent._model = mock_model

    @pytest.mark.asyncio
    async def test_recall_uses_context_pipeline_ns_and_query(self, agent, mock_store, mock_state):
        """S2 pipeline recall: same ns/query/limit as the two old _recall_memory."""
        self._mock_model(agent, '{"title_candidates": [], "body_text": ""}', {})
        await agent.execute(mock_state, store=mock_store)
        by_ns = {c.args[0][-1]: c for c in mock_store.asearch.call_args_list}
        assert "content_history" in by_ns
        assert "audience_preferences" in by_ns
        hist = by_ns["content_history"]
        assert hist.args[0] == ("accounts", "test_account", "content_history")
        assert hist.kwargs.get("query") == "美食探店"
        assert hist.kwargs.get("limit") == 3
        aud = by_ns["audience_preferences"]
        assert aud.args[0] == ("accounts", "test_account", "audience_preferences")
        assert aud.kwargs.get("query") == "audience preference for 图文笔记"
        assert aud.kwargs.get("limit") == 3

    @pytest.mark.asyncio
    async def test_memory_context_l4_format_verbatim(self, agent, mock_store, mock_state):
        """L4 记忆段逐字等价：多字段 bullet 由 raw_items 格式化，占位符无残留。"""

        async def _asearch(ns, **kwargs):
            if ns[-1] == "content_history":
                item = MagicMock()
                item.value = {"title": "历史爆款", "engagement_rate": 0.1}
                return [item]
            if ns[-1] == "audience_preferences":
                item = MagicMock()
                item.value = {"preference": "喜欢实用内容"}
                return [item]
            return []

        mock_store.asearch = _asearch
        captured: dict = {}
        self._mock_model(agent, '{"title_candidates": [], "body_text": ""}', captured)
        await agent.execute(mock_state, store=mock_store)

        system = captured["messages"][0].content
        assert "\n历史爆款参考：\n- 历史爆款 (互动率: 0.1)\n" in system
        assert "\n受众偏好：\n- 喜欢实用内容\n" in system
        # 占位符必须全部消失（{memory_context} 由分段标记替代）
        assert "{memory_context}" not in system

    def test_yaml_segment_schema(self, agent):
        """YAML 分段 schema：恰好一个 L4 标记，{memory_context} 占位符移除。"""
        system = agent.prompt_template["system"]
        assert system.count("<!-- ctx:") == 1
        assert "<!-- ctx:l4_memory -->" in system
        assert "{memory_context}" not in system

    @pytest.mark.asyncio
    async def test_degraded_recall_drops_memory_section(self, agent, mock_store, mock_state):
        """Store 故障 → 降级而非崩溃：记忆段缺席，节点照常产出 copy_content。"""

        async def _boom(ns, **kwargs):
            raise RuntimeError("store down")

        mock_store.asearch = _boom
        captured: dict = {}
        self._mock_model(agent, '{"title_candidates": [], "body_text": ""}', captured)
        result = await agent.execute(mock_state, store=mock_store)

        assert "copy_content" in result
        system = captured["messages"][0].content
        assert "历史爆款参考" not in system
        assert "受众偏好" not in system
        assert "{memory_context}" not in system

    @pytest.mark.asyncio
    async def test_ripple_context_still_replaced(self, agent, mock_store, mock_state):
        """{ripple_context} 保持 post-render replace（P1b 暂不动），占位符无残留。"""
        mock_state["content_plan"]["ripple_prediction"] = {
            "estimated_reach": 10000,
            "estimated_engagement": 800,
            "viral_probability": 0.42,
        }
        captured: dict = {}
        self._mock_model(agent, '{"title_candidates": [], "body_text": ""}', captured)
        await agent.execute(mock_state, store=mock_store)

        system = captured["messages"][0].content
        assert "Ripple 传播预测数据" in system
        assert "预计触达: 10000" in system
        assert "{ripple_context}" not in system
