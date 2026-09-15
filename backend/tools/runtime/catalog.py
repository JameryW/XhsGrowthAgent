"""Tool catalogue — the declared metadata for every real capability (P1c-S1).

Two kinds of tool exist in this repo, and both are adapted to the same
invocation contract here:

* LangChain ``StructuredTool`` (``@tool``-decorated async functions) — the
  name / description / input schema are **reflected** from the object, so we
  never re-declare (and never drift from) what LangChain already knows.
* Plain functions (sync or async) — capability, summary and parameter
  description are declared explicitly, since there is no schema to read.

What is declared *here* rather than reflected is exactly what LangChain does
not express: side-effect strength, latency / cost class, retry policy and
auth scope. Those are the runtime facts the Gateway needs.

S1 registers metadata only — no call path changes.
"""

from __future__ import annotations

import inspect
from collections.abc import Mapping
from typing import Any

from backend.tools.analysis.topic_scorer import topic_scorer
from backend.tools.content.de_ai_taste import algorithmic_de_ai, polish_copy
from backend.tools.ripple.integration import get_report, predict_spread, validate_pmf
from backend.tools.runtime.models import (
    CostClass,
    LatencyClass,
    RetryPolicy,
    SideEffect,
    ToolFn,
    ToolSpec,
)
from backend.tools.runtime.registry import ToolRegistry
from backend.tools.xhs.publisher import xhs_publisher
from backend.tools.xhs.trending import competitor_analyzer, keyword_monitor, xhs_trending

__all__ = ["adapt_tool", "build_registry", "describe_params"]

_LANGCHAIN_TOOL_ATTRS = ("ainvoke", "args_schema", "name")


def _is_langchain_tool(target: Any) -> bool:
    """Duck-typed check — avoids importing langchain here for typing only."""
    return all(hasattr(target, attr) for attr in _LANGCHAIN_TOOL_ATTRS)


def adapt_tool(target: Any) -> ToolFn:
    """Adapt any supported tool object to the unified ``ToolFn`` contract.

    Sync callables are called directly rather than pushed to a thread: the
    only sync tools here are small local computations (``algorithmic_de_ai``),
    where thread hand-off would cost more than the work itself. A sync tool
    that ever blocks on I/O must be made async (the Gateway cannot help).
    """
    if _is_langchain_tool(target):

        async def _call_langchain(payload: Mapping[str, Any]) -> Any:
            return await target.ainvoke(dict(payload))

        return _call_langchain

    if inspect.iscoroutinefunction(target):

        async def _call_async(payload: Mapping[str, Any]) -> Any:
            return await target(**dict(payload))

        return _call_async

    async def _call_sync(payload: Mapping[str, Any]) -> Any:
        return target(**dict(payload))

    return _call_sync


def describe_params(target: Any) -> dict[str, Any]:
    """Lightweight parameter description for prompt rendering (L1 layer).

    ``StructuredTool`` exposes a real Pydantic schema, so we use it. For
    plain functions this is a *lightweight* description (name / type /
    default) — deliberately not advertised as strict JSON Schema, and never
    used for validation (validation is the provider's job in P4).
    """
    if _is_langchain_tool(target):
        schema = getattr(target, "args_schema", None)
        if schema is not None and hasattr(schema, "model_json_schema"):
            properties = schema.model_json_schema().get("properties", {})
            required = set(schema.model_json_schema().get("required", ()))
            return {
                name: {
                    "type": field.get("type", "any"),
                    "required": name in required,
                    "description": field.get("description", ""),
                }
                for name, field in properties.items()
            }
        return {}

    signature = inspect.signature(target)
    described: dict[str, Any] = {}
    for name, param in signature.parameters.items():
        if name in ("self", "cls"):
            continue
        described[name] = {
            "type": (
                getattr(param.annotation, "__name__", str(param.annotation))
                if param.annotation is not inspect.Parameter.empty
                else "any"
            ),
            "required": param.default is inspect.Parameter.empty,
            "description": "",
        }
    return described


def _spec(
    *,
    capability: str,
    target: Any,
    summary: str,
    side_effect: SideEffect,
    latency: LatencyClass,
    cost: CostClass,
    retry: RetryPolicy,
    auth_scope: tuple[str, ...] = (),
) -> ToolSpec:
    return ToolSpec(
        capability=capability,
        summary=summary,
        side_effect=side_effect,
        latency=latency,
        cost=cost,
        retry_policy=retry,
        auth_scope=auth_scope,
        input_schema=describe_params(target),
    )


def build_registry() -> ToolRegistry:
    """The catalogue of every capability the agents currently use (9 call
    sites) plus publishing, which P2a will route through the Gateway.

    Registration is explicit rather than derived from a directory scan: a new
    module must be declared here to become reachable, which is what makes the
    coverage test in S5 meaningful.
    """
    registry = ToolRegistry()

    # ── analysis ────────────────────────────────────────────────────────────
    registry.register(
        _spec(
            capability="analysis.topic_scorer",
            target=topic_scorer,
            summary="评估话题热度与传播潜力（读取小红书真实数据）",
            # Reads the platform through XHSClient — read-only, but slow and
            # rate-limit sensitive.
            side_effect=SideEffect.READ_ONLY,
            latency=LatencyClass.SLOW,
            cost=CostClass.CHEAP,
            retry=RetryPolicy(max_attempts=2, backoff_s=3.0),
            auth_scope=("xhs:read",),
        ),
        adapt_tool(topic_scorer),
    )

    # ── content ─────────────────────────────────────────────────────────────
    registry.register(
        _spec(
            capability="content.algorithmic_de_ai",
            target=algorithmic_de_ai,
            summary="算法级去 AI 味改写（纯本地文本规则，无外部调用）",
            side_effect=SideEffect.PURE,
            latency=LatencyClass.FAST,
            cost=CostClass.FREE,
            retry=RetryPolicy(),
        ),
        adapt_tool(algorithmic_de_ai),
    )
    registry.register(
        _spec(
            capability="content.polish_copy",
            target=polish_copy,
            summary="LLM 润色文案（计费，单次调用）",
            side_effect=SideEffect.PURE,
            latency=LatencyClass.MEDIUM,
            cost=CostClass.EXPENSIVE,
            retry=RetryPolicy(max_attempts=2, backoff_s=2.0),
        ),
        adapt_tool(polish_copy),
    )

    # ── ripple ──────────────────────────────────────────────────────────────
    registry.register(
        _spec(
            capability="ripple.get_report",
            target=get_report,
            summary="取回 Ripple 传播预测报告（按 job id）",
            side_effect=SideEffect.READ_ONLY,
            latency=LatencyClass.MEDIUM,
            cost=CostClass.CHEAP,
            retry=RetryPolicy(max_attempts=3, backoff_s=2.0),
            auth_scope=("ripple:read",),
        ),
        adapt_tool(get_report),
    )
    registry.register(
        _spec(
            capability="ripple.predict_spread",
            target=predict_spread,
            summary="预测内容传播效果（重计算，长耗时）",
            side_effect=SideEffect.READ_ONLY,
            latency=LatencyClass.SLOW,
            cost=CostClass.EXPENSIVE,
            retry=RetryPolicy(max_attempts=2, backoff_s=5.0),
            auth_scope=("ripple:read",),
        ),
        adapt_tool(predict_spread),
    )
    registry.register(
        _spec(
            capability="ripple.validate_pmf",
            target=validate_pmf,
            summary="校验 PMF 分布参数",
            side_effect=SideEffect.READ_ONLY,
            latency=LatencyClass.MEDIUM,
            cost=CostClass.CHEAP,
            retry=RetryPolicy(max_attempts=2, backoff_s=2.0),
            auth_scope=("ripple:read",),
        ),
        adapt_tool(validate_pmf),
    )

    # ── xhs platform (read) ─────────────────────────────────────────────────
    registry.register(
        _spec(
            capability="xhs.trending",
            target=xhs_trending,
            summary="抓取平台热门趋势（只读，有封禁风险）",
            side_effect=SideEffect.READ_ONLY,
            latency=LatencyClass.SLOW,
            cost=CostClass.CHEAP,
            retry=RetryPolicy(max_attempts=2, backoff_s=3.0),
            auth_scope=("xhs:read",),
        ),
        adapt_tool(xhs_trending),
    )
    registry.register(
        _spec(
            capability="xhs.keyword_monitor",
            target=keyword_monitor,
            summary="监控关键词数据（只读，有封禁风险）",
            side_effect=SideEffect.READ_ONLY,
            latency=LatencyClass.SLOW,
            cost=CostClass.CHEAP,
            retry=RetryPolicy(max_attempts=2, backoff_s=3.0),
            auth_scope=("xhs:read",),
        ),
        adapt_tool(keyword_monitor),
    )
    registry.register(
        _spec(
            capability="xhs.competitor_analyzer",
            target=competitor_analyzer,
            summary="竞品笔记分析（只读，有封禁风险）",
            side_effect=SideEffect.READ_ONLY,
            latency=LatencyClass.SLOW,
            cost=CostClass.CHEAP,
            retry=RetryPolicy(max_attempts=2, backoff_s=3.0),
            auth_scope=("xhs:read",),
        ),
        adapt_tool(competitor_analyzer),
    )

    # ── xhs platform (write) ────────────────────────────────────────────────
    registry.register(
        _spec(
            capability="xhs.publish",
            target=xhs_publisher,
            summary="发布笔记到小红书（写操作）",
            side_effect=SideEffect.SIDE_EFFECTING,
            latency=LatencyClass.SLOW,
            cost=CostClass.CHEAP,
            # No retry yet: publishing is not idempotent until P2a gives it an
            # idempotency key (Action Executor + Receipt). Enabling retry
            # without that key would double-publish — and ToolSpec refuses to
            # let us do that by accident.
            retry=RetryPolicy(),
            auth_scope=("xhs:write",),
        ),
        adapt_tool(xhs_publisher),
    )

    return registry
