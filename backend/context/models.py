"""Context Compiler domain models (P1b-S1 skeleton, zero behavior change).

P1b makes Context an independent system component (architecture review
§十七): every prompt is compiled from typed context items through one
pipeline (recall → rerank → dedup → freshness → budget → compile) instead of
per-agent ``template.replace`` calls.  These are the value objects of that
pipeline; nothing in the existing agent paths is wired to them yet (S1 is
additive-only — the migration happens in S4 per the consumer-map order).

Decisions frozen in the task ``info.md`` (D1'-D6'):
- D1': :class:`RunContext` is a frozen model built at the node seam; it never
  enters the LangGraph checkpoint.
- D2': ``RunContext.niche`` has no default — a missing niche fails fast at
  construction instead of silently compiling "母婴" into the prompt.
- D6': :class:`RetrievalResult` always carries a ``mode`` so a failed recall
  can never silently degrade into an empty string again (§十五).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PromptLayer(StrEnum):
    """The L0-L5 stable-prefix layers (architecture review §十八).

    Declared most → least stable; the budget allocator trims from the tail
    (L5 first) and never touches L0-L3 (info.md D4').  L1 is fed by the Tool
    Runtime's schema renderer (P1c-S4) — see ``RunContext.tool_schema`` — and
    is empty for an agent that declares no capabilities.
    """

    L0_SYSTEM = "l0_system"
    L1_TOOL_SCHEMA = "l1_tool_schema"
    L2_ACCOUNT = "l2_account"
    L3_TASK = "l3_task"
    L4_MEMORY = "l4_memory"
    L5_OBSERVATION = "l5_observation"


LAYER_ORDER: tuple[PromptLayer, ...] = tuple(PromptLayer)
"""Canonical L0→L5 rendering order."""


class ContextItem(BaseModel):
    """One compiled-context entry with full provenance metadata."""

    model_config = ConfigDict(frozen=True)

    body: str
    source: str
    timestamp: datetime | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    scope: str = "task"
    priority: int = 0
    token_cost: int = Field(default=0, ge=0)

    def with_token_cost(self, token_cost: int) -> ContextItem:
        """A copy with ``token_cost`` set (frozen model ⇒ explicit wither)."""
        return self.model_copy(update={"token_cost": token_cost})


def require_niche(state: Mapping[str, Any]) -> str:
    """D2' fail-fast companion: resolve the niche from state or raise.

    Workflow start resolves/provides the account niche (start 入口校验必填);
    agents must never invent a default (the old ``state.get("niche", "母婴")``
    silently compiled a made-up niche into prompts). Raises ``ValueError``
    with an actionable message instead.
    """
    niche = state.get("niche")
    if not niche or not str(niche).strip():
        raise ValueError(
            "niche is required (D2'): workflow start must provide or resolve "
            "the account niche; refusing to compile a default niche into the prompt"
        )
    return str(niche)


class RetrievalMode(StrEnum):
    """Outcome of one recall — the degradation signal (info.md D6')."""

    HIT = "hit"
    EMPTY = "empty"
    DEGRADED = "degraded"


class RetrievalResult(BaseModel):
    """One namespace recall outcome, with its degradation signal.

    ``mode`` is mandatory observability: ``DEGRADED`` means the caller saw a
    failure (partial data or an error) and ``error`` carries a human-readable
    summary; a ``HIT``/``EMPTY`` result must leave ``error`` empty.

    ``raw_items`` mirrors the original store records (same order as
    ``items``) for agents that format multi-field fields (e.g. copywriter's
    ``- {title} (互动率: {rate})`` bullets) — ``items[].body`` alone collapses
    a record to a single string and would lose the field structure.
    """

    model_config = ConfigDict(frozen=True)

    namespace: str
    layer: PromptLayer = PromptLayer.L4_MEMORY
    items: tuple[ContextItem, ...] = ()
    raw_items: tuple[dict[str, Any], ...] = ()
    mode: RetrievalMode = RetrievalMode.EMPTY
    error: str = ""

    @property
    def bodies(self) -> tuple[str, ...]:
        """The recalled bodies in recall order."""
        return tuple(item.body for item in self.items)


class RunContext(BaseModel):
    """Per-superstep execution context, built at the node seam (info.md D1').

    Runtime-only value object: it is passed into agents and never enters the
    LangGraph checkpoint (prd 红线).  ``values`` is the *resolved* state view
    (the hydration layer's output), read-only by convention.
    """

    model_config = ConfigDict(frozen=True)

    thread_id: str
    account_id: str
    niche: str
    workflow_mode: str = "trend"
    phase: str = ""
    topic: str = ""
    values: Mapping[str, Any] = Field(default_factory=dict)
    tool_schema: str = ""
    """Pre-rendered L1 text, or ``""`` for no L1 at all.

    Rendered by the agent from its declared capabilities
    (``BaseAgent.tool_schema_layer()`` → the Tool Runtime's schema renderer)
    and carried here rather than passed beside it, because it is per-run
    context like the rest of this object. The compiler seeds the L1 section
    from it and nowhere else, so the decision "is there a tool layer?" is made
    in one place instead of once per call site.
    """


class CompiledPrompt(BaseModel):
    """Layered compile output, ready for the LLM call."""

    model_config = ConfigDict(frozen=True)

    layers: dict[PromptLayer, str] = Field(default_factory=dict)
    total_token_cost: int = Field(default=0, ge=0)

    def render(self) -> str:
        """Join layers in canonical L0→L5 order (stable prefix first)."""
        return "\n\n".join(self.layers[layer] for layer in LAYER_ORDER if layer in self.layers)
