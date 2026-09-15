"""Tool Runtime — declarative tool metadata (P1c-S1).

``ToolSpec`` describes *what a tool is*: its capability id, input/output
contract, side-effect strength, latency/cost class, retry policy and auth
scope. It is the Registry entry type, the thing the Gateway consults to
decide timeout / retry / rate limiting, and the data source for the L1 tool
schema layer (the layer P1b left empty until this task gave it a producer).

This slice is purely additive: it registers metadata and changes no call
path.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "CostClass",
    "LatencyClass",
    "PassStyle",
    "RetryPolicy",
    "SideEffect",
    "ToolResult",
    "ToolSpec",
]


class SideEffect(StrEnum):
    """Side-effect strength — decides whether retrying is safe."""

    PURE = "pure"
    """Local computation. Retry freely."""
    READ_ONLY = "read_only"
    """Reads an external system. Retryable, but rate limits still apply."""
    SIDE_EFFECTING = "side_effecting"
    """Changes external state. Retrying *requires* an idempotency key."""


class LatencyClass(StrEnum):
    """Expected wall-clock class — drives the default timeout."""

    FAST = "fast"
    """Sub-second (local computation)."""
    MEDIUM = "medium"
    """Seconds (light network / one LLM call)."""
    SLOW = "slow"
    """Tens of seconds (heavy external service, platform scraping)."""


class CostClass(StrEnum):
    """Cost class — drives rate limiting and (later) budget accounting."""

    FREE = "free"
    """No external cost (local computation)."""
    CHEAP = "cheap"
    """Cheap network call."""
    EXPENSIVE = "expensive"
    """Billed call — LLM inference or a metered service."""


class PassStyle(StrEnum):
    """How the payload mapping reaches the underlying tool.

    Not every tool takes keyword arguments. ``algorithmic_de_ai(data: dict)``
    takes one free-form mapping, so unpacking the payload as keywords would
    raise ``TypeError: unexpected keyword argument`` — a failure the Gateway
    would faithfully report as ``ok=False``, i.e. as "the tool broke" rather
    than "we wired it wrong". Declaring the style here is what makes that
    distinction auditable (and is exactly what L1 rendering needs to describe
    a free-form tool without inventing parameter names it cannot know).
    """

    KWARGS = "kwargs"
    """Payload keys are the tool's argument names (``tool(**payload)``)."""
    MAPPING = "mapping"
    """The tool takes one mapping argument (``tool(payload)``)."""


# Default per-latency timeout, unless a spec overrides it explicitly.
_DEFAULT_TIMEOUT_S: Mapping[LatencyClass, float] = {
    LatencyClass.FAST: 5.0,
    LatencyClass.MEDIUM: 30.0,
    LatencyClass.SLOW: 120.0,
}


@dataclass(frozen=True)
class RetryPolicy:
    """Declarative retry rules for one capability.

    Kept separate from graph-level retry on purpose: P0 closed the
    double-retry semantics, and a tool-level transient failure must not be
    conflated with a node-level one.
    """

    max_attempts: int = 1
    backoff_s: float = 0.0
    requires_idempotency_key: bool = False

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("RetryPolicy.max_attempts must be >= 1")
        if self.backoff_s < 0:
            raise ValueError("RetryPolicy.backoff_s must be >= 0")

    @property
    def retryable(self) -> bool:
        return self.max_attempts > 1


@dataclass(frozen=True)
class ToolSpec:
    """Declarative metadata for one capability.

    ``capability`` is the stable id agents request (``"ripple.predict_spread"``);
    it must be dotted so a namespace never collides with a bare function name.
    """

    capability: str
    summary: str
    side_effect: SideEffect
    latency: LatencyClass = LatencyClass.FAST
    cost: CostClass = CostClass.FREE
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    auth_scope: tuple[str, ...] = ()
    pass_style: PassStyle = PassStyle.KWARGS
    """How :mod:`~backend.tools.runtime.catalog` hands the payload over.

    Set by ``adapt_tool``'s detection so the adapter and the declaration can
    never disagree; overridable when a tool's signature is ambiguous.
    """
    timeout_s: float | None = None
    max_concurrency: int | None = None
    """In-flight ceiling for this capability (``None`` = unbounded).

    The Gateway enforces it with a per-capability semaphore. This is the
    deterministic half of rate limiting; time-based quotas belong to the
    durable scheduler (P2b).
    """
    input_schema: Mapping[str, Any] = field(default_factory=dict)
    output_schema: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.capability or "." not in self.capability:
            raise ValueError(f"capability must be a dotted id (got {self.capability!r})")
        if not self.summary.strip():
            raise ValueError(f"{self.capability}: summary must not be empty")
        if self.timeout_s is not None and self.timeout_s <= 0:
            raise ValueError(f"{self.capability}: timeout_s must be > 0")
        if self.max_concurrency is not None and self.max_concurrency < 1:
            raise ValueError(f"{self.capability}: max_concurrency must be >= 1")
        # Retrying something that changes external state without an
        # idempotency key is how you double-publish. Fail loudly instead.
        if (
            self.side_effect is SideEffect.SIDE_EFFECTING
            and self.retry_policy.retryable
            and not self.retry_policy.requires_idempotency_key
        ):
            raise ValueError(
                f"{self.capability}: side_effecting tools with max_attempts > 1 "
                "must set requires_idempotency_key=True"
            )

    @property
    def effective_timeout_s(self) -> float:
        """Explicit timeout, else the class default."""
        if self.timeout_s is not None:
            return self.timeout_s
        return _DEFAULT_TIMEOUT_S[self.latency]

    @property
    def qualified(self) -> str:
        """``capability`` plus its risk posture, for logs."""
        return f"{self.capability}[{self.side_effect.value}]"

    def to_dict(self) -> dict[str, Any]:
        """Serialisable view (for L1 rendering / diagnostics)."""
        return {
            "capability": self.capability,
            "summary": self.summary,
            "side_effect": self.side_effect.value,
            "latency": self.latency.value,
            "cost": self.cost.value,
            "auth_scope": list(self.auth_scope),
            "pass_style": self.pass_style.value,
            "timeout_s": self.effective_timeout_s,
            "max_concurrency": self.max_concurrency,
            "retry": {
                "max_attempts": self.retry_policy.max_attempts,
                "backoff_s": self.retry_policy.backoff_s,
                "requires_idempotency_key": self.retry_policy.requires_idempotency_key,
            },
            "input_schema": dict(self.input_schema),
            "output_schema": dict(self.output_schema),
        }


class ToolResult(BaseModel):
    """Outcome of one Gateway invocation.

    Same honesty contract as ``RetrievalResult`` (P1b D6'): a failure carries
    ``error``; ``degraded`` marks "we got something, but not everything".
    """

    model_config = ConfigDict(frozen=True)

    capability: str
    ok: bool
    value: Any | None = None
    error: str = ""
    elapsed_ms: float = Field(default=0.0, ge=0.0)
    attempts: int = Field(default=1, ge=1)
    degraded: bool = False

    def __init__(self, **data: Any) -> None:
        super().__init__(**data)
        if self.ok and self.error:
            raise ValueError(
                f"{self.capability}: ok=True must not carry an error (got {self.error!r})"
            )
        if not self.ok and not self.error:
            raise ValueError(f"{self.capability}: ok=False must explain itself via error")

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability": self.capability,
            "ok": self.ok,
            "error": self.error,
            "elapsed_ms": round(self.elapsed_ms, 3),
            "attempts": self.attempts,
            "degraded": self.degraded,
        }


ToolFn = Callable[[Mapping[str, Any]], Awaitable[Any]]
"""Unified invocation contract for one capability.

One payload mapping in, one awaitable out — regardless of what the tool is
underneath (a LangChain ``StructuredTool``, an async function, a plain sync
function). :mod:`backend.tools.runtime.catalog` adapts each kind to this
shape, so the Gateway (S2) has a single calling convention to retry, time
out and trace.
"""
