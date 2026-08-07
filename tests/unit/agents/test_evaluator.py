"""Unit tests for EvaluatorAgent (RQGM agent-as-a-judge panel)."""

# ruff: noqa: E501, UP031  — long JSON test fixtures + %-format avoids {}/f-string clash

import asyncio
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from backend.agents import evaluator as evaluator_module
from backend.agents.evaluator import EvaluatorAgent
from backend.db.evaluator_config import EvaluatorWeights, PromptEpoch
from backend.state.enums import ContentStatus
from backend.state.schema import WorkflowPhase


class TestEvaluatorAgent:
    """Tests for EvaluatorAgent creation-quality evaluation."""

    @pytest.fixture
    def agent(self):
        return EvaluatorAgent()

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
            "phase": WorkflowPhase.REVIEWING,
            "content_plan": {
                "selected_topic": "婴儿车推荐",
                "content_angle": "通勤场景",
                "target_audience": "都市宝妈",
                "content_type": "note",
            },
            "copy_content": {
                "selected_title": "通勤带娃神器",
                "body_text": "这款婴儿车轻便...",
                "hashtags": ["#婴儿车", "#通勤"],
                "cta": "点击购买",
                "tone": "friendly",
            },
            "visual_plan": {
                "cover_prompt": "婴儿车通勤场景",
                "image_count": 3,
                "image_prompts": ["图1", "图2", "图3"],
                "layout_style": "grid",
                "color_palette": ["#FFFFFF", "#F5F5F5"],
            },
        }

    def _full_panel_response(self, scores: dict[str, float], blocking: str | None = None) -> str:
        """Build a full 10-dimension LLM JSON response string (incl. altruism)."""
        dims = []
        for name in [
            "copywriting",
            "visual",
            "compliance",
            "reach",
            "audience",
            "ai_taste",
            "image_quality",
            "commercial_tone",
            "altruism",
            "bias_check",
        ]:
            extra = ', "bias_severity": 10' if name == "bias_check" else ""
            dims.append(
                '{"dimension": "%s", "score": %s, "rationale": "r", "issues": [], "is_blocking": %s%s}'
                % (
                    name,
                    scores.get(name, 80.0),
                    "true" if name == blocking else "false",
                    extra,
                )
            )
        return (
            '{"overall_score": 80, "dimensions": [%s], "decision": "approved", "revision_hints": [], "bias_warning": "", "summary": "ok"}'
            % ",".join(dims)
        )

    def test_agent_attributes(self, agent):
        assert agent.agent_name == "evaluator"
        assert agent.prompt_file == "evaluator.yaml"
        assert agent.task_type.value == "evaluation"

    @pytest.mark.asyncio
    async def test_execute_returns_evaluation_result(self, agent, mock_state, mock_store):
        mock_response = MagicMock()
        mock_response.content = self._full_panel_response(
            {
                "copywriting": 85,
                "visual": 80,
                "compliance": 90,
                "reach": 75,
                "audience": 80,
                "bias_check": 90,
            }
        )
        with patch.object(type(agent), "model", new_callable=PropertyMock) as m:
            model = MagicMock()
            model.ainvoke = AsyncMock(return_value=mock_response)
            m.return_value = model
            result = await agent.execute(mock_state, store=mock_store)

        assert "evaluation_result" in result
        ev = result["evaluation_result"]
        assert ev["decision"] == ContentStatus.APPROVED
        assert ev["overall_score"] >= 70
        assert len(ev["dimensions"]) == 10
        assert any(d["dimension"] == "altruism" for d in ev["dimensions"])
        # High altruism (default 80) → no forced 利他性 hints
        assert not any("利他性" in h for h in ev["revision_hints"])

    async def test_execute_timeout_returns_unscored_degraded_result(
        self, agent, mock_state, mock_store
    ):
        """LLM timeout → explicit degraded result without a fake pass score."""
        with patch.object(type(agent), "model", new_callable=PropertyMock) as m:
            model = MagicMock()
            model.ainvoke = AsyncMock(side_effect=TimeoutError("llm slow"))
            m.return_value = model
            result = await agent.execute(mock_state, store=mock_store)

        ev = result["evaluation_result"]
        assert ev["decision"] is None
        assert ev["overall_score"] is None
        assert ev["degraded"] is True
        assert "未完成" in ev["summary"]

    @pytest.mark.asyncio
    async def test_low_score_needs_revision(self, agent, mock_state, mock_store):
        mock_response = MagicMock()
        mock_response.content = self._full_panel_response(
            {
                "copywriting": 50,
                "visual": 55,
                "compliance": 80,
                "reach": 40,
                "audience": 50,
                "bias_check": 80,
            }
        )
        with patch.object(type(agent), "model", new_callable=PropertyMock) as m:
            model = MagicMock()
            model.ainvoke = AsyncMock(return_value=mock_response)
            m.return_value = model
            result = await agent.execute(mock_state, store=mock_store)

        ev = result["evaluation_result"]
        assert ev["decision"] == ContentStatus.NEEDS_REVISION
        assert len(ev["revision_hints"]) > 0

    @pytest.mark.asyncio
    async def test_compliance_blocking_rejects(self, agent, mock_state, mock_store):
        """compliance is_blocking=true → rejected regardless of overall score."""
        mock_response = MagicMock()
        # Add an issue to compliance so hints are generated from it
        raw = self._full_panel_response(
            {
                "copywriting": 90,
                "visual": 90,
                "compliance": 40,
                "reach": 90,
                "audience": 90,
                "bias_check": 90,
            },
            blocking="compliance",
        )
        raw = raw.replace(
            '"is_blocking": true',
            '"is_blocking": true, "issues": ["含医疗绝对化用语"]',
            1,
        )
        mock_response.content = raw
        with patch.object(type(agent), "model", new_callable=PropertyMock) as m:
            model = MagicMock()
            model.ainvoke = AsyncMock(return_value=mock_response)
            m.return_value = model
            result = await agent.execute(mock_state, store=mock_store)

        ev = result["evaluation_result"]
        assert ev["decision"] == ContentStatus.REJECTED
        assert any("compliance" in h for h in ev["revision_hints"])

    @pytest.mark.asyncio
    async def test_bias_detection_sets_warning(self, agent, mock_state, mock_store):
        """Low bias_check score triggers bias_warning + overall penalty."""
        mock_response = MagicMock()
        raw = self._full_panel_response(
            {
                "copywriting": 85,
                "visual": 85,
                "compliance": 85,
                "reach": 85,
                "audience": 85,
                "bias_check": 40,
            }
        )
        # inject a bias issue
        raw = raw.replace(
            '"dimension": "bias_check", "score": 40, "rationale": "r", "issues": []',
            '"dimension": "bias_check", "score": 40, "rationale": "r", "issues": ["copywriting 维度对 AI 套路化表达过度宽容"]',
        )
        mock_response.content = raw
        with patch.object(type(agent), "model", new_callable=PropertyMock) as m:
            model = MagicMock()
            model.ainvoke = AsyncMock(return_value=mock_response)
            m.return_value = model
            result = await agent.execute(mock_state, store=mock_store)

        ev = result["evaluation_result"]
        assert ev["bias_warning"]  # non-empty
        assert "过度宽容" in ev["bias_warning"]

    @pytest.mark.asyncio
    async def test_empty_content_degrades_to_pass(self, agent, mock_store):
        """No copy/visual → degrade to pass (don't block empty flow)."""
        state = {"account_id": "a", "niche": "母婴", "phase": WorkflowPhase.REVIEWING}
        result = await agent.execute(state, store=mock_store)
        ev = result["evaluation_result"]
        assert ev["decision"] == ContentStatus.APPROVED
        assert ev["overall_score"] == 100.0

    @pytest.mark.asyncio
    async def test_missing_dimensions_are_unavailable(self, agent, mock_state, mock_store):
        """LLM returning only some dimensions never receives a neutral 70."""
        mock_response = MagicMock()
        # Only return 2 dimensions
        mock_response.content = (
            '{"overall_score": 80, "dimensions": ['
            '{"dimension": "copywriting", "score": 80, "rationale": "r", "issues": [], "is_blocking": false},'
            '{"dimension": "visual", "score": 80, "rationale": "r", "issues": [], "is_blocking": false}'
            '], "decision": "approved", "revision_hints": [], "bias_warning": "", "summary": "ok"}'
        )
        with patch.object(type(agent), "model", new_callable=PropertyMock) as m:
            model = MagicMock()
            model.ainvoke = AsyncMock(return_value=mock_response)
            m.return_value = model
            result = await agent.execute(mock_state, store=mock_store)

        dims = result["evaluation_result"]["dimensions"]
        assert len(dims) == 10
        names = {d["dimension"] for d in dims}
        assert names == {
            "copywriting",
            "visual",
            "compliance",
            "reach",
            "audience",
            "ai_taste",
            "image_quality",
            "commercial_tone",
            "altruism",
            "bias_check",
        }
        missing = {
            d["dimension"]: d for d in dims if d["dimension"] not in {"copywriting", "visual"}
        }
        assert all(d["available"] is False and d["score"] is None for d in missing.values())
        assert result["evaluation_result"]["status"] == "partial"
        assert result["evaluation_result"]["overall_score"] is None

    @pytest.mark.asyncio
    async def test_decision_ignores_llm_self_reported_decision(self, agent, mock_state, mock_store):
        """Decision is computed by rules, not trusted from LLM (verifiable metric)."""
        mock_response = MagicMock()
        # LLM says "approved" but scores are all low → rules override to needs_revision
        mock_response.content = self._full_panel_response(
            {
                "copywriting": 40,
                "visual": 40,
                "compliance": 40,
                "reach": 40,
                "audience": 40,
                "bias_check": 80,
            }
        )
        with patch.object(type(agent), "model", new_callable=PropertyMock) as m:
            model = MagicMock()
            model.ainvoke = AsyncMock(return_value=mock_response)
            m.return_value = model
            result = await agent.execute(mock_state, store=mock_store)

        ev = result["evaluation_result"]
        assert ev["decision"] != ContentStatus.APPROVED

    @pytest.mark.asyncio
    async def test_recall_memory_called_for_audience(self, agent, mock_state, mock_store):
        mock_item = MagicMock()
        mock_item.value = {"preference": "宝妈偏好真实测评"}
        mock_store.asearch = AsyncMock(return_value=[mock_item])

        mock_response = MagicMock()
        mock_response.content = self._full_panel_response(
            {
                "copywriting": 80,
                "visual": 80,
                "compliance": 80,
                "reach": 80,
                "audience": 80,
                "bias_check": 80,
            }
        )
        with patch.object(type(agent), "model", new_callable=PropertyMock) as m:
            model = MagicMock()
            model.ainvoke = AsyncMock(return_value=mock_response)
            m.return_value = model
            await agent.execute(mock_state, store=mock_store)

        mock_store.asearch.assert_called()

    def test_compute_overall_weighted(self, agent):
        from backend.agents.evaluator import _REQUIRED_DIMENSIONS

        dims = []
        for name in _REQUIRED_DIMENSIONS:
            score = 100.0 if name != "bias_check" else 100.0
            dims.append({"dimension": name, "score": score, "is_blocking": False})
        overall = agent._compute_overall(dims)
        # all 100, no bias penalty → 100
        assert overall == 100.0

    def test_compute_overall_bias_penalty(self, agent):
        from backend.agents.evaluator import _REQUIRED_DIMENSIONS

        dims = [
            {"dimension": name, "score": 100.0, "is_blocking": False}
            for name in _REQUIRED_DIMENSIONS
        ]
        # high bias_severity (检测到明显偏倚) triggers overall penalty
        for d in dims:
            if d["dimension"] == "bias_check":
                d["bias_severity"] = 80.0  # >= penalty threshold (60)
        overall = agent._compute_overall(dims)
        # 100 weighted minus penalty
        assert overall < 100.0

    def test_compute_overall_no_penalty_when_bias_severity_low(self, agent):
        from backend.agents.evaluator import _REQUIRED_DIMENSIONS

        dims = [
            {"dimension": name, "score": 100.0, "is_blocking": False}
            for name in _REQUIRED_DIMENSIONS
        ]
        for d in dims:
            if d["dimension"] == "bias_check":
                d["bias_severity"] = 30.0  # below threshold → no penalty
                d["score"] = 40.0  # score 不再驱动 penalty，低 score 不应触发
        overall = agent._compute_overall(dims)
        assert overall == 100.0

    def test_build_result_bias_severity_explicit_wins(self, agent):
        """LLM-provided bias_severity is preserved and drives the penalty."""
        from backend.agents.evaluator import _REQUIRED_DIMENSIONS

        raw_dims = [
            {"dimension": name, "score": 100.0, "is_blocking": False}
            for name in _REQUIRED_DIMENSIONS
        ]
        for d in raw_dims:
            if d["dimension"] == "bias_check":
                d["score"] = 90.0  # high score alone would NOT trigger penalty
                d["bias_severity"] = 80.0  # high severity SHOULD trigger
        result = agent._build_evaluation_result({"dimensions": raw_dims})
        bias = next(d for d in result["dimensions"] if d["dimension"] == "bias_check")
        assert bias["bias_severity"] == 80.0
        assert result["overall_score"] < 100.0  # penalty applied via severity

    def test_build_result_bias_severity_falls_back_to_score(self, agent):
        """Old LLM output without bias_severity falls back to 100 - score."""
        from backend.agents.evaluator import _REQUIRED_DIMENSIONS

        raw_dims = [
            {"dimension": name, "score": 100.0, "is_blocking": False}
            for name in _REQUIRED_DIMENSIONS
        ]
        for d in raw_dims:
            if d["dimension"] == "bias_check":
                d["score"] = 30.0  # low score → high severity (100-30=70) → penalty
        result = agent._build_evaluation_result({"dimensions": raw_dims})
        bias = next(d for d in result["dimensions"] if d["dimension"] == "bias_check")
        assert bias["bias_severity"] == 70.0  # 100 - 30
        assert result["overall_score"] < 100.0

    def test_build_system_prompt_injects_weights_and_epoch(self, agent):
        """_build_system_prompt replaces {weights_block}/{thresholds}/{bias_severity_note}
        from DB weights + active epoch — prompt no longer hardcodes them."""
        from backend.db.evaluator_config import EvaluatorWeights

        # Custom weights + strict epoch
        agent._weights = EvaluatorWeights()
        agent._weights.dimension_weights["copywriting"] = 0.40
        agent._weights.pass_threshold = 75.0
        agent._weights.reject_threshold = 55.0
        agent._bias_severity = "strict"

        state = {"niche": "美食"}
        prompt = agent._build_system_prompt(state, extra_context="audience-pref")

        # weights block injected with the custom weight
        assert "copywriting 0.40" in prompt
        # thresholds injected (not hardcoded 70/50)
        assert ">= 75" in prompt  # pass threshold line
        assert "55 <= overall_score" in prompt  # reject threshold in needs_revision line
        assert "< 55" in prompt  # reject threshold in rejected line
        # bias severity note injected
        assert "本 epoch 加严" in prompt
        # niche still injected (system template has {account_niche})
        assert "美食" in prompt
        # placeholders fully consumed
        assert "{weights_block}" not in prompt
        assert "{pass_threshold}" not in prompt
        assert "{bias_severity_note}" not in prompt

    def test_build_system_prompt_default_weights_when_unset(self, agent):
        """Fresh agent (defaults) → prompt shows default weights, no placeholders."""
        state = {"niche": "母婴"}
        prompt = agent._build_system_prompt(state)
        assert "copywriting 0.18" in prompt  # default (incl. altruism rebalance)
        assert "altruism 0.09" in prompt
        assert "{weights_block}" not in prompt
        assert "{bias_severity_note}" not in prompt  # standard note (may be empty-ish)


class TestEvaluatorGatherConcurrency:
    """Two-layer gather: _resolve_weights (load_weights + get_active_epoch) and
    the top-level execute gather (_resolve_weights + _recall_memory).

    Uses the call-overlap discriminator (#519 pattern): each mocked coroutine
    records a start/finish timestamp and yields control via ``asyncio.sleep(0)``.
    Under a real ``asyncio.gather`` the two awaitables overlap (one is paused at
    its yield point while the other runs); under serial ``await`` the intervals
    are disjoint. This avoids patching ``asyncio.gather`` globally (the
    shared-asyncio-module leak trap from #515).
    """

    @pytest.fixture
    def agent(self):
        return EvaluatorAgent()

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
            "phase": WorkflowPhase.REVIEWING,
            "content_plan": {
                "selected_topic": "婴儿车推荐",
                "content_angle": "通勤场景",
                "target_audience": "都市宝妈",
                "content_type": "note",
            },
            "copy_content": {
                "selected_title": "通勤带娃神器",
                "body_text": "这款婴儿车轻便...",
                "hashtags": ["#婴儿车", "#通勤"],
                "cta": "点击购买",
                "tone": "friendly",
            },
            "visual_plan": {
                "cover_prompt": "婴儿车通勤场景",
                "image_count": 3,
                "image_prompts": ["图1", "图2", "图3"],
                "layout_style": "grid",
                "color_palette": ["#FFFFFF", "#F5F5F5"],
            },
        }

    def _full_panel_response(self, scores: dict[str, float], blocking: str | None = None) -> str:
        """Build a full 10-dimension LLM JSON response string (incl. altruism)."""
        dims = []
        for name in [
            "copywriting",
            "visual",
            "compliance",
            "reach",
            "audience",
            "ai_taste",
            "image_quality",
            "commercial_tone",
            "altruism",
            "bias_check",
        ]:
            extra = ', "bias_severity": 10' if name == "bias_check" else ""
            dims.append(
                '{"dimension": "%s", "score": %s, "rationale": "r", "issues": [], "is_blocking": %s%s}'
                % (
                    name,
                    scores.get(name, 80.0),
                    "true" if name == blocking else "false",
                    extra,
                )
            )
        return (
            '{"overall_score": 80, "dimensions": [%s], "decision": "approved", "revision_hints": [], "bias_warning": "", "summary": "ok"}'
            % ",".join(dims)
        )

    @staticmethod
    def _overlapping(a: tuple[float, float], b: tuple[float, float]) -> bool:
        """True if the two [start, finish] windows overlap in time."""
        return a[0] <= b[1] and b[0] <= a[1]

    @pytest.mark.asyncio
    async def test_resolve_weights_gathers_load_and_epoch(self, agent):
        """Inside _resolve_weights, load_weights + get_active_epoch run concurrently."""
        windows: dict[str, list[float]] = {}

        async def _tracked_load(_account_id):
            start = asyncio.get_event_loop().time()
            windows["load"] = [start, start]
            await asyncio.sleep(0)  # yield so the sibling gather task can start
            windows["load"][1] = asyncio.get_event_loop().time()
            return EvaluatorWeights()

        async def _tracked_epoch():
            start = asyncio.get_event_loop().time()
            windows["epoch"] = [start, start]
            await asyncio.sleep(0)  # yield so the sibling gather task can start
            windows["epoch"][1] = asyncio.get_event_loop().time()
            return PromptEpoch(0, "standard", "default", True, "")

        with (
            patch.object(
                evaluator_module, "load_weights", new=AsyncMock(side_effect=_tracked_load)
            ),
            patch.object(
                evaluator_module, "get_active_epoch", new=AsyncMock(side_effect=_tracked_epoch)
            ),
        ):
            await agent._resolve_weights("acct")

        assert "load" in windows and "epoch" in windows
        assert self._overlapping(windows["load"], windows["epoch"])  # concurrent, not serial

    @pytest.mark.asyncio
    async def test_resolve_weights_preserves_fallback_on_failure(self, agent):
        """load_weights failure → EvaluatorWeights default; epoch failure → 'standard'.

        Both fallbacks must survive the gather refactor (each closure swallows its
        own exception and returns the fallback).
        """
        with (
            patch.object(
                evaluator_module,
                "load_weights",
                new=AsyncMock(side_effect=RuntimeError("db down")),
            ),
            patch.object(
                evaluator_module,
                "get_active_epoch",
                new=AsyncMock(side_effect=RuntimeError("db down")),
            ),
        ):
            result = await agent._resolve_weights("acct")

        # Returns the default weights and sets side-effects identically to the
        # pre-gather serial implementation.
        assert isinstance(result, EvaluatorWeights)
        assert result is agent._weights
        assert agent._bias_severity == "standard"

    @pytest.mark.asyncio
    async def test_execute_gathers_weights_and_memory_concurrently(
        self, agent, mock_state, mock_store
    ):
        """Top-level execute gathers _resolve_weights + _recall_memory concurrently.

        Drives a full execute() with a mocked LLM panel response, patching
        load_weights/get_active_epoch (inside _resolve_weights) and _recall_memory
        to record overlap windows. Asserts the _resolve_weights fetch overlaps
        _recall_memory — only possible under a top-level gather, not serial awaits.
        """
        windows: dict[str, list[float]] = {}

        # Capture the real unbound methods before patching, so the tracked
        # wrappers can delegate without recursing into themselves.
        real_resolve_weights = EvaluatorAgent._resolve_weights
        real_recall_memory = EvaluatorAgent._recall_memory

        async def _tracked_resolve(self_unused, account_id_unused):
            # _resolve_weights itself: record its start, yield, then let the real
            # method run (which gathers load_weights + get_active_epoch). Patched
            # onto the class, so descriptor binding passes (self, account_id).
            del self_unused, account_id_unused
            start = asyncio.get_event_loop().time()
            windows["resolve"] = [start, start]
            await asyncio.sleep(0)
            try:
                return await real_resolve_weights(agent, "test_account")
            finally:
                windows["resolve"][1] = asyncio.get_event_loop().time()

        async def _tracked_recall(self_unused, *args, **kwargs):
            del self_unused
            start = asyncio.get_event_loop().time()
            windows["recall"] = [start, start]
            await asyncio.sleep(0)
            try:
                return await real_recall_memory(agent, *args, **kwargs)
            finally:
                windows["recall"][1] = asyncio.get_event_loop().time()

        mock_response = MagicMock()
        mock_response.content = self._full_panel_response(
            {
                "copywriting": 85,
                "visual": 80,
                "compliance": 90,
                "reach": 75,
                "audience": 80,
                "bias_check": 90,
            }
        )
        with (
            patch.object(
                evaluator_module, "load_weights", new=AsyncMock(return_value=EvaluatorWeights())
            ),
            patch.object(
                evaluator_module,
                "get_active_epoch",
                new=AsyncMock(return_value=PromptEpoch(0, "standard", "default", True, "")),
            ),
            patch.object(EvaluatorAgent, "_resolve_weights", new=_tracked_resolve),
            patch.object(EvaluatorAgent, "_recall_memory", new=_tracked_recall),
            patch.object(type(agent), "model", new_callable=PropertyMock) as m,
        ):
            model = MagicMock()
            model.ainvoke = AsyncMock(return_value=mock_response)
            m.return_value = model
            result = await agent.execute(mock_state, store=mock_store)

        # Sanity: execute completed and produced a real evaluation result.
        assert "evaluation_result" in result
        assert result["evaluation_result"]["decision"] == ContentStatus.APPROVED
        # Concurrency: _resolve_weights and _recall_memory overlapped in time.
        assert "resolve" in windows and "recall" in windows
        assert self._overlapping(windows["resolve"], windows["recall"])
