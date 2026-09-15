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

Payload passing has **two** conventions, declared per capability
(``ToolSpec.pass_style``):

* ``KWARGS`` (the default) — the payload's keys are the tool's argument
  names, so ``tool(**payload)``. This is what a LangChain tool means, and
  what almost every tool here takes.
* ``MAPPING`` — the tool takes one free-form mapping, so ``tool(payload)``.
  Only ``algorithmic_de_ai(data: dict)`` does this.

The style is declared rather than guessed, because the two are
indistinguishable from a signature like ``async def f(filters: dict)`` — and
guessing wrong does not raise. ``f(**{"filters": {...}})`` and ``f({...})``
both "work"; one of them runs on the wrong data. That is the silent class of
bug this runtime exists to kill, so :func:`adapt_tool` refuses a declaration
the target's signature cannot honour instead of picking one.

S1 registers metadata only — no call path changes.
"""

from __future__ import annotations

import inspect
from collections.abc import Mapping
from typing import Any, get_origin, get_type_hints

from backend.tools.analysis.topic_scorer import topic_scorer
from backend.tools.content.de_ai_taste import algorithmic_de_ai, polish_copy
from backend.tools.ripple.integration import get_report, predict_spread, validate_pmf
from backend.tools.runtime.models import (
    CostClass,
    LatencyClass,
    PassStyle,
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


def _is_mapping_annotation(annotation: Any) -> bool:
    """True for ``dict[str, Any]`` / ``Mapping[str, Any]`` and friends."""
    if annotation is inspect.Parameter.empty:
        return False
    origin = get_origin(annotation)
    concrete = origin if origin is not None else annotation
    return isinstance(concrete, type) and issubclass(concrete, Mapping)


def _resolved_annotation(target: Any, param: inspect.Parameter) -> Any:
    """Annotation as a type object, not the string PEP 563 leaves behind.

    Every module in this repo uses ``from __future__ import annotations``, so
    ``param.annotation`` is the *string* ``"dict[str, Any]"`` — and a string is
    never a ``Mapping`` subclass, which would make the check below answer
    "not a mapping" for every tool in the catalogue. ``get_type_hints``
    resolves it against the defining module; if it cannot (a callable object,
    an unresolvable forward reference) we keep the raw value and simply do not
    claim it is a mapping — the declared style still decides.
    """
    if param.annotation is inspect.Parameter.empty:
        return inspect.Parameter.empty
    try:
        hints = get_type_hints(target)
    except Exception:  # not introspectable as a function → keep it raw
        return param.annotation
    return hints.get(param.name, param.annotation)


def _positional_params(target: Any) -> list[inspect.Parameter]:
    """Bindable positional parameters, ignoring ``self``/``cls``."""
    return [
        param
        for name, param in inspect.signature(target).parameters.items()
        if name not in ("self", "cls")
        and param.kind
        in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]


def _takes_a_free_form_mapping(target: Any) -> bool:
    """One required positional argument, annotated as a mapping.

    Such a tool *probably* wants the payload mapping itself — which is exactly
    why it must not be assumed: see the module docstring.
    """
    positional = _positional_params(target)
    if len(positional) != 1 or positional[0].default is not inspect.Parameter.empty:
        return False
    return _is_mapping_annotation(_resolved_annotation(target, positional[0]))


def _validate_style(target: Any, style: PassStyle) -> None:
    """Refuse a declared style the target's signature cannot honour."""
    name = getattr(target, "__name__", repr(target))
    positional = _positional_params(target)
    if style is PassStyle.MAPPING:
        if len(positional) != 1:
            raise ValueError(
                f"{name}: PassStyle.MAPPING takes exactly one positional "
                f"parameter, but the target has {len(positional)}"
            )
        return
    if _takes_a_free_form_mapping(target):
        raise ValueError(
            f"{name} takes a single mapping argument ({positional[0].name}) and is "
            "declared PassStyle.KWARGS. Say which it is: declare "
            "adapt_tool(..., pass_style=PassStyle.MAPPING) if the tool is handed "
            "the payload itself, or annotate the parameter as its real type if "
            "the payload keys are genuinely its argument names. Both ways call "
            "successfully — one of them passes the wrong data."
        )


def adapt_tool(target: Any, *, pass_style: PassStyle = PassStyle.KWARGS) -> ToolFn:
    """Adapt any supported tool object to the unified ``ToolFn`` contract.

    ``pass_style`` states how the payload reaches ``target`` and is validated
    against the signature (:func:`_validate_style`) rather than inferred.

    Sync callables are called directly rather than pushed to a thread: the
    only sync tools here are small local computations (``algorithmic_de_ai``),
    where thread hand-off would cost more than the work itself. A sync tool
    that ever blocks on I/O must be made async (the Gateway cannot help).
    """
    if _is_langchain_tool(target):

        async def _call_langchain(payload: Mapping[str, Any]) -> Any:
            return await target.ainvoke(dict(payload))

        return _call_langchain

    _validate_style(target, pass_style)

    if pass_style is PassStyle.MAPPING:

        async def _call_mapping(payload: Mapping[str, Any]) -> Any:
            return target(dict(payload))

        return _call_mapping

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

    This reflects the tool's *signature*: a ``PassStyle.MAPPING`` tool shows
    its one ``data`` parameter, even though callers pass that mapping directly
    as the payload rather than nesting it under ``data``. L1 rendering (S4)
    must branch on ``ToolSpec.pass_style`` to render it honestly.
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


def _register(
    registry: ToolRegistry,
    *,
    capability: str,
    target: Any,
    summary: str,
    side_effect: SideEffect,
    latency: LatencyClass,
    cost: CostClass,
    retry: RetryPolicy,
    auth_scope: tuple[str, ...] = (),
    pass_style: PassStyle = PassStyle.KWARGS,
) -> None:
    """Declare a capability and bind it, from one statement.

    The declaration and the adapter are built from the *same* ``pass_style``
    value here, so ``ToolSpec.pass_style`` cannot claim one convention while
    the Gateway calls another.
    """
    registry.register(
        ToolSpec(
            capability=capability,
            summary=summary,
            side_effect=side_effect,
            latency=latency,
            cost=cost,
            retry_policy=retry,
            auth_scope=auth_scope,
            pass_style=pass_style,
            input_schema=describe_params(target),
        ),
        adapt_tool(target, pass_style=pass_style),
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
    _register(
        registry,
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
    )

    # ── content ─────────────────────────────────────────────────────────────
    _register(
        registry,
        capability="content.algorithmic_de_ai",
        target=algorithmic_de_ai,
        summary="算法级去 AI 味改写（纯本地文本规则，无外部调用）",
        # The one MAPPING-style tool: it takes `data: dict[str, Any]` and reads
        # the caller's keys out of it, so the payload *is* that mapping.
        # Unpacking it as keywords raises TypeError; nesting it under `data`
        # silently drops every field.
        side_effect=SideEffect.PURE,
        latency=LatencyClass.FAST,
        cost=CostClass.FREE,
        retry=RetryPolicy(),
        pass_style=PassStyle.MAPPING,
    )
    _register(
        registry,
        capability="content.polish_copy",
        target=polish_copy,
        summary="LLM 润色文案（计费，单次调用）",
        side_effect=SideEffect.PURE,
        latency=LatencyClass.MEDIUM,
        cost=CostClass.EXPENSIVE,
        retry=RetryPolicy(max_attempts=2, backoff_s=2.0),
    )

    # ── ripple ──────────────────────────────────────────────────────────────
    _register(
        registry,
        capability="ripple.get_report",
        target=get_report,
        summary="取回 Ripple 传播预测报告（按 job id）",
        side_effect=SideEffect.READ_ONLY,
        latency=LatencyClass.MEDIUM,
        cost=CostClass.CHEAP,
        retry=RetryPolicy(max_attempts=3, backoff_s=2.0),
        auth_scope=("ripple:read",),
    )
    _register(
        registry,
        capability="ripple.predict_spread",
        target=predict_spread,
        summary="预测内容传播效果（重计算，长耗时）",
        side_effect=SideEffect.READ_ONLY,
        latency=LatencyClass.SLOW,
        cost=CostClass.EXPENSIVE,
        retry=RetryPolicy(max_attempts=2, backoff_s=5.0),
        auth_scope=("ripple:read",),
    )
    _register(
        registry,
        capability="ripple.validate_pmf",
        target=validate_pmf,
        summary="校验 PMF 分布参数",
        side_effect=SideEffect.READ_ONLY,
        latency=LatencyClass.MEDIUM,
        cost=CostClass.CHEAP,
        retry=RetryPolicy(max_attempts=2, backoff_s=2.0),
        auth_scope=("ripple:read",),
    )

    # ── xhs platform (read) ─────────────────────────────────────────────────
    _register(
        registry,
        capability="xhs.trending",
        target=xhs_trending,
        summary="抓取平台热门趋势（只读，有封禁风险）",
        side_effect=SideEffect.READ_ONLY,
        latency=LatencyClass.SLOW,
        cost=CostClass.CHEAP,
        retry=RetryPolicy(max_attempts=2, backoff_s=3.0),
        auth_scope=("xhs:read",),
    )
    _register(
        registry,
        capability="xhs.keyword_monitor",
        target=keyword_monitor,
        summary="监控关键词数据（只读，有封禁风险）",
        side_effect=SideEffect.READ_ONLY,
        latency=LatencyClass.SLOW,
        cost=CostClass.CHEAP,
        retry=RetryPolicy(max_attempts=2, backoff_s=3.0),
        auth_scope=("xhs:read",),
    )
    _register(
        registry,
        capability="xhs.competitor_analyzer",
        target=competitor_analyzer,
        summary="竞品笔记分析（只读，有封禁风险）",
        side_effect=SideEffect.READ_ONLY,
        latency=LatencyClass.SLOW,
        cost=CostClass.CHEAP,
        retry=RetryPolicy(max_attempts=2, backoff_s=3.0),
        auth_scope=("xhs:read",),
    )

    # ── xhs platform (write) ────────────────────────────────────────────────
    _register(
        registry,
        capability="xhs.publish",
        target=xhs_publisher,
        summary="发布笔记到小红书（写操作）",
        side_effect=SideEffect.SIDE_EFFECTING,
        latency=LatencyClass.SLOW,
        cost=CostClass.CHEAP,
        # No retry yet: publishing is not idempotent until P2a gives it an
        # idempotency key (Action Executor + Receipt). Enabling retry without
        # that key would double-publish — and ToolSpec refuses to let us do
        # that by accident.
        retry=RetryPolicy(),
        auth_scope=("xhs:write",),
    )

    return registry
