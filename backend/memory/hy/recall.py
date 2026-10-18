"""hy-memory recall → P1b RetrievalResult 适配器。

把 :meth:`HyMemoryBridge.recall` 的结果包成 Context Compiler 管线的
:class:`RetrievalResult`（``backend.context.models``），使命中/降级信号
（D6'）在 hy 这条召回路径上同样可见：``HIT`` / ``EMPTY`` / ``DEGRADED``
三种 mode 与既有四命名空间一致，调用方（agents）可以并发 gather 后按
同一套逻辑渲染。

与 ``backend.context.retrieval.recall_namespaces`` 的关系：**不混用**。
既有管线只认四个注册命名空间（未知命名空间抛
``UnknownMemoryNamespaceError``），hy-memory 是外部记忆引擎、有自己的
开关与端点，走这条独立适配器；两者在 agent 里以 ``asyncio.gather`` 并发。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from backend.context.models import (
    ContextItem,
    PromptLayer,
    RetrievalMode,
    RetrievalResult,
    TrustClass,
)
from backend.memory.hy.bridge import HyMemoryBridge, get_hy_memory_bridge

logger = logging.getLogger("xhs_growth.memory.hy.recall")

#: hy 召回使用的伪命名空间（不进既有 NAMESPACE_KEYS，仅作事件面标识）。
HY_NAMESPACE_PREFIX = "hy_"


def hy_namespace(scene: str) -> str:
    """``chat`` → ``"hy_chat"``；``working`` → ``"hy_working"``。"""
    return f"{HY_NAMESPACE_PREFIX}{scene}"


async def recall_hy_memory(
    query: str,
    *,
    account_id: str,
    scene: str = "chat",
    limit: int | None = None,
    thread_id: str = "",
    bridge: HyMemoryBridge | None = None,
) -> RetrievalResult:
    """一次 hy-memory 召回，永远返回带 mode 的 RetrievalResult，永不抛。

    mode 语义（D6'）：
    - ``EMPTY``：功能关闭或确实没命中 —— 正常空态，``error`` 为空；
    - ``HIT``：拿到 ≥1 条记忆；
    - ``DEGRADED``：SDK/client 层出了问题（端点超时、结构异常）——
      携带 ``error`` 摘要，便于观测面把"外部记忆挂了"与"没有记忆"分开。
    """
    bridge = bridge or get_hy_memory_bridge()
    if not bridge.enabled:
        return RetrievalResult(
            namespace=hy_namespace(scene),
            mode=RetrievalMode.EMPTY,
        )
    try:
        items = await bridge.recall(query, account_id=account_id, scene=scene, limit=limit)
    except Exception as exc:  # bridge 自身已吞大部分；这里是双保险
        logger.warning("hy recall degraded (query=%.60s): %s", query, exc)
        return RetrievalResult(
            namespace=hy_namespace(scene),
            mode=RetrievalMode.DEGRADED,
            error=f"{type(exc).__name__}: {exc}",
        )

    if not items:
        # bridge 在 SDK 故障时也返回 []；用 last_error 区分"没命中"与"降级"。
        last_error = bridge.last_error()
        if last_error:
            return RetrievalResult(
                namespace=hy_namespace(scene),
                mode=RetrievalMode.DEGRADED,
                error=last_error,
            )
        return RetrievalResult(namespace=hy_namespace(scene), mode=RetrievalMode.EMPTY)

    context_items = tuple(_to_context_item(item) for item in items)
    return RetrievalResult(
        namespace=hy_namespace(scene),
        layer=PromptLayer.L4_MEMORY,
        items=context_items,
        raw_items=tuple(items),
        mode=RetrievalMode.HIT,
    )


def _to_context_item(item: dict[str, Any]) -> ContextItem:
    """归一化记忆 dict → ContextItem（score 折成 confidence 与 priority）。"""
    score = float(item.get("score") or 0.0)
    # SDK 分数常见区间 0-1；折成 0-100 的 priority 供 rerank 使用。
    return ContextItem(
        body=str(item.get("content") or ""),
        source=f"hy_memory:{item.get('channel') or item.get('scene') or 'chat'}",
        # P1-A: memory derived by an external engine's LLM extraction —
        # relevant by construction, but never presented as verified fact.
        trust_class=TrustClass.MEMORY,
        timestamp=datetime.now(UTC),
        confidence=min(max(score, 0.0), 1.0),
        scope="account",
        priority=int(round(score * 100)),
    )


def format_hy_section(results: list[RetrievalResult]) -> str:
    """hy 召回结果 → L4 prompt 文本段（无命中返回空串）。

    与 ``content_strategist._format_memory_context`` 同一形态：调用方把
    返回值拼进 ``memory_context``。降级（DEGRADED）不静默 —— 以一行
    【hy-memory 降级】注明，让模型与运维都能看见外部记忆不在线，
    而不是把"没有记忆"伪装成"记忆说没有"。
    """
    lines: list[str] = []
    for result in results:
        if result.mode is RetrievalMode.HIT and result.items:
            label = "账号记忆画像" if result.namespace == hy_namespace("chat") else "运营经验记忆"
            lines.append(f"{label}（hy-memory）：")
            for item in result.items:
                lines.append(f"- {item.body}")
        elif result.mode is RetrievalMode.DEGRADED:
            lines.append(f"【hy-memory 降级】{result.namespace}: {result.error or 'unknown'}")
    return "\n".join(lines)
