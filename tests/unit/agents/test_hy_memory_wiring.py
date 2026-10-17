"""hy-memory agent 接线测试 — analyst / content_strategist 的读写增强。

这些用例钉住集成契约：
1. hy 启用时，analyst 并发召回 chat + working 两个场景，命中注入 prompt，
   复盘洞察/策略建议双写 hy working 记忆；
2. hy 禁用时（默认），两个 agent 的行为与集成前逐字一致——不建 client、
   不发 SDK 调用、prompt 无 hy 段；
3. 任一侧 hy 故障都不炸节点（降级可见但不抛）。
"""

from __future__ import annotations

import sys
import types
from typing import Any
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from backend.agents.analyst import AnalystAgent
from backend.agents.content_strategist import ContentStrategistAgent
from backend.memory.hy.bridge import HyMemoryBridge, get_hy_memory_bridge, reset_hy_memory_bridge
from backend.memory.hy.settings import HyMemorySettings
from backend.state.schema import WorkflowPhase


class FakeHyClient:
    """Records SDK calls; canned results settable per test (class-level so
    tests can preset them before the lazy client build)."""

    last_instance: FakeHyClient | None = None
    search_results: dict[str, Any] = {}

    def __init__(self) -> None:
        self.search_calls: list[tuple[str, dict[str, Any]]] = []
        self.add_calls: list[tuple[Any, dict[str, Any]]] = []
        self.closed = False

    @classmethod
    def from_config(cls, config_dict: dict[str, Any], mode: str | None = None) -> FakeHyClient:
        client = cls()
        cls.last_instance = client
        return client

    async def async_search(self, query: str, **kwargs: Any) -> Any:
        self.search_calls.append((query, kwargs))
        scene = kwargs.get("scene", "chat")
        return self.search_results.get(
            scene, {"memories": {"normal": [], "profile": [], "proactive": []}}
        )

    async def async_add(self, data: Any, **kwargs: Any) -> dict[str, Any]:
        self.add_calls.append((data, kwargs))
        return {"success": True, "memory_id": "m-new"}

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def fake_sdk(monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    module = types.ModuleType("hy_memory")
    module.HyMemoryClient = FakeHyClient  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "hy_memory", module)
    FakeHyClient.last_instance = None
    FakeHyClient.search_results = {}
    return module


@pytest.fixture
def enabled_bridge(fake_sdk: types.ModuleType) -> HyMemoryBridge:
    """进程单例 = 启用的 bridge（测试后重置）。"""
    reset_hy_memory_bridge()
    bridge = get_hy_memory_bridge(HyMemorySettings(enabled=True, mode="lite"))
    yield bridge
    reset_hy_memory_bridge()


@pytest.fixture
def disabled_bridge() -> HyMemoryBridge:
    reset_hy_memory_bridge()
    bridge = get_hy_memory_bridge(HyMemorySettings(enabled=False))
    yield bridge
    reset_hy_memory_bridge()


def _analyst_model_response(insights: list[str], recommendations: list[str]) -> MagicMock:
    response = MagicMock()
    response.content = (
        '{"insights": '
        + str(insights).replace("'", '"')
        + ', "recommendations": '
        + str(recommendations).replace("'", '"')
        + "}"
    )
    return response


class TestAnalystHyWiring:
    @pytest.fixture
    def agent(self):
        return AnalystAgent()

    @pytest.fixture
    def mock_store(self):
        store = AsyncMock()
        store.asearch = AsyncMock(return_value=[])
        store.aput = AsyncMock()
        return store

    @pytest.fixture
    def mock_state(self):
        return {
            "account_id": "test_account",
            "niche": "母婴",
            "phase": WorkflowPhase.PUBLISHING,
            "publish_result": {"post_id": "123", "views": 1000, "engagement_rate": 0.05},
        }

    @pytest.mark.asyncio
    async def test_recall_both_scenes(self, agent, mock_state, mock_store, enabled_bridge):
        """hy 启用：chat + working 两场景都召回，user_ids 带账号。"""
        with patch.object(type(agent), "model", new_callable=PropertyMock) as model_prop:
            model = MagicMock()
            model.ainvoke = AsyncMock(return_value=_analyst_model_response([], []))
            model_prop.return_value = model
            await agent.execute(mock_state, store=mock_store)

        client = FakeHyClient.last_instance
        assert client is not None
        scenes = [kw["scene"] for _, kw in client.search_calls]
        assert scenes == ["chat", "working"]
        for _, kw in client.search_calls:
            assert kw["user_ids"] == ["test_account"]
            assert kw["include_sources"] == ["xhs_growth"]
        queries = [q for q, _ in client.search_calls]
        assert any("母婴" in q for q in queries)

    @pytest.mark.asyncio
    async def test_hits_injected_into_prompt(self, agent, mock_state, mock_store, enabled_bridge):
        """命中注入 user_msg；capture 模型输入验证。"""
        FakeHyClient.search_results = {
            "chat": {"memories": {"normal": [{"content": "受众偏爱教程干货", "score": 0.9}]}},
            "working": {"facts": [{"content": "周二发布互动高", "score": 0.8}]},
        }
        captured_messages: list[Any] = []

        async def _ainvoke(messages, **kwargs):
            captured_messages.append(messages)
            return _analyst_model_response([], [])

        with patch.object(type(agent), "model", new_callable=PropertyMock) as model_prop:
            model = MagicMock()
            model.ainvoke = _ainvoke
            model_prop.return_value = model
            await agent.execute(mock_state, store=mock_store)

        user_msg = captured_messages[0][1].content
        assert "受众偏爱教程干货" in user_msg
        assert "周二发布互动高" in user_msg
        assert "账号记忆画像（hy-memory）" in user_msg
        assert "运营经验记忆（hy-memory）" in user_msg

    @pytest.mark.asyncio
    async def test_insights_written_back(self, agent, mock_state, mock_store, enabled_bridge):
        """洞察/建议双写 hy working 记忆（带 metadata）。"""
        with patch.object(type(agent), "model", new_callable=PropertyMock) as model_prop:
            model = MagicMock()
            model.ainvoke = AsyncMock(
                return_value=_analyst_model_response(["数字标题完播率高"], ["增加教程内容比例"])
            )
            model_prop.return_value = model
            await agent.execute(mock_state, store=mock_store)

        client = FakeHyClient.last_instance
        assert client is not None
        assert len(client.add_calls) == 2
        scenes = {kw["scene"] for _, kw in client.add_calls}
        assert scenes == {"working"}
        kinds = sorted(kw["metadata"]["kind"] for _, kw in client.add_calls)
        assert kinds == ["insight", "strategy_note"]
        for data, kw in client.add_calls:
            assert kw["user_id"] == "test_account"
            assert kw["source"] == "xhs_growth"
            assert kw["workspace_id"] == "xhs/test_account"
            assert "母婴" in data
        # 帖子 id 进 insight 的 metadata
        insight_meta = [
            kw["metadata"] for _, kw in client.add_calls if kw["metadata"]["kind"] == "insight"
        ]
        assert insight_meta[0]["post_id"] == "123"

    @pytest.mark.asyncio
    async def test_disabled_no_sdk_calls(
        self, agent, mock_state, mock_store, disabled_bridge, fake_sdk
    ):
        """hy 禁用（默认）：零 SDK 调用，行为与集成前一致。"""
        with patch.object(type(agent), "model", new_callable=PropertyMock) as model_prop:
            model = MagicMock()
            model.ainvoke = AsyncMock(return_value=_analyst_model_response(["洞察A"], ["建议B"]))
            model_prop.return_value = model
            result = await agent.execute(mock_state, store=mock_store)

        assert FakeHyClient.last_instance is None  # client 从未构建
        assert result["analytics"]["insights"] == ["洞察A"]
        # 既有记忆写入不受影响
        mock_store.aput.assert_called()

    @pytest.mark.asyncio
    async def test_hy_failure_does_not_break_node(
        self, agent, mock_state, mock_store, enabled_bridge
    ):
        """SDK 调用抛错：节点照常完成，降级仅可见于日志。"""

        class BoomClient(FakeHyClient):
            async def async_search(self, query: str, **kwargs: Any) -> Any:
                raise TimeoutError("hy down")

        module = sys.modules["hy_memory"]
        original = module.HyMemoryClient
        module.HyMemoryClient = BoomClient
        try:
            with patch.object(type(agent), "model", new_callable=PropertyMock) as model_prop:
                model = MagicMock()
                model.ainvoke = AsyncMock(return_value=_analyst_model_response(["洞察A"], []))
                model_prop.return_value = model
                result = await agent.execute(mock_state, store=mock_store)
        finally:
            module.HyMemoryClient = original

        assert result["analytics"]["insights"] == ["洞察A"]
        assert result.get("error") is None


class TestContentStrategistHyWiring:
    @pytest.fixture
    def agent(self):
        return ContentStrategistAgent()

    @pytest.fixture
    def mock_store(self):
        store = AsyncMock()
        store.asearch = AsyncMock(return_value=[])
        store.aput = AsyncMock()
        return store

    @pytest.fixture
    def mock_state(self):
        return {
            "account_id": "test_account",
            "niche": "母婴",
            "trend_data": {"trending_topics": ["辅食添加指南"]},
        }

    @pytest.mark.asyncio
    async def test_hy_profile_injected_into_prompt(
        self, agent, mock_state, mock_store, enabled_bridge
    ):
        """hy chat 命中注入 strategist 的 L4 记忆段。"""
        FakeHyClient.search_results = {
            "chat": {
                "memories": {
                    "normal": [{"content": "受众偏爱辅食教程", "score": 0.88}],
                    "profile": [],
                    "proactive": [],
                }
            }
        }
        captured: list[Any] = []

        async def _ainvoke(messages, **kwargs):
            captured.append(messages)
            return MagicMock(content='{"selected_topic": "辅食添加指南"}')

        from backend.agents.content_strategist import _RippleCall

        with (
            patch.object(type(agent), "model", new_callable=PropertyMock) as model_prop,
            patch.object(
                type(agent),
                "_ripple_predict",
                AsyncMock(return_value=_RippleCall(reason="unavailable")),
            ),
            patch.object(
                type(agent),
                "_ripple_validate_pmf",
                AsyncMock(return_value=_RippleCall(reason="unavailable")),
            ),
            patch.object(type(agent), "_score_trend_topics", AsyncMock(return_value="")),
        ):
            model = MagicMock()
            model.ainvoke = _ainvoke
            model_prop.return_value = model
            await agent.execute(mock_state, store=mock_store)

        system = captured[0][0].content
        assert "受众偏爱辅食教程" in system
        assert "账号记忆画像（hy-memory）" in system

    @pytest.mark.asyncio
    async def test_disabled_prompt_unchanged(
        self, agent, mock_state, mock_store, disabled_bridge, fake_sdk
    ):
        """hy 禁用：prompt 无 hy 段，不建 client。"""
        from backend.agents.content_strategist import _RippleCall

        captured: list[Any] = []

        async def _ainvoke(messages, **kwargs):
            captured.append(messages)
            return MagicMock(content='{"selected_topic": "辅食添加指南"}')

        with (
            patch.object(type(agent), "model", new_callable=PropertyMock) as model_prop,
            patch.object(
                type(agent),
                "_ripple_predict",
                AsyncMock(return_value=_RippleCall(reason="unavailable")),
            ),
            patch.object(
                type(agent),
                "_ripple_validate_pmf",
                AsyncMock(return_value=_RippleCall(reason="unavailable")),
            ),
            patch.object(type(agent), "_score_trend_topics", AsyncMock(return_value="")),
        ):
            model = MagicMock()
            model.ainvoke = _ainvoke
            model_prop.return_value = model
            await agent.execute(mock_state, store=mock_store)

        assert FakeHyClient.last_instance is None
        assert "hy-memory" not in captured[0][0].content
