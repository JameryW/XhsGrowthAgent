"""Tool Runtime — declarative tool metadata (P1c-S1).

``ToolSpec`` describes *what a tool is*: its capability id, input/output
contract, side-effect strength, latency/cost class, retry policy and auth
scope. It is the Registry entry type, the thing the Gateway consults to
decide timeout / retry / rate limiting, and the data source for the L1 tool
schema layer (the layer P1b left empty until this task gave it a producer).

It also holds the vocabulary a *result* speaks: ``ErrorKind`` says how a call
failed, and ``DomainOutcome`` is how a tool whose answer is neither success nor
transport failure reports that answer without the Gateway mistaking it for one.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "CostClass",
    "ErrorKind",
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

    Three conventions, all of them declared rather than inferred, because the
    object in hand cannot always tell you which one it is:

    * ``KWARGS`` — the payload's keys are the tool's argument names.
    * ``MAPPING`` — the tool takes one free-form mapping
      (``algorithmic_de_ai(data: dict)``); unpacking it as keywords raises
      ``TypeError``, and nesting it under ``data`` silently drops every field.
    * ``INVOKE`` — a LangChain ``BaseTool``, invoked as ``tool.ainvoke(payload)``.

    A tool that takes one mapping and a tool whose payload keys are its
    arguments are indistinguishable from a signature like
    ``async def f(filters: dict)`` — and guessing wrong does not raise, it
    quietly runs on the wrong data. ``KWARGS`` versus ``INVOKE`` is worse
    still: a test double answers both ``__call__`` and ``ainvoke``, so the
    adapter cannot tell a doubled ``StructuredTool`` from a doubled plain
    function. Hence: declared here, verified by ``adapt_tool`` against the
    target, never guessed. (Both silent-misrouting bugs this runtime has had
    came from trying to infer it.)
    """

    KWARGS = "kwargs"
    """Payload keys are the tool's argument names (``tool(**payload)``)."""
    MAPPING = "mapping"
    """The tool takes one mapping argument (``tool(payload)``)."""
    INVOKE = "invoke"
    """A LangChain tool: ``await tool.ainvoke(payload)``."""


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

    Declared per capability and honoured as written — ``catalog`` builds the
    adapter from this same value, so the declaration and the call cannot
    disagree. A target that cannot honour it (a LangChain tool declared
    ``KWARGS``, a plain function declared ``INVOKE``) is refused at build
    time rather than failing on the first request.
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


class ErrorKind(StrEnum):
    """*How* one invocation failed — the part a caller has to branch on.

    A failed call carries its failure as data (see the Gateway docstring), so
    the kind has to be data as well. Both kinds arrive as ``ok=False``, but
    they mean opposite things to the caller: a timeout means the work never
    finished (so there may still be something out there to cancel or resume),
    while an exception means the tool ran and said no. Branching on the
    ``error`` string to tell them apart would make a message format load
    bearing.
    """

    TIMEOUT = "timeout"
    """The Gateway's own wait budget expired and the tool was cancelled."""
    EXCEPTION = "exception"
    """The tool raised. It was given its chance and reported a failure."""
    DOMAIN = "domain"
    """The tool reported an outcome in its own vocabulary (``DomainOutcome``).

    Not a failure of the call — an *answer* about the work: Ripple saying "the
    simulation is still running, its id is X" is neither a success nor a
    transport problem, and the payload has to survive intact for the caller to
    act on it.
    """


# Named without an ``Error`` suffix deliberately (ruff N818): this is not an
# error, it is the tool's answer. The suffix would invite callers to treat a
# verdict they must act on as something that merely went wrong.
class DomainOutcome(Exception):  # noqa: N818
    """A tool's own verdict, raised rather than returned.

    Some tools answer in a vocabulary of their own instead of by succeeding or
    failing, and the answer carries data the caller needs. Returning it as an
    ordinary dict makes the Gateway read the call as ``ok=True`` — a lie the
    trace then repeats (S3c found a Ripple timeout recorded as a success, and
    the ``{"error": ...}`` variant recorded as a success too). Raising it hands
    the payload to the Gateway unaltered, which files it under
    ``ErrorKind.DOMAIN`` and copies it into ``ToolResult.domain``.

    Why this and not just ``raise RippleTimeoutError``: the Gateway classifies
    by exception *type*, and ``RippleTimeoutError`` is a ``TimeoutError``
    subclass, so on the way through it would arrive as a plain gateway timeout
    with the ``job_id`` — the one field that makes cancel/resume possible —
    stripped off.

    **Never retried.** A domain outcome is an answer, not a hiccup; asking the
    same question again costs another simulation and cannot change it.
    """

    def __init__(self, reason: str, **payload: Any) -> None:
        if not reason:
            raise ValueError("DomainOutcome needs a reason")
        self.reason = reason
        """Short machine-readable verdict (``"timeout"``, ``"unavailable"``)."""
        self.payload: dict[str, Any] = {"reason": reason, **payload}
        """The verdict plus whatever the caller needs to act on it."""
        super().__init__(reason)


class ToolResult(BaseModel):
    """Outcome of one Gateway invocation.

    Same honesty contract as ``RetrievalResult`` (P1b D6'): a failure carries
    ``error``; ``degraded`` marks "we got something, but not everything".
    ``domain`` carries the payload of a domain outcome, and is populated on
    exactly the failures that have one — see ``__init__``.
    """

    model_config = ConfigDict(frozen=True)

    capability: str
    ok: bool
    value: Any | None = None
    error: str = ""
    error_kind: ErrorKind | None = None
    domain: Mapping[str, Any] = Field(default_factory=dict)
    elapsed_ms: float = Field(default=0.0, ge=0.0)
    attempts: int = Field(default=1, ge=1)
    degraded: bool = False

    def __init__(self, **data: Any) -> None:
        super().__init__(**data)
        if self.ok and self.error:
            raise ValueError(
                f"{self.capability}: ok=True must not carry an error (got {self.error!r})"
            )
        if self.ok and self.error_kind is not None:
            raise ValueError(
                f"{self.capability}: ok=True must not carry an error_kind "
                f"(got {self.error_kind.value!r})"
            )
        if not self.ok and not self.error:
            raise ValueError(f"{self.capability}: ok=False must explain itself via error")
        if not self.ok and self.error_kind is None:
            raise ValueError(f"{self.capability}: ok=False must say how it failed via error_kind")
        # ``domain`` is populated on exactly the domain outcomes. Keeping it
        # one-way means "has a domain payload" and "is a domain outcome" are
        # the same question, so no caller has to guess whether an empty
        # mapping means "no payload" or "not that kind of failure".
        if self.ok and self.domain:
            raise ValueError(f"{self.capability}: ok=True must not carry a domain payload")
        if self.error_kind is ErrorKind.DOMAIN and not self.domain:
            raise ValueError(
                f"{self.capability}: ErrorKind.DOMAIN must carry the tool's outcome "
                "payload via domain"
            )
        if self.error_kind is not None and self.error_kind is not ErrorKind.DOMAIN and self.domain:
            raise ValueError(
                f"{self.capability}: only ErrorKind.DOMAIN carries a domain payload "
                f"(got {self.error_kind.value!r} with {sorted(self.domain)})"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability": self.capability,
            "ok": self.ok,
            "error": self.error,
            "error_kind": self.error_kind.value if self.error_kind is not None else "",
            "domain_reason": self.domain.get("reason", ""),
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
