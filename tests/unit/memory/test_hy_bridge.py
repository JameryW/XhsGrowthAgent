"""Unit tests for the hy-memory bridge (backend.memory.hy).

契约（与实现同一条纪律）：
1. 默认 no-op —— enabled=False 时所有读写立即返回空，不碰 SDK。
2. 永不炸调用方 —— SDK 缺失 / 端点异常 / 结构异常全部降级为空结果 +
   可观测的错误痕迹。
3. SDK 懒加载 —— hy_memory 只在启用且真正调用时才 import；测试用
   sys.modules 注入假 SDK，不依赖真实安装。
"""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from backend.context.models import RetrievalMode
from backend.memory.hy.bridge import HyMemoryBridge, get_hy_memory_bridge, reset_hy_memory_bridge
from backend.memory.hy.recall import format_hy_section, hy_namespace, recall_hy_memory
from backend.memory.hy.settings import HyMemorySettings


def _enabled_settings(**overrides: Any) -> HyMemorySettings:
    base: dict[str, Any] = {
        "enabled": True,
        "mode": "pro",
        "llm_model": "deepseek-chat",
        "llm_api_key": "sk-llm",
        "llm_base_url": "https://api.deepseek.com",
        "embedder_model": "text-embedding-v3",
        "embedder_api_key": "sk-emb",
        "embedder_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "embedding_dims": 1024,
        "data_dir": "/tmp/hy-memory-test",
        "default_scene": "chat",
        "source": "xhs_growth",
        "default_limit": 5,
    }
    base.update(overrides)
    return HyMemorySettings(**base)


class FakeHyClient:
    """Records calls and returns canned SDK-shaped results."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []
        self.search_result: Any = {"memories": {"normal": []}}
        self.add_result: dict[str, Any] = {"success": True, "memory_id": "m1"}
        self.search_raises: BaseException | None = None
        self.add_raises: BaseException | None = None
        self.closed = False

    @classmethod
    def from_config(cls, config_dict: dict[str, Any], mode: str | None = None) -> FakeHyClient:
        client = cls()
        client.calls.append(("from_config", (config_dict,), {"mode": mode}))
        return client

    async def async_search(self, query: str, **kwargs: Any) -> Any:
        self.calls.append(("async_search", (query,), kwargs))
        if self.search_raises is not None:
            raise self.search_raises
        return self.search_result

    async def async_add(self, data: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("async_add", (data,), kwargs))
        if self.add_raises is not None:
            raise self.add_raises
        return self.add_result

    async def async_list_memories(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("async_list_memories", (), kwargs))
        if getattr(self, "_list_shape", None) is not None:
            return self._list_shape
        # 真实 SDK 2.0.1 形状（探针实测）：vdb 是 dict，memories 在其内。
        return {
            "vdb": {
                "memories": [{"id": "m1", "content": "stored"}],
                "total": 1,
                "limit": 50,
                "offset": 0,
            }
        }

    async def async_delete(self, memory_id: str) -> dict[str, Any]:
        self.calls.append(("async_delete", (memory_id,), {}))
        return {"success": True}

    async def async_get_metrics(self, minutes: int = 5) -> dict[str, Any]:
        self.calls.append(("async_get_metrics", (), {"minutes": minutes}))
        return {"requests": 7}

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def fake_sdk(monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    """Inject a fake ``hy_memory`` module; returns the module (client via
    ``module.HyMemoryClient.last_instance``)."""
    module = types.ModuleType("hy_memory")

    class _Client(FakeHyClient):
        last_instance: FakeHyClient | None = None

        @classmethod
        def from_config(cls, config_dict: dict[str, Any], mode: str | None = None) -> _Client:
            client = super().from_config(config_dict, mode)
            cls.last_instance = client
            return client

    module.HyMemoryClient = _Client  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "hy_memory", module)
    return module


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_hy_memory_bridge()
    yield
    reset_hy_memory_bridge()


async def _built_client(bridge: HyMemoryBridge, fake_sdk: types.ModuleType) -> FakeHyClient:
    """Force lazy client construction, then return the fake instance.

    The bridge builds its SDK client on first use, so tests that need to
    preset canned results (search_result / *_raises) must build first.
    """
    await bridge.recall("warmup", account_id="a1")
    return fake_sdk.HyMemoryClient.last_instance  # type: ignore[attr-defined]


class TestDisabledNoOp:
    """enabled=False：整个集成是零成本 no-op。"""

    @pytest.mark.asyncio
    async def test_recall_returns_empty(self):
        bridge = HyMemoryBridge(HyMemorySettings(enabled=False))
        assert await bridge.recall("q", account_id="a1") == []

    @pytest.mark.asyncio
    async def test_remember_returns_none(self):
        bridge = HyMemoryBridge(HyMemorySettings(enabled=False))
        assert await bridge.remember("text", account_id="a1") is None

    @pytest.mark.asyncio
    async def test_list_forget_metrics_return_empty(self):
        bridge = HyMemoryBridge(HyMemorySettings(enabled=False))
        assert await bridge.list_memories(account_id="a1") == []
        assert await bridge.forget("m1") is False
        assert await bridge.metrics() == {}

    @pytest.mark.asyncio
    async def test_recall_hy_memory_is_empty_mode(self):
        bridge = HyMemoryBridge(HyMemorySettings(enabled=False))
        result = await recall_hy_memory("q", account_id="a1", bridge=bridge)
        assert result.mode is RetrievalMode.EMPTY
        assert result.items == ()

    @pytest.mark.asyncio
    async def test_recall_hy_memory_uses_singleton(self, monkeypatch: pytest.MonkeyPatch):
        # 未显式注入 bridge 时走单例（此处单例默认 disabled）。
        result = await recall_hy_memory("q", account_id="a1")
        assert result.mode is RetrievalMode.EMPTY


class TestEnabledReadWrite:
    """enabled=True + 假 SDK：配置构建、调用委托、结果归一化。"""

    @pytest.mark.asyncio
    async def test_client_built_from_settings(self, fake_sdk: types.ModuleType):
        bridge = HyMemoryBridge(_enabled_settings())
        await bridge.recall("q", account_id="a1", scene="chat")
        client = fake_sdk.HyMemoryClient.last_instance  # type: ignore[attr-defined]
        ((name, (config_dict,), kwargs),) = [c for c in client.calls if c[0] == "from_config"]
        assert name == "from_config"
        assert kwargs["mode"] == "pro"
        assert config_dict["llm"]["model"] == "deepseek-chat"
        assert config_dict["embedder"]["embedding_dims"] == 1024

    @pytest.mark.asyncio
    async def test_data_dir_exported_to_sdk(self, fake_sdk: types.ModuleType, monkeypatch):
        monkeypatch.delenv("MEMORY_DATA_DIR", raising=False)
        bridge = HyMemoryBridge(_enabled_settings(data_dir="/tmp/hy-memory-test"))
        await bridge.recall("q", account_id="a1")
        import os

        assert os.environ["MEMORY_DATA_DIR"] == "/tmp/hy-memory-test"

    @pytest.mark.asyncio
    async def test_recall_normalizes_channels(self, fake_sdk: types.ModuleType):
        bridge = HyMemoryBridge(_enabled_settings())
        client = await _built_client(bridge, fake_sdk)
        client.search_result = {
            "memories": {
                "profile": [{"content": "90后互联网从业者", "score": 0.65}],
                "normal": [{"content": "喜欢科幻电影", "score": 0.87, "layer": "FACT"}],
                "proactive": [],
            }
        }
        items = await bridge.recall("q", account_id="a1", scene="chat", limit=3)
        assert [i["content"] for i in items] == ["90后互联网从业者", "喜欢科幻电影"]
        assert [i["channel"] for i in items] == ["profile", "normal"]
        assert items[1]["score"] == 0.87
        assert items[1]["layer"] == "FACT"

    @pytest.mark.asyncio
    async def test_recall_search_kwargs(self, fake_sdk: types.ModuleType):
        bridge = HyMemoryBridge(_enabled_settings())
        await bridge.recall("q", account_id="acct_1", scene="chat", limit=7)
        client = fake_sdk.HyMemoryClient.last_instance  # type: ignore[attr-defined]
        ((_, (query,), kwargs),) = [c for c in client.calls if c[0] == "async_search"]
        assert query == "q"
        assert kwargs["scene"] == "chat"
        assert kwargs["user_ids"] == ["acct_1"]
        assert kwargs["include_sources"] == ["xhs_growth"]
        assert kwargs["limit"] == 7

    @pytest.mark.asyncio
    async def test_recall_working_scene_facts_experiences(self, fake_sdk: types.ModuleType):
        bridge = HyMemoryBridge(_enabled_settings())
        client = await _built_client(bridge, fake_sdk)
        client.search_result = {
            "facts": [{"content": "导出过 7 日互动数据", "score": 0.8}],
            "experiences": [
                {
                    "content": "先用 creator_stats 再手工核对",
                    "score": 0.6,
                    "task": "周报制作",
                    "search_keys": ["周报", "导出"],
                }
            ],
            "chain_block": {},
        }
        items = await bridge.recall("q", account_id="a1", scene="working")
        assert [i["channel"] for i in items] == ["facts", "experiences"]
        assert items[1]["task"] == "周报制作"
        assert items[1]["search_keys"] == ["周报", "导出"]

    @pytest.mark.asyncio
    async def test_remember_passes_scene_source_workspace(self, fake_sdk: types.ModuleType):
        bridge = HyMemoryBridge(_enabled_settings())
        await _built_client(bridge, fake_sdk)
        result = await bridge.remember(
            "洞察：数字标题完播率高",
            account_id="acct_1",
            scene="working",
            metadata={"kind": "insight"},
        )
        assert result == {"success": True, "memory_id": "m1"}
        client = fake_sdk.HyMemoryClient.last_instance  # type: ignore[attr-defined]
        ((_, (data,), kwargs),) = [c for c in client.calls if c[0] == "async_add"]
        assert data == "洞察：数字标题完播率高"
        assert kwargs["scene"] == "working"
        assert kwargs["user_id"] == "acct_1"
        assert kwargs["source"] == "xhs_growth"
        assert kwargs["workspace_id"] == "xhs/acct_1"
        assert kwargs["metadata"] == {"kind": "insight"}

    @pytest.mark.asyncio
    async def test_remember_accepts_message_trace(self, fake_sdk: types.ModuleType):
        bridge = HyMemoryBridge(_enabled_settings())
        await _built_client(bridge, fake_sdk)
        trace = [
            {"role": "user", "content": "修一下搜索超时"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "c1"}]},
            {"role": "tool", "tool_call_id": "c1", "name": "apply_patch", "content": "ok"},
        ]
        await bridge.remember(trace, account_id="a1", scene="working", branch="fix/x")
        client = fake_sdk.HyMemoryClient.last_instance  # type: ignore[attr-defined]
        ((_, (data,), kwargs),) = [c for c in client.calls if c[0] == "async_add"]
        assert data == trace
        assert kwargs["branch"] == "fix/x"

    @pytest.mark.asyncio
    async def test_list_forget_metrics(self, fake_sdk: types.ModuleType):
        bridge = HyMemoryBridge(_enabled_settings())
        await _built_client(bridge, fake_sdk)
        listed = await bridge.list_memories(account_id="a1")
        assert listed == [{"id": "m1", "content": "stored"}]
        assert await bridge.forget("m1") is True
        assert await bridge.metrics(minutes=30) == {"requests": 7}

    @pytest.mark.asyncio
    async def test_list_memories_vdb_shapes(self, fake_sdk: types.ModuleType):
        """回归：SDK 2.0.1 实测 vdb 为 dict；list 兼容旧形状；其余归空。"""
        bridge = HyMemoryBridge(_enabled_settings())
        client = await _built_client(bridge, fake_sdk)
        expected = [{"id": "m1", "content": "stored"}]

        # 真实形状：vdb 为 dict
        assert await bridge.list_memories(account_id="a1") == expected

        # 兼容形状：vdb 直接是 list
        client._list_shape = {"vdb": list(expected)}
        assert await bridge.list_memories(account_id="a1") == expected

        # 未知形状：vdb 既非 dict 也非 list
        client._list_shape = {"vdb": "unexpected"}
        assert await bridge.list_memories(account_id="a1") == []

    @pytest.mark.asyncio
    async def test_workspace_mapping(self):
        assert HyMemoryBridge.workspace_for("acct_1") == "xhs/acct_1"
        assert HyMemoryBridge.workspace_for("") == "xhs/default"

    @pytest.mark.asyncio
    async def test_health_reports_client_ready(self, fake_sdk: types.ModuleType):
        bridge = HyMemoryBridge(_enabled_settings())
        await bridge.recall("q", account_id="a1")
        health = bridge.health()
        assert health["enabled"] is True
        assert health["client_ready"] is True
        assert "client_error" not in health

    @pytest.mark.asyncio
    async def test_close_closes_client(self, fake_sdk: types.ModuleType):
        bridge = HyMemoryBridge(_enabled_settings())
        client = await _built_client(bridge, fake_sdk)
        await bridge.close()
        assert client.closed is True


class TestDegradation:
    """SDK 缺失 / 调用异常 / 结构异常：永不抛，降级可见。"""

    @pytest.mark.asyncio
    async def test_sdk_missing_degrades(self, monkeypatch: pytest.MonkeyPatch):
        import builtins

        monkeypatch.delitem(sys.modules, "hy_memory", raising=False)
        real_import = builtins.__import__

        def _fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "hy_memory":
                raise ImportError(f"No module named {name!r}")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _fake_import)
        bridge = HyMemoryBridge(_enabled_settings())
        assert await bridge.recall("q", account_id="a1") == []
        assert await bridge.remember("x", account_id="a1") is None
        health = bridge.health()
        assert "client_error" in health and "SDK not installed" in health["client_error"]

        result = await recall_hy_memory("q", account_id="a1", bridge=bridge)
        assert result.mode is RetrievalMode.DEGRADED
        assert "SDK not installed" in result.error

    @pytest.mark.asyncio
    async def test_search_exception_degrades_with_error(self, fake_sdk: types.ModuleType):
        bridge = HyMemoryBridge(_enabled_settings())
        client = await _built_client(bridge, fake_sdk)
        client.search_raises = TimeoutError("endpoint down")
        assert await bridge.recall("q", account_id="a1") == []
        result = await recall_hy_memory("q", account_id="a1", bridge=bridge)
        assert result.mode is RetrievalMode.DEGRADED
        assert "TimeoutError" in result.error

    @pytest.mark.asyncio
    async def test_remember_exception_returns_none(self, fake_sdk: types.ModuleType):
        bridge = HyMemoryBridge(_enabled_settings())
        client = await _built_client(bridge, fake_sdk)
        client.add_raises = RuntimeError("write failed")
        assert await bridge.remember("x", account_id="a1") is None

    @pytest.mark.asyncio
    async def test_weird_search_shape_returns_empty(self, fake_sdk: types.ModuleType):
        bridge = HyMemoryBridge(_enabled_settings())
        client = await _built_client(bridge, fake_sdk)
        client.search_result = {"memories": "not-a-dict", "facts": None}
        assert await bridge.recall("q", account_id="a1") == []
        # 结构异常不是故障：没有错误痕迹，召回面视为 EMPTY。
        result = await recall_hy_memory("q", account_id="a1", bridge=bridge)
        assert result.mode is RetrievalMode.EMPTY

    @pytest.mark.asyncio
    async def test_last_error_cleared_on_success(self, fake_sdk: types.ModuleType):
        bridge = HyMemoryBridge(_enabled_settings())
        client = await _built_client(bridge, fake_sdk)
        client.search_raises = TimeoutError("down")
        await bridge.recall("q", account_id="a1")
        assert "TimeoutError" in bridge.last_error()
        client.search_raises = None
        await bridge.recall("q", account_id="a1")
        assert bridge.last_error() == ""

    @pytest.mark.asyncio
    async def test_cross_event_loop_rebuilds_client(self, fake_sdk: types.ModuleType):
        """pytest-asyncio 每测试一个 loop；bridge 跨 loop 不得抛绑定错误。

        第二个循环跑在独立线程里（asyncio.run 不能嵌套）。
        """
        import asyncio
        import threading

        bridge = HyMemoryBridge(_enabled_settings())
        assert await bridge.recall("q", account_id="a1") == []

        outcome: dict[str, Any] = {}

        def _run_in_thread() -> None:
            outcome["items"] = asyncio.run(bridge.recall("q", account_id="a1"))

        thread = threading.Thread(target=_run_in_thread)
        thread.start()
        thread.join()
        assert outcome["items"] == []


class TestRecallAdapter:
    """recall_hy_memory → RetrievalResult + format_hy_section。"""

    @pytest.mark.asyncio
    async def test_hit_result_shape(self, fake_sdk: types.ModuleType):
        bridge = HyMemoryBridge(_enabled_settings())
        client = await _built_client(bridge, fake_sdk)
        client.search_result = {
            "memories": {"normal": [{"content": "喜欢科幻电影", "score": 0.87}]}
        }
        result = await recall_hy_memory("q", account_id="a1", scene="chat", bridge=bridge)
        assert result.mode is RetrievalMode.HIT
        assert result.namespace == "hy_chat"
        assert result.layer.value == "l4_memory"
        assert result.items[0].body == "喜欢科幻电影"
        assert result.items[0].confidence == 0.87
        assert result.items[0].priority == 87
        assert result.raw_items[0]["content"] == "喜欢科幻电影"

    @pytest.mark.asyncio
    async def test_empty_when_no_hits(self, fake_sdk: types.ModuleType):
        bridge = HyMemoryBridge(_enabled_settings())
        client = await _built_client(bridge, fake_sdk)
        client.search_result = {"memories": {"normal": []}}
        result = await recall_hy_memory("q", account_id="a1", bridge=bridge)
        assert result.mode is RetrievalMode.EMPTY
        assert result.error == ""

    def test_hy_namespace(self):
        assert hy_namespace("chat") == "hy_chat"
        assert hy_namespace("working") == "hy_working"

    def test_format_hy_section_hit(self, fake_sdk: types.ModuleType):
        from backend.context.models import ContextItem, RetrievalResult

        chat = RetrievalResult(
            namespace="hy_chat",
            items=(ContextItem(body="喜欢科幻电影", source="hy_memory:normal"),),
            mode=RetrievalMode.HIT,
        )
        working = RetrievalResult(
            namespace="hy_working",
            items=(ContextItem(body="导出前先核对口径", source="hy_memory:facts"),),
            mode=RetrievalMode.HIT,
        )
        text = format_hy_section([chat, working])
        assert "账号记忆画像（hy-memory）：" in text
        assert "运营经验记忆（hy-memory）：" in text
        assert "- 喜欢科幻电影" in text
        assert "- 导出前先核对口径" in text

    def test_format_hy_section_degraded_is_visible(self):
        from backend.context.models import RetrievalResult

        degraded = RetrievalResult(
            namespace="hy_chat",
            mode=RetrievalMode.DEGRADED,
            error="TimeoutError: endpoint down",
        )
        text = format_hy_section([degraded])
        assert "【hy-memory 降级】" in text
        assert "TimeoutError" in text

    def test_format_hy_section_empty_is_blank(self):
        from backend.context.models import RetrievalResult

        assert format_hy_section([RetrievalResult(namespace="hy_chat")]) == ""


class TestSettings:
    def test_defaults(self):
        s = HyMemorySettings()
        assert s.enabled is False
        assert s.mode == "lite"
        assert s.default_scene == "chat"
        assert s.source == "xhs_growth"
        assert s.default_limit == 5

    def test_env_prefix(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("HYMEMORY_ENABLED", "true")
        monkeypatch.setenv("HYMEMORY_MODE", "pro")
        monkeypatch.setenv("HYMEMORY_EMBEDDER_MODEL", "text-embedding-v3")
        s = HyMemorySettings()
        assert s.enabled is True
        assert s.mode == "pro"
        assert s.embedder_model == "text-embedding-v3"

    def test_aggregated_into_global_settings(self):
        from backend.config.settings import Settings

        settings = Settings()
        assert isinstance(settings.hy_memory, HyMemorySettings)
        assert settings.hy_memory.enabled is False  # 默认关闭


class TestSingleton:
    def test_get_and_reset(self):
        bridge = get_hy_memory_bridge(HyMemorySettings(enabled=True))
        assert get_hy_memory_bridge() is bridge
        reset_hy_memory_bridge()
        assert get_hy_memory_bridge() is not bridge
