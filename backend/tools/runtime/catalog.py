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

Payload passing has **three** conventions, declared per capability
(``ToolSpec.pass_style``):

* ``KWARGS`` (the default) — the payload's keys are the tool's argument
  names, so ``tool(**payload)``. What an ordinary Python function means, and
  what four of the ten capabilities here take.
* ``MAPPING`` — the tool takes one free-form mapping, so ``tool(payload)``.
  Only ``algorithmic_de_ai(data: dict)`` does this.
* ``INVOKE`` — a LangChain ``BaseTool``, so ``await tool.ainvoke(payload)``.
  The five ``@tool``-decorated capabilities.

The style is declared rather than guessed, because the object in hand cannot
always tell you which one it is — and guessing wrong does not raise.
``KWARGS`` and ``MAPPING`` are indistinguishable from a signature like
``async def f(filters: dict)``: ``f(**{"filters": {...}})`` and ``f({...})``
both "work", one of them on the wrong data. ``KWARGS`` versus ``INVOKE`` is
worse, because a test double answers *both* ``__call__`` and ``ainvoke``, so
a doubled ``StructuredTool`` and a doubled plain function look identical from
the outside. That is the silent class of bug this runtime exists to kill, so
:func:`adapt_tool` routes by the declaration and refuses a target that cannot
honour it (:func:`_validate_style`) instead of picking a convention and
hoping. Both routing defects this file has had came from inspecting the
object to choose.

Implementations are referenced **by name** (``"pkg.module:attr"``) and looked
up when called, not captured as objects. That is not indirection for its own
sake: the whole test suite replaces a tool by rebinding its module attribute
(``patch("backend.tools.analysis.topic_scorer.topic_scorer", fake)``), and a
captured function object would ignore that replacement — the agent would keep
calling the real platform client while the test believed it was faking.

S1 registers metadata only — no call path changes.
"""

from __future__ import annotations

import importlib
import inspect
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, get_origin, get_type_hints

from pydantic import BaseModel

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

__all__ = ["adapt_tool", "bind", "build_registry", "describe_params", "tool_ref"]


def _is_langchain_tool(target: Any) -> bool:
    """Is this actually a LangChain tool?

    An ``isinstance`` check, deliberately — *not* duck-typing on
    ``ainvoke``/``args_schema``/``name``. A test double answers every
    attribute, so duck-typing classifies an ``AsyncMock`` as a LangChain tool
    and then routes the payload to ``.ainvoke`` instead of calling it: the
    double silently never receives the payload, and the code under test looks
    like it degraded gracefully. Two separate defects in this runtime came
    from exactly that shortcut (reflecting a schema off a mock, and here), so
    the question is answered by the real type.

    The import is deferred because the runtime is imported by the agent base
    class, and only a composition root ever needs langchain.
    """
    from langchain_core.tools import BaseTool

    return isinstance(target, BaseTool)


@dataclass(frozen=True)
class ToolRef:
    """A capability's implementation, named rather than captured.

    ``"backend.tools.analysis.topic_scorer:topic_scorer"``. Keeping the name
    means the lookup happens when the tool is *called*, so a replaced module
    attribute (a test double, or a reload in development) is honoured.
    """

    module: str
    attr: str

    def __str__(self) -> str:
        return f"{self.module}:{self.attr}"

    def resolve(self) -> Any:
        """The current object at that path.

        Raises ``AttributeError``/``ImportError`` if the path is wrong —
        deliberately at *build* time for every registered tool, so a typo in
        the catalogue fails the composition root instead of one call.
        """
        return getattr(importlib.import_module(self.module), self.attr)


def tool_ref(dotted: str) -> ToolRef:
    """Parse ``"pkg.module:attr"`` into a :class:`ToolRef`."""
    module, separator, attr = dotted.partition(":")
    if not separator or not module or not attr:
        raise ValueError(f"tool reference must be 'pkg.module:attr' (got {dotted!r})")
    return ToolRef(module=module, attr=attr)


def bind(ref: ToolRef, *, pass_style: PassStyle = PassStyle.KWARGS) -> ToolFn:
    """A ``ToolFn`` that invokes whatever ``ref`` currently points at.

    The target is resolved and adapted once eagerly — so a declaration the
    signature cannot honour still fails at build time, not on the first call
    — and re-adapted only when the path starts returning a different object
    (which is exactly what a test double does).
    """
    target = ref.resolve()
    current: tuple[Any, ToolFn] = (target, adapt_tool(target, pass_style=pass_style))

    async def _call(payload: Mapping[str, Any]) -> Any:
        nonlocal current
        target = ref.resolve()
        if current[0] is not target:
            current = (target, adapt_tool(target, pass_style=pass_style))
        return await current[1](payload)

    return _call


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


def _target_name(target: Any) -> str:
    """A readable name for error messages.

    Not ``getattr(target, "__name__", repr(target))``: a mock auto-creates any
    attribute asked of it, so that returns a ``Mock`` repr rather than the
    name — the same trap this module keeps having to avoid.
    """
    name = getattr(target, "__name__", None)
    return name if isinstance(name, str) and name else type(target).__name__


def _validate_style(target: Any, style: PassStyle) -> None:
    """Refuse a target the declared style cannot be honoured against.

    This checks the declaration *against* the object; it never infers the
    declaration from it. Every mismatch caught here is one that would
    otherwise surface as a tool failure at the first request — or, worse,
    succeed with the payload in the wrong shape.
    """
    name = _target_name(target)
    if style is PassStyle.INVOKE:
        if not callable(getattr(target, "ainvoke", None)):
            raise ValueError(
                f"{name}: declared PassStyle.INVOKE, which calls "
                "await target.ainvoke(payload), but the target has no callable "
                "ainvoke. Declare PassStyle.KWARGS if the payload keys are its "
                "argument names, or PassStyle.MAPPING if it takes the payload "
                "mapping whole."
            )
        return
    if _is_langchain_tool(target):
        # A StructuredTool is not callable, so a direct call raises TypeError
        # on the first request. Say the fix instead.
        raise ValueError(
            f"{name} is a LangChain tool, which is invoked as "
            "await tool.ainvoke(payload) rather than called. Declare "
            "PassStyle.INVOKE."
        )
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

    ``pass_style`` states how the payload reaches ``target`` and *decides the
    route*; :func:`_validate_style` then checks the target can honour that
    declaration. Nothing here inspects the target in order to choose a
    convention — see the module docstring for why that is not a safe question
    to ask of an object.

    Sync callables are called directly rather than pushed to a thread: the
    only sync tools here are small local computations (``algorithmic_de_ai``),
    where thread hand-off would cost more than the work itself. A sync tool
    that ever blocks on I/O must be made async (the Gateway cannot help).
    """
    _validate_style(target, pass_style)

    if pass_style is PassStyle.INVOKE:

        async def _call_invoke(payload: Mapping[str, Any]) -> Any:
            return await target.ainvoke(dict(payload))

        return _call_invoke

    if pass_style is PassStyle.MAPPING:

        async def _call_mapping(payload: Mapping[str, Any]) -> Any:
            result = target(dict(payload))
            # A mapping-style tool may be async; awaiting it keeps ToolFn's
            # "one awaitable in, one value out" contract true either way, and
            # avoids handing the Gateway an un-awaited coroutine as a value.
            if inspect.isawaitable(result):
                result = await result
            return result

        return _call_mapping

    if inspect.iscoroutinefunction(target):

        async def _call_async(payload: Mapping[str, Any]) -> Any:
            return await target(**dict(payload))

        return _call_async

    async def _call_sync(payload: Mapping[str, Any]) -> Any:
        return target(**dict(payload))

    return _call_sync


def _reflected_schema(target: Any) -> Mapping[str, Any] | None:
    """The Pydantic schema behind a real LangChain tool, when there is one.

    Only consulted for a ``BaseTool`` (:func:`describe_params` gates on that),
    and even then only used when the schema really is a Pydantic model's:
    ``model_json_schema()`` on anything else returns whatever that something
    makes up — a coroutine, for a double — and ``.get`` on that used to take
    the whole catalogue down at build time. A tool without a usable schema
    declares none (``{}``), which is the honest answer and what the S5
    coverage gate is for.
    """
    schema = getattr(target, "args_schema", None)
    if not (isinstance(schema, type) and issubclass(schema, BaseModel)):
        return None
    try:
        reflected = schema.model_json_schema()
    except Exception:  # a broken schema must not take the catalogue down
        return None
    return reflected if isinstance(reflected, Mapping) else None


def describe_params(target: Any) -> dict[str, Any]:
    """Lightweight parameter description for prompt rendering (L1 layer).

    A real ``StructuredTool`` exposes a Pydantic schema, so we use it. For
    plain functions this is a *lightweight* description (name / type /
    default) — deliberately not advertised as strict JSON Schema, and never
    used for validation (validation is the provider's job in P4).

    The reflected path is gated on the real type rather than on the presence
    of an ``args_schema`` attribute: a double can fake that attribute, and
    the schema it fakes is not a schema. Anything that is not a ``BaseTool``
    is described by signature, which is true of it.

    This reflects the tool's *signature*: a ``PassStyle.MAPPING`` tool shows
    its one ``data`` parameter, even though callers pass that mapping directly
    as the payload rather than nesting it under ``data``. L1 rendering (S4)
    must branch on ``ToolSpec.pass_style`` to render it honestly.
    """
    if _is_langchain_tool(target):
        reflected = _reflected_schema(target)
        if reflected is None:
            return {}
        properties = reflected.get("properties", {})
        required = set(reflected.get("required", ()))
        return {
            name: {
                "type": field.get("type", "any"),
                "required": name in required,
                "description": field.get("description", ""),
            }
            for name, field in properties.items()
        }

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
    ref: ToolRef,
    summary: str,
    side_effect: SideEffect,
    latency: LatencyClass,
    cost: CostClass,
    retry: RetryPolicy,
    auth_scope: tuple[str, ...] = (),
    pass_style: PassStyle = PassStyle.KWARGS,
    timeout_s: float | None = None,
) -> None:
    """Declare a capability and bind it, from one statement.

    The declaration and the adapter are built from the *same* ``pass_style``
    value and the *same* resolved target here, so ``ToolSpec.pass_style``
    cannot claim one convention while the Gateway calls another.

    ``KWARGS`` is merely the *default*, not an assumption: it is plain
    Python's convention, and a target that contradicts it is refused by
    :func:`_validate_style` rather than routed the wrong way. Anything that
    is not an ordinary function — a LangChain tool, a payload-whole tool —
    must say so here.

    ``timeout_s`` overrides the latency-class default; declare it whenever a
    call site had a wait budget of its own, so the budget has exactly one home.
    """
    target = ref.resolve()
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
            timeout_s=timeout_s,
            input_schema=describe_params(target),
        ),
        bind(ref, pass_style=pass_style),
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
        ref=tool_ref("backend.tools.analysis.topic_scorer:topic_scorer"),
        summary="评估话题热度与传播潜力（读取小红书真实数据）",
        # A LangChain @tool: reached through ainvoke, not called.
        pass_style=PassStyle.INVOKE,
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
        ref=tool_ref("backend.tools.content.de_ai_taste:algorithmic_de_ai"),
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
        ref=tool_ref("backend.tools.content.de_ai_taste:polish_copy"),
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
        ref=tool_ref("backend.tools.ripple.integration:get_report"),
        summary="取回 Ripple 传播预测报告（按 job id）",
        side_effect=SideEffect.READ_ONLY,
        latency=LatencyClass.MEDIUM,
        cost=CostClass.CHEAP,
        # S3c: the call site (``analyst._ripple_report``) guarded this fetch
        # with a hard 120s ``asyncio.wait_for``. That budget now belongs to the
        # capability, so it is declared here and the call site no longer wraps
        # the call — one home for the wait, not two that can disagree.
        timeout_s=120.0,
        # No retry, deliberately — and this is not the read-only default
        # applied blindly. ``get_report`` reports its own failures as data
        # (``{"error": ...}``) and so never raises, which leaves the Gateway's
        # own timeout as the only retryable event; and retrying a timeout is
        # not a transient-failure remedy, it is a longer wait wearing a
        # disguise (two attempts behind a 120s guard stall the node for 240s,
        # which is a budget question, not a retry one). If this ever needs to
        # wait longer, raise ``timeout_s``.
        retry=RetryPolicy(),
        auth_scope=("ripple:read",),
    )
    _register(
        registry,
        capability="ripple.predict_spread",
        ref=tool_ref("backend.tools.ripple.integration:predict_spread"),
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
        ref=tool_ref("backend.tools.ripple.integration:validate_pmf"),
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
        ref=tool_ref("backend.tools.xhs.trending:xhs_trending"),
        summary="抓取平台热门趋势（只读，有封禁风险）",
        pass_style=PassStyle.INVOKE,
        side_effect=SideEffect.READ_ONLY,
        latency=LatencyClass.SLOW,
        cost=CostClass.CHEAP,
        retry=RetryPolicy(max_attempts=2, backoff_s=3.0),
        auth_scope=("xhs:read",),
    )
    _register(
        registry,
        capability="xhs.keyword_monitor",
        ref=tool_ref("backend.tools.xhs.trending:keyword_monitor"),
        summary="监控关键词数据（只读，有封禁风险）",
        pass_style=PassStyle.INVOKE,
        side_effect=SideEffect.READ_ONLY,
        latency=LatencyClass.SLOW,
        cost=CostClass.CHEAP,
        retry=RetryPolicy(max_attempts=2, backoff_s=3.0),
        auth_scope=("xhs:read",),
    )
    _register(
        registry,
        capability="xhs.competitor_analyzer",
        ref=tool_ref("backend.tools.xhs.trending:competitor_analyzer"),
        summary="竞品笔记分析（只读，有封禁风险）",
        pass_style=PassStyle.INVOKE,
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
        ref=tool_ref("backend.tools.xhs.publisher:xhs_publisher"),
        summary="发布笔记到小红书（写操作）",
        pass_style=PassStyle.INVOKE,
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
