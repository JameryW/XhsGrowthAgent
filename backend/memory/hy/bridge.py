"""HyMemoryBridge — hy-memory SDK 的异步门面（默认关闭、优雅降级）。

设计契约（与 backend.memory.store 的 recall_* 同一条纪律）：

1. **默认 no-op**：``enabled=False`` 或未配置端点时，每个方法立即返回
   （``recall`` → ``[]``、``remember`` → ``None``），不建 client、不发请求、
   不 import SDK。
2. **永不炸调用方**：SDK 不在（可选依赖未安装）、client 构建失败、端点超时、
   返回结构异常 —— 全部降级为 warning + 空结果。记忆是增强，不是主链路。
3. **SDK 懒加载**：``hy_memory`` 只在真正启用时才 import，所以
   ``pip install -e .``（无 ``memory-hy`` extra）的部署导入本模块零成本。
4. **账号隔离**：``account_id`` 映射为 SDK 的 ``user_id``，``workspace_id``
   映射为 ``xhs/<account_id>``，``source="xhs_growth"`` 做调用方隔离。

SDK 2.0.1 的真实契约（冒烟验证过）：
- ``HyMemoryClient.from_config({...}, mode=...)`` 建 client；
- ``await client.async_add(data, user_id=..., scene=..., source=...)``
  → ``{"success": True, "scene": ..., "memory_id": ...}``；
- chat 场景 ``await client.async_search(q, user_ids=[...], scene="chat")``
  → ``{"memories": {"profile": [...], "normal": [...], "proactive": [...]}}``；
- working/coding 场景 → ``{"facts": [...], "experiences": [...],
  "chain_block": ...}``；
- ``await client.async_list_memories(user_id=...)`` → ``{"vdb": [...]}``；
- ``await client.async_get_metrics(minutes=...)`` → 指标 dict。
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import TYPE_CHECKING, Any

from backend.memory.hy.settings import HyMemorySettings

if TYPE_CHECKING:
    from hy_memory import HyMemoryClient

logger = logging.getLogger("xhs_growth.memory.hy")


class HyMemoryBridge:
    """hy-memory 的异步门面。进程级单例（见 :func:`get_hy_memory_bridge`）。"""

    def __init__(self, settings: HyMemorySettings | None = None) -> None:
        self._settings = settings or HyMemorySettings()
        # client/lock 按事件循环键控：SDK client（内部 httpx/openai 连接池）
        # 与 asyncio.Lock 都会绑定构建时的事件循环。生产只有一个 loop
        # （uvicorn），测试里 pytest-asyncio 每测试一个 loop —— 跨 loop 复用
        # 会抛 "bound to a different event loop"，故按 loop 分桶。
        self._clients: dict[int, HyMemoryClient] = {}
        self._locks: dict[int, asyncio.Lock] = {}
        self._client_errors: dict[int, str] = {}
        # 每次调用的最后一次错误（同 loop 内）：recall 返回 [] 时调用方
        # （recall_hy_memory）靠它区分"没命中"与"刚发生了故障"。
        self._last_errors: dict[int, str] = {}
        # SDK import 失败原因（实例级缓存：避免每次调用都重试 import 刷日志，
        # 同时不跨 bridge 实例耦合——测试各建各的）。
        self._sdk_error: str | None = None

    # ── 状态 ──

    @property
    def settings(self) -> HyMemorySettings:
        return self._settings

    @property
    def enabled(self) -> bool:
        """配置层开关。注意：enabled=True 但 SDK 缺失/端点不可用时，
        运行时仍然降级（见 :meth:`health`）。"""
        return self._settings.enabled

    def last_error(self) -> str:
        """当前事件循环上最近一次调用的错误摘要（无则空串）。"""
        return self._last_errors.get(id(asyncio.get_running_loop()), "")

    def health(self) -> dict[str, Any]:
        """可观测性快照 —— 供 /status 或日志消费，永远不抛。"""
        s = self._settings
        try:
            loop_id: int | None = id(asyncio.get_running_loop())
        except RuntimeError:
            loop_id = None
        status: dict[str, Any] = {
            "enabled": s.enabled,
            "mode": s.mode,
            "default_scene": s.default_scene,
            "source": s.source,
            "client_ready": bool(self._clients),
        }
        errors = [e for e in self._client_errors.values() if e]
        if errors:
            status["client_error"] = errors[0]
        if loop_id is not None and self._last_errors.get(loop_id):
            status["last_error"] = self._last_errors[loop_id]
        if self._sdk_error:
            status["sdk_error"] = self._sdk_error
        if s.enabled and not self._clients and not errors:
            status["note"] = "client builds lazily on first use"
        return status

    # ── client 生命周期 ──

    async def _get_client(self) -> HyMemoryClient | None:
        """懒构建 client（按当前事件循环分桶）；任何失败返回 None。

        ``asyncio.Lock``（每 loop 一把）防并发首调用重复构建 —— SDK client
        构建会建 Chroma 连接 + SQLite，双花不如等。失败原因按 loop 缓存，
        同一 loop 内不重试（换 loop 时错误缓存自动失效，允许重试一次）。
        """
        loop_id = id(asyncio.get_running_loop())
        client = self._clients.get(loop_id)
        if client is not None:
            return client
        if loop_id in self._client_errors:
            return None
        lock = self._locks.get(loop_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[loop_id] = lock
        async with lock:
            client = self._clients.get(loop_id)  # 二次检查（锁期内被建好）
            if client is not None:
                return client
            try:
                client = await asyncio.to_thread(self._build_client)
            except Exception as exc:
                self._client_errors[loop_id] = f"{type(exc).__name__}: {exc}"
                logger.warning(
                    "hy-memory client build failed, degrading: %s",
                    self._client_errors[loop_id],
                )
                return None
            self._clients[loop_id] = client
            logger.info("hy-memory client ready (mode=%s)", self._settings.mode)
            return client

    def _build_client(self) -> HyMemoryClient:
        """同步构建 SDK client（在线程池里跑，不阻塞事件循环）。"""
        try:
            from hy_memory import HyMemoryClient
        except ImportError as exc:
            self._sdk_error = str(exc)
            raise RuntimeError(
                "hy_memory SDK not installed — install the optional extra: "
                'pip install -e ".[memory-hy]"'
            ) from exc

        s = self._settings
        config: dict[str, Any] = {}
        if s.data_dir:
            # MEMORY_DATA_DIR 同时决定 Chroma 持久化、SQLite 元数据与 SDK 日志
            # 的落点（SDK 默认 ~/.hy_memory；容器部署应指向持久卷）。
            os.environ["MEMORY_DATA_DIR"] = s.data_dir
        if s.llm_model or s.llm_api_key or s.llm_base_url:
            config["llm"] = {
                "provider": "openai",
                "model": s.llm_model,
                "api_key": s.llm_api_key,
                "base_url": s.llm_base_url,
            }
        if s.embedder_model or s.embedder_api_key or s.embedder_base_url:
            embedder: dict[str, Any] = {
                "provider": "openai",
                "model": s.embedder_model,
                "api_key": s.embedder_api_key,
                "base_url": s.embedder_base_url,
            }
            if s.embedding_dims > 0:
                embedder["embedding_dims"] = s.embedding_dims
            config["embedder"] = embedder
        return HyMemoryClient.from_config(config, mode=s.mode)

    async def close(self) -> None:
        """关停所有 loop 上的 client（应用 shutdown 钩子用）。永不抛。"""
        clients, self._clients = self._clients, {}
        self._client_errors.clear()
        for client in clients.values():
            try:
                await asyncio.to_thread(client.close)
            except Exception as exc:  # best-effort
                logger.debug("hy-memory client close failed: %s", exc)

    # ── 读写 ──

    @staticmethod
    def workspace_for(account_id: str) -> str:
        """account_id → SDK workspace_id（working/coding 隔离用）。"""
        return f"xhs/{account_id}" if account_id else "xhs/default"

    async def recall(
        self,
        query: str,
        *,
        account_id: str,
        scene: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """检索账号相关记忆，返回归一化的 dict 列表（空列表 = 没命中/降级）。

        chat 场景取 ``memories.{profile,normal,proactive}``；working/coding
        取 ``facts`` / ``experiences``。每条 dict 至少带
        ``{"content", "scene", "score", "layer"}``，调用方可直接渲染。
        """
        if not self.enabled or not query:
            return []
        client = await self._get_client()
        if client is None:
            # client 构建失败（SDK 缺失/配置错误）也要留下错误痕迹，
            # 否则上层 recall_hy_memory 会把"挂了"误判成"没命中"。
            loop_id = id(asyncio.get_running_loop())
            fallback_error = self._client_errors.get(loop_id, "client_unavailable")
            self._last_errors.setdefault(loop_id, fallback_error)
            return []
        s = self._settings
        scene = scene or s.default_scene
        self._last_errors.pop(id(asyncio.get_running_loop()), None)
        try:
            result = await client.async_search(
                query,
                scene=scene,
                user_ids=[account_id] if account_id else None,
                include_sources=[s.source],
                limit=limit or s.default_limit,
            )
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            self._last_errors[id(asyncio.get_running_loop())] = message
            logger.warning("hy-memory recall failed (query=%.60s): %s", query, message)
            return []
        return _normalize_search_result(result, scene=scene)

    async def remember(
        self,
        data: str | list[dict[str, str]],
        *,
        account_id: str,
        scene: str | None = None,
        metadata: dict[str, Any] | None = None,
        workspace_id: str | None = None,
        branch: str | None = None,
    ) -> dict[str, Any] | None:
        """写入一条记忆。返回 SDK 的结果 dict；禁用/失败返回 None。

        ``data`` 可以是纯文本（chat 偏好/画像）或 OpenAI 格式消息列表
        （working/coding 必须带 tool_calls 或 role="tool" 痕迹才会进
        两层管线，否则按 raw 记忆存储）。
        """
        if not self.enabled:
            return None
        client = await self._get_client()
        if client is None:
            return None
        s = self._settings
        scene = scene or s.default_scene
        loop_id = id(asyncio.get_running_loop())
        self._last_errors.pop(loop_id, None)
        try:
            result = await client.async_add(
                data,
                user_id=account_id,
                source=s.source,
                scene=scene,
                metadata=metadata,
                workspace_id=workspace_id or self.workspace_for(account_id),
                branch=branch,
            )
            return result if isinstance(result, dict) else None
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            self._last_errors[loop_id] = message
            logger.warning("hy-memory remember failed (scene=%s): %s", scene, message)
            return None

    async def list_memories(
        self,
        *,
        account_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """列出一个账号的记忆（管理/调试面）。禁用/失败返回 []。"""
        if not self.enabled:
            return []
        client = await self._get_client()
        if client is None:
            return []
        try:
            result = await client.async_list_memories(
                user_id=account_id,
                limit=limit,
                offset=offset,
            )
        except Exception as exc:
            logger.warning("hy-memory list failed: %s", exc)
            return []
        vdb = result.get("vdb") if isinstance(result, dict) else None
        return list(vdb) if isinstance(vdb, list) else []

    async def forget(self, memory_id: str) -> bool:
        """删除一条记忆。成功 True；禁用/失败 False。"""
        if not self.enabled or not memory_id:
            return False
        client = await self._get_client()
        if client is None:
            return False
        try:
            await client.async_delete(memory_id)
            return True
        except Exception as exc:
            logger.warning("hy-memory forget failed (%s): %s", memory_id, exc)
            return False

    async def metrics(self, *, minutes: int = 60) -> dict[str, Any]:
        """SDK 运行指标（请求量/时延/存储 ops）。禁用返回 {}。"""
        if not self.enabled:
            return {}
        client = await self._get_client()
        if client is None:
            return {}
        try:
            result = await client.async_get_metrics(minutes=minutes)
        except Exception as exc:
            logger.debug("hy-memory metrics failed: %s", exc)
            return {}
        return result if isinstance(result, dict) else {}


def _normalize_search_result(result: Any, *, scene: str) -> list[dict[str, Any]]:
    """SDK search 返回 → 归一化 dict 列表。

    chat: ``{"memories": {"profile": [...], "normal": [...], "proactive": [...]}}``
    working/coding: ``{"facts": [...], "experiences": [...], "chain_block": ...}``

    SDK 每条记忆至少带 ``content`` / ``score``（字段名随版本可能有差异，
    这里逐个兜底，结构异常时跳过该条而不是整体失败）。
    """
    if not isinstance(result, dict):
        return []
    out: list[dict[str, Any]] = []
    if scene == "chat":
        channels = result.get("memories")
        if isinstance(channels, dict):
            for channel in ("profile", "normal", "proactive"):
                items = channels.get(channel)
                if isinstance(items, list):
                    for item in items:
                        normalized = _normalize_item(item, scene, channel)
                        if normalized is not None:
                            out.append(normalized)
    else:
        for channel in ("facts", "experiences"):
            items = result.get(channel)
            if isinstance(items, list):
                for item in items:
                    normalized = _normalize_item(item, scene, channel)
                    if normalized is not None:
                        out.append(normalized)
    return out


def _normalize_item(item: Any, scene: str, channel: str) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    content = item.get("content") or item.get("statement") or item.get("text")
    if not content:
        return None
    try:
        score = float(item.get("score", 0.0))
    except (TypeError, ValueError):
        score = 0.0
    normalized: dict[str, Any] = {
        "content": str(content),
        "scene": scene,
        "channel": channel,
        "score": score,
        "layer": item.get("layer") or channel,
    }
    # working/coding 的经验层带复用坐标，原样透出（prompt 渲染可能用到）。
    for key in ("task", "search_keys", "solution", "boundary_envs", "memory_id", "id"):
        if key in item:
            normalized[key] = item[key]
    return normalized


_bridge: HyMemoryBridge | None = None


def get_hy_memory_bridge(settings: HyMemorySettings | None = None) -> HyMemoryBridge:
    """进程级单例。首次调用可用显式 settings（测试注入用）。

    未显式注入时从全局 ``Settings()`` 取 ``hy_memory`` 段（仓库惯例：
    pydantic-settings 每次实例化读env，单例只读一次，后续快照稳定）。
    """
    global _bridge
    if _bridge is None:
        if settings is None:
            from backend.config.settings import Settings

            settings = Settings().hy_memory
        _bridge = HyMemoryBridge(settings)
    return _bridge


def reset_hy_memory_bridge() -> None:
    """测试辅助：丢弃单例（不关停已有 client —— 调用方负责 close）。"""
    global _bridge
    _bridge = None
