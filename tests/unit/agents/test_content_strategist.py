"""Unit tests for ContentStrategistAgent."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.agents.content_strategist import ContentStrategistAgent
from backend.services.ripple_service import RippleTimeoutError
from backend.state.schema import WorkflowPhase


class TestContentStrategistAgent:
    """Tests for ContentStrategistAgent strategy generation."""

    @pytest.fixture
    def agent(self):
        """Create content strategist instance."""
        return ContentStrategistAgent()

    @pytest.fixture
    def mock_store(self):
        """Mock LangGraph store."""
        store = AsyncMock()
        store.asearch = AsyncMock(return_value=[])
        return store

    @pytest.fixture
    def mock_state(self):
        """Standard mock state with trend_data."""
        return {
            "account_id": "test_account",
            "niche": "母婴",
            "phase": WorkflowPhase.SCOUTING,
            "trend_data": {
                "trending_topics": ["美食探店"],
                "recommendations": ["健康饮食"],
            },
        }

    @pytest.mark.asyncio
    async def test_execute_returns_content_plan(self, agent, mock_state, mock_store):
        """Execute returns content_plan in result."""
        mock_response = MagicMock()
        mock_response.content = """```json
{
  "selected_topic": "美食探店",
  "content_angle": "探店攻略",
  "target_audience": "美食爱好者",
  "content_type": "图文笔记"
}
```"""

        mock_model = MagicMock()
        mock_model.ainvoke = AsyncMock(return_value=mock_response)
        agent._model = mock_model

        scorer = AsyncMock()
        scorer.ainvoke = AsyncMock(return_value={"heat_score": 50})

        with (
            patch(
                "backend.tools.ripple.integration.predict_spread", new_callable=AsyncMock
            ) as mock_pred,
            patch(
                "backend.tools.ripple.integration.validate_pmf", new_callable=AsyncMock
            ) as mock_pmf,
            patch("backend.tools.analysis.topic_scorer.topic_scorer", scorer),
        ):
            mock_pred.return_value = {"ripple_prediction": None}
            mock_pmf.return_value = {"ripple_pmf": None}

            result = await agent.execute(mock_state, store=mock_store)

        assert "content_plan" in result
        assert result["phase"] == WorkflowPhase.PLANNING
        assert result["content_plan"]["selected_topic"] == "美食探店"

    @pytest.mark.asyncio
    async def test_execute_recalls_memory(self, agent, mock_state, mock_store):
        """Execute recalls historical performance insights."""
        mock_item = MagicMock()
        mock_item.value = {"insight": "美食话题互动率高"}
        mock_store.asearch = AsyncMock(return_value=[mock_item])

        mock_response = MagicMock()
        mock_response.content = '{"selected_topic": "test"}'

        mock_model = MagicMock()
        mock_model.ainvoke = AsyncMock(return_value=mock_response)
        agent._model = mock_model

        scorer = AsyncMock()
        scorer.ainvoke = AsyncMock(return_value={"heat_score": 50})

        with (
            patch(
                "backend.tools.ripple.integration.predict_spread", new_callable=AsyncMock
            ) as mock_pred,
            patch(
                "backend.tools.ripple.integration.validate_pmf", new_callable=AsyncMock
            ) as mock_pmf,
            patch("backend.tools.analysis.topic_scorer.topic_scorer", scorer),
        ):
            mock_pred.return_value = {"ripple_prediction": None}
            mock_pmf.return_value = {"ripple_pmf": None}

            await agent.execute(mock_state, store=mock_store)

        mock_store.asearch.assert_called()

    @pytest.mark.asyncio
    async def test_ripple_predict_returns_prediction(self, agent, mock_state, mock_store):
        """_ripple_predict returns prediction when topic exists."""
        mock_response = MagicMock()
        mock_response.content = '{"selected_topic": "美食探店"}'

        mock_model = MagicMock()
        mock_model.ainvoke = AsyncMock(return_value=mock_response)
        agent._model = mock_model

        scorer = AsyncMock()
        scorer.ainvoke = AsyncMock(return_value={"heat_score": 50})

        with (
            patch(
                "backend.tools.ripple.integration.predict_spread", new_callable=AsyncMock
            ) as mock_predict,
            patch(
                "backend.tools.ripple.integration.validate_pmf", new_callable=AsyncMock
            ) as mock_pmf,
            patch("backend.tools.analysis.topic_scorer.topic_scorer", scorer),
        ):
            mock_predict.return_value = {
                "ripple_job_id": "test-job",
                "ripple_prediction": {"estimated_reach": 5000, "viral_probability": 0.3},
            }
            mock_pmf.return_value = {"ripple_pmf": None}

            result = await agent.execute(mock_state, store=mock_store)

        assert result["content_plan"]["ripple_prediction"]["estimated_reach"] == 5000
        assert result["content_plan"]["ripple_prediction"]["ripple_job_id"] == "test-job"

    @pytest.mark.asyncio
    async def test_ripple_predict_skipped_on_error(self, agent, mock_state, mock_store):
        """Ripple prediction gracefully skipped on error — uses fallback data."""
        mock_response = MagicMock()
        mock_response.content = '{"selected_topic": "美食探店"}'

        mock_model = MagicMock()
        mock_model.ainvoke = AsyncMock(return_value=mock_response)
        agent._model = mock_model

        scorer = AsyncMock()
        scorer.ainvoke = AsyncMock(return_value={"heat_score": 50})

        with (
            patch(
                "backend.tools.ripple.integration.predict_spread", new_callable=AsyncMock
            ) as mock_predict,
            patch(
                "backend.tools.ripple.integration.validate_pmf", new_callable=AsyncMock
            ) as mock_pmf,
            patch("backend.tools.analysis.topic_scorer.topic_scorer", scorer),
        ):
            mock_predict.side_effect = Exception("Ripple unavailable")
            mock_pmf.side_effect = Exception("Ripple unavailable")

            result = await agent.execute(mock_state, store=mock_store)

        # Should have fallback ripple_prediction with zeros
        assert result["content_plan"]["ripple_prediction"]["estimated_reach"] == 0
        assert result["content_plan"]["ripple_prediction"]["viral_probability"] == 0.0
        # Generic error (not timeout) sets ripple_reason to "unreachable"
        assert result.get("ripple_reason") == "unreachable"

    @pytest.mark.asyncio
    async def test_ripple_predict_skipped_no_topic(self, agent, mock_store):
        """Ripple prediction skipped when no topic."""
        mock_state = {"niche": "母婴", "account_id": "test", "trend_data": {}}
        mock_response = MagicMock()
        mock_response.content = '{"selected_topic": ""}'

        mock_model = MagicMock()
        mock_model.ainvoke = AsyncMock(return_value=mock_response)
        agent._model = mock_model

        scorer = AsyncMock()
        scorer.ainvoke = AsyncMock(return_value={"heat_score": 50})

        with (
            patch(
                "backend.tools.ripple.integration.predict_spread", new_callable=AsyncMock
            ) as mock_pred,
            patch(
                "backend.tools.ripple.integration.validate_pmf", new_callable=AsyncMock
            ) as mock_pmf,
            patch("backend.tools.analysis.topic_scorer.topic_scorer", scorer),
        ):
            mock_pred.return_value = {"ripple_prediction": None}
            mock_pmf.return_value = {"ripple_pmf": None}

            result = await agent.execute(mock_state, store=mock_store)

        assert result["content_plan"]["selected_topic"] == ""

    @pytest.mark.asyncio
    async def test_user_topic_skips_drift_guard(self, agent, mock_store):
        """When state['topic'] is set, the user topic is the selection core and
        the candidate-set drift guard is skipped (no retry regen). Previously
        state['topic'] was dead data and the guard pulled the LLM back to the
        trend candidate set."""
        # topic NOT in trend candidates — under old guard this would regen.
        state = {
            "niche": "母婴",
            "account_id": "test_account",
            "phase": WorkflowPhase.SCOUTING,
            "topic": "露营亲子日记",
            "trend_data": {"trending_topics": ["辅食食谱", "早教游戏"]},
        }
        mock_response = MagicMock()
        mock_response.content = '{"selected_topic": "露营亲子日记"}'

        mock_model = MagicMock()
        mock_model.ainvoke = AsyncMock(return_value=mock_response)
        agent._model = mock_model

        scorer = AsyncMock()
        scorer.ainvoke = AsyncMock(return_value={"heat_score": 50})

        with (
            patch(
                "backend.tools.ripple.integration.predict_spread", new_callable=AsyncMock
            ) as mock_pred,
            patch(
                "backend.tools.ripple.integration.validate_pmf", new_callable=AsyncMock
            ) as mock_pmf,
            patch("backend.tools.analysis.topic_scorer.topic_scorer", scorer),
        ):
            mock_pred.return_value = {"ripple_prediction": None}
            mock_pmf.return_value = {"ripple_pmf": None}

            result = await agent.execute(state, store=mock_store)

        # user_topic set → guard skipped → model invoked exactly once (no retry).
        assert mock_model.ainvoke.await_count == 1
        # user_topic injected into the human prompt of that single call.
        sent_user_msg = mock_model.ainvoke.await_args.args[0][1].content
        assert "露营亲子日记" in sent_user_msg
        # selected_topic honored the user topic, not forced into candidates.
        assert result["content_plan"]["selected_topic"] == "露营亲子日记"
        assert "topic_revised" not in result["content_plan"]

    @pytest.mark.asyncio
    async def test_no_user_topic_keeps_drift_guard(self, agent, mock_store):
        """Without state['topic'], drift guard still fires on a candidate miss."""
        state = {
            "niche": "母婴",
            "account_id": "test_account",
            "phase": WorkflowPhase.SCOUTING,
            "trend_data": {"trending_topics": ["辅食食谱"]},
        }
        first = MagicMock()
        first.content = '{"selected_topic": "不在候选里的自创话题"}'
        retry = MagicMock()
        retry.content = '{"selected_topic": "辅食食谱"}'
        mock_model = MagicMock()
        mock_model.ainvoke = AsyncMock(side_effect=[first, retry])
        agent._model = mock_model

        scorer = AsyncMock()
        scorer.ainvoke = AsyncMock(return_value={"heat_score": 50})

        with (
            patch(
                "backend.tools.ripple.integration.predict_spread", new_callable=AsyncMock
            ) as mock_pred,
            patch(
                "backend.tools.ripple.integration.validate_pmf", new_callable=AsyncMock
            ) as mock_pmf,
            patch("backend.tools.analysis.topic_scorer.topic_scorer", scorer),
        ):
            mock_pred.return_value = {"ripple_prediction": None}
            mock_pmf.return_value = {"ripple_pmf": None}

            result = await agent.execute(state, store=mock_store)

        # no user topic + miss → retry regen fired (2 invocations).
        assert mock_model.ainvoke.await_count == 2
        assert result["content_plan"]["selected_topic"] == "辅食食谱"
        assert result["content_plan"].get("topic_revised") is True

    @pytest.mark.asyncio
    async def test_execute_recalls_memory_concurrently(self, agent, mock_state, mock_store):
        """The 4 memory recalls run via one asyncio.gather (not 4 serial awaits).

        Non-vacuous: patches ``asyncio.gather`` in the content_strategist
        module and asserts exactly one gather call receives 4 awaitables (the
        memory recalls). The module also gathers the 2 Ripple calls later in
        ``execute`` — those have 2 awaitables and are filtered out. If the
        recalls are reverted to 4 serial ``await`` assignments, no gather has
        4 awaitables and this test fails.
        """
        import asyncio as _asyncio

        mock_response = MagicMock()
        mock_response.content = '{"selected_topic": "美食探店"}'

        real_gather = _asyncio.gather
        gather_calls: list[tuple[tuple, dict]] = []

        async def _fake_gather(*awaitables, **kwargs):
            gather_calls.append((awaitables, kwargs))
            # Drive the coroutines the way real gather would, preserving order.
            return list(await real_gather(*awaitables, **kwargs))

        scorer = AsyncMock()
        scorer.ainvoke = AsyncMock(return_value={"heat_score": 50})

        with (
            patch(
                "backend.tools.ripple.integration.predict_spread", new_callable=AsyncMock
            ) as mock_pred,
            patch(
                "backend.tools.ripple.integration.validate_pmf", new_callable=AsyncMock
            ) as mock_pmf,
            patch("backend.tools.analysis.topic_scorer.topic_scorer", scorer),
            patch("backend.agents.content_strategist.asyncio.gather", new=_fake_gather),
        ):
            mock_pred.return_value = {"ripple_prediction": None}
            mock_pmf.return_value = {"ripple_pmf": None}

            mock_model = MagicMock()
            mock_model.ainvoke = AsyncMock(return_value=mock_response)
            agent._model = mock_model

            await agent.execute(mock_state, store=mock_store)

        # The module also gathers the 2 Ripple calls (predict + pmf) later in
        # execute; the memory-recall gather is the one with 4 awaitables. This
        # stays non-vacuous: revert to 4 serial awaits → no gather has 4 args.
        memory_gather = [c for c, _ in gather_calls if len(c) == 4]
        assert len(memory_gather) == 1, "memory recalls must be gathered in one call"
        assert len(memory_gather[0]) == 4, "expected exactly 4 concurrent recalls"

    def test_agent_attributes(self, agent):
        """Verify agent class attributes."""
        assert agent.agent_name == "content_strategist"
        assert agent.prompt_file == "content_strategist.yaml"

    @pytest.mark.asyncio
    async def test_ripple_timeout_saves_job_id(self, agent, mock_state, mock_store):
        """Ripple 超时（DomainOutcome timeout）时保存 job_id 并取消任务

        驱动真实链路：服务抛 RippleTimeoutError → integration 把它翻译成携带
        job_id 的 DomainOutcome → Gateway 记为 ErrorKind.DOMAIN → agent 读到
        job_id 并取消。替换 integration 函数本身会绕过那次翻译，于是测到的是
        虚构而不是行为 —— 而"job_id 在穿越 Gateway 后仍在"正是这一步要守的东西。
        """
        mock_response = MagicMock()
        mock_response.content = '{"selected_topic": "美食探店"}'

        mock_model = MagicMock()
        mock_model.ainvoke = AsyncMock(return_value=mock_response)
        agent._model = mock_model

        scorer = AsyncMock()
        scorer.ainvoke = AsyncMock(return_value={"heat_score": 50})

        service = MagicMock()
        service.is_healthy.return_value = True
        service.predict_spread = AsyncMock(side_effect=RippleTimeoutError("job-timeout-123", 900.0))
        service.validate_pmf = AsyncMock(return_value={"ripple_pmf": {"pmf_score": 0.5}})

        with (
            patch("backend.tools.ripple.integration.RippleService") as mock_cls,
            patch.object(agent, "_ripple_cancel", new_callable=AsyncMock) as mock_cancel,
            patch("backend.tools.analysis.topic_scorer.topic_scorer", scorer),
        ):
            mock_cls.get_instance.return_value = service
            result = await agent.execute(mock_state, store=mock_store)

        # job_id 应被保存
        assert result.get("ripple_job_id") == "job-timeout-123"
        assert result.get("ripple_reason") == "timeout"
        # cancel 应被调用
        mock_cancel.assert_awaited_once_with("job-timeout-123")

    @pytest.mark.asyncio
    async def test_ripple_cancel_called_on_timeout(self, agent):
        """_ripple_cancel 调用 RippleService.cancel_simulation"""
        mock_service = MagicMock()
        mock_service.cancel_simulation = AsyncMock(
            return_value={"cancelled": True, "job_id": "job-cancel-456", "status": "cancelled"}
        )

        with patch("backend.services.ripple_service.RippleService") as mock_cls:
            mock_cls.get_instance.return_value = mock_service
            result = await agent._ripple_cancel("job-cancel-456")

        assert result["cancelled"] is True
        mock_service.cancel_simulation.assert_called_once_with("job-cancel-456")

    @pytest.mark.asyncio
    async def test_ripple_cancel_handles_empty_job_id(self, agent):
        """_ripple_cancel 对空 job_id 返回 None"""
        result = await agent._ripple_cancel("")
        assert result is None

    @pytest.mark.asyncio
    async def test_ripple_cancel_handles_exception(self, agent):
        """_ripple_cancel 对异常做优雅降级"""
        mock_service = MagicMock()
        mock_service.cancel_simulation = AsyncMock(side_effect=Exception("Connection refused"))

        with patch("backend.services.ripple_service.RippleService") as mock_cls:
            mock_cls.get_instance.return_value = mock_service
            result = await agent._ripple_cancel("job-err")

        assert result is None


class TestContentStrategistContextPipeline:
    """S4-3 迁移契约：performance_insights recall 走 S2 管线、prompt 走
    compile_prompt、降级可观测、L4 记忆段逐字等价（D3'）。"""

    @pytest.fixture
    def agent(self):
        return ContentStrategistAgent()

    @pytest.fixture
    def mock_store(self):
        store = AsyncMock()
        store.asearch = AsyncMock(return_value=[])
        return store

    @pytest.fixture
    def mock_state(self):
        return {
            "account_id": "test_account",
            "niche": "母婴",
            "trend_data": {"trending_topics": ["美食探店"]},
        }

    def _ripple_patches(self):
        return (
            patch("backend.tools.ripple.integration.predict_spread", new_callable=AsyncMock),
            patch("backend.tools.ripple.integration.validate_pmf", new_callable=AsyncMock),
        )

    def _mock_scorer(self):
        scorer = AsyncMock()
        scorer.ainvoke = AsyncMock(return_value={"heat_score": 50})
        return scorer

    @pytest.mark.asyncio
    async def test_recall_uses_context_pipeline_ns_and_query(self, agent, mock_store, mock_state):
        """S2 pipeline recall: same ns/query/limit as the old _recall_memory."""
        mock_response = MagicMock()
        mock_response.content = '{"selected_topic": "美食探店"}'
        mock_model = MagicMock()
        mock_model.ainvoke = AsyncMock(return_value=mock_response)
        agent._model = mock_model

        pred, pmf = self._ripple_patches()
        with (
            pred as mock_pred,
            pmf as mock_pmf,
            patch("backend.tools.analysis.topic_scorer.topic_scorer", self._mock_scorer()),
        ):
            mock_pred.return_value = {"ripple_prediction": None}
            mock_pmf.return_value = {"ripple_pmf": None}
            await agent.execute(mock_state, store=mock_store)

        by_ns = {c.args[0][-1]: c for c in mock_store.asearch.call_args_list}
        assert "performance_insights" in by_ns
        ins = by_ns["performance_insights"]
        assert ins.args[0] == ("accounts", "test_account", "performance_insights")
        assert ins.kwargs.get("query") == "content strategy"
        assert ins.kwargs.get("limit") == 5

    @pytest.mark.asyncio
    async def test_memory_context_l4_format_verbatim(self, agent, mock_store, mock_state):
        """L4 记忆段逐字等价，占位符无残留（{memory_context} 删除、
        {ripple_context} 由 post-render replace 清空）。"""
        mock_item = MagicMock()
        mock_item.value = {"insight": "美食话题互动率高"}
        mock_store.asearch = AsyncMock(return_value=[mock_item])

        captured: dict = {}
        responses = [MagicMock()]
        responses[0].content = '{"selected_topic": "美食探店"}'

        async def _ainvoke(messages, **kwargs):
            captured.setdefault("calls", []).append(messages)
            return responses[len(captured["calls"]) - 1]

        mock_model = MagicMock()
        mock_model.ainvoke = _ainvoke
        agent._model = mock_model

        pred, pmf = self._ripple_patches()
        with (
            pred as mock_pred,
            pmf as mock_pmf,
            patch("backend.tools.analysis.topic_scorer.topic_scorer", self._mock_scorer()),
        ):
            mock_pred.return_value = {"ripple_prediction": None}
            mock_pmf.return_value = {"ripple_pmf": None}
            await agent.execute(mock_state, store=mock_store)

        system = captured["calls"][0][0].content
        assert "\n历史表现洞察：\n- 美食话题互动率高\n" in system
        assert "{memory_context}" not in system
        assert "{ripple_context}" not in system

    def test_yaml_segment_schema(self, agent):
        """YAML 分段 schema：恰好一个 L4 标记，{memory_context} 占位符移除。"""
        system = agent.prompt_template["system"]
        assert system.count("<!-- ctx:") == 1
        assert "<!-- ctx:l4_memory -->" in system
        assert "{memory_context}" not in system
        # {ripple_context} 占位符按 consumer-map 暂保留（post-render replace）
        assert "{ripple_context}" in system

    @pytest.mark.asyncio
    async def test_degraded_recall_drops_memory_section(self, agent, mock_store, mock_state):
        """Store 故障 → 降级而非崩溃：记忆段缺席，节点照常产出 content_plan。"""

        async def _boom(ns, **kwargs):
            raise RuntimeError("store down")

        mock_store.asearch = _boom

        captured: dict = {}
        mock_response = MagicMock()
        mock_response.content = '{"selected_topic": "美食探店"}'

        async def _ainvoke(messages, **kwargs):
            captured.setdefault("calls", []).append(messages)
            return mock_response

        mock_model = MagicMock()
        mock_model.ainvoke = _ainvoke
        agent._model = mock_model

        pred, pmf = self._ripple_patches()
        with (
            pred as mock_pred,
            pmf as mock_pmf,
            patch("backend.tools.analysis.topic_scorer.topic_scorer", self._mock_scorer()),
        ):
            mock_pred.return_value = {"ripple_prediction": None}
            mock_pmf.return_value = {"ripple_pmf": None}
            result = await agent.execute(mock_state, store=mock_store)

        assert "content_plan" in result
        system = captured["calls"][0][0].content
        assert "历史表现洞察" not in system
        assert "{memory_context}" not in system

    @pytest.mark.asyncio
    async def test_drift_retry_prompt_carries_correction_hint(self, agent, mock_store, mock_state):
        """漂移纠偏 retry（双形态之一）：第二次调用 SystemMessage 携带【纠偏】提示，
        且两次调用都经 compile_prompt 编译（L4 标记已消费）。"""
        first = MagicMock()
        first.content = '{"selected_topic": "不在候选里的自创话题"}'
        retry = MagicMock()
        retry.content = '{"selected_topic": "美食探店"}'
        responses = [first, retry]

        captured: dict = {}

        async def _ainvoke(messages, **kwargs):
            captured.setdefault("calls", []).append(messages)
            return responses[len(captured["calls"]) - 1]

        mock_model = MagicMock()
        mock_model.ainvoke = _ainvoke
        agent._model = mock_model

        pred, pmf = self._ripple_patches()
        with (
            pred as mock_pred,
            pmf as mock_pmf,
            patch("backend.tools.analysis.topic_scorer.topic_scorer", self._mock_scorer()),
        ):
            mock_pred.return_value = {"ripple_prediction": None}
            mock_pmf.return_value = {"ripple_pmf": None}
            result = await agent.execute(mock_state, store=mock_store)

        assert len(captured["calls"]) == 2
        assert result["content_plan"].get("topic_revised") is True
        retry_system = captured["calls"][1][0].content
        assert "【纠偏】" in retry_system
        assert "不在候选话题内" in retry_system
        assert "{memory_context}" not in retry_system
