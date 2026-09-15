"""Context Compiler pipeline (P1b-S1 skeleton; S2/S3 wired the recall and the
segmented prompt YAML, P1c-S4 feeds the L1 tool-schema layer).

The stages are pure, deterministic functions (info.md D6': no LLM rerank).
``compile_prompt`` is the entry point agents use: it parses the (segmented)
prompt YAML and delegates the dedup / rerank / budget / ordering work below.
"""

from __future__ import annotations

from collections.abc import Mapping

from backend.context.estimator import estimate_tokens
from backend.context.models import (
    LAYER_ORDER,
    CompiledPrompt,
    ContextItem,
    PromptLayer,
    RetrievalResult,
    RunContext,
)
from backend.context.segments import parse_system_segments

# Budget trimming pulls from the tail of the stability order (L5 first, then
# L4); L0-L3 are static context and are never trimmed (info.md D4').
_TRIM_ORDER: tuple[PromptLayer, ...] = (
    PromptLayer.L5_OBSERVATION,
    PromptLayer.L4_MEMORY,
)


def dedup_items(items: tuple[ContextItem, ...]) -> tuple[ContextItem, ...]:
    """Order-stable dedup by ``(source, body)`` — first occurrence wins."""
    seen: set[tuple[str, str]] = set()
    unique: list[ContextItem] = []
    for item in items:
        key = (item.source, item.body)
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return tuple(unique)


def _recency_key(item: ContextItem) -> tuple[int, float]:
    """Sort key for recency, ascending = newest first, ``None`` last.

    Timestamped items get ``(0, -epoch)`` so newer (larger epoch → more
    negative key) sorts first; ``None`` timestamps get ``(1, 0.0)`` and sort
    last (oldest).  Epoch conversion keeps the key a plain float; naive
    datetimes resolve against the local timezone, which is fine for ordering
    purposes and keeps the sort total.
    """
    if item.timestamp is None:
        return (1, 0.0)
    return (0, -item.timestamp.timestamp())


def rerank_items(
    items: tuple[ContextItem, ...],
    source_weights: Mapping[str, float] | None = None,
) -> tuple[ContextItem, ...]:
    """Deterministic rerank (info.md D6').

    Order: ``priority`` desc, then effective confidence (``confidence``
    scaled by an optional per-source weight) desc, then recency desc.  The
    sort is stable, so equal keys keep recall order.
    """
    weights = source_weights or {}

    def key(item: ContextItem) -> tuple[int, float, tuple[int, float]]:
        effective = item.confidence * weights.get(item.source, 1.0)
        return (-item.priority, -effective, _recency_key(item))

    return tuple(sorted(items, key=key))


def apply_item_budget(
    items_by_layer: Mapping[PromptLayer, tuple[ContextItem, ...]],
    budget: int,
    *,
    reserved: int = 0,
) -> dict[PromptLayer, tuple[ContextItem, ...]]:
    """Drop items from the tail of :data:`_TRIM_ORDER` until under budget.

    ``reserved`` is the estimated cost of the static layers (L0-L3) — the
    budget applies to the whole prompt, so items may only spend what is left
    after it.  Reranked layers are ordered best-first, so "drop from the
    tail" drops the lowest-priority / least-confident / stalest item first.
    Static layers themselves are never trimmed.  Stops early once the
    estimated total fits (or nothing droppable remains).
    """

    def total(mapping: Mapping[PromptLayer, tuple[ContextItem, ...]]) -> int:
        return sum(estimate_tokens(item.body) for items in mapping.values() for item in items)

    trimmed = {layer: items for layer, items in items_by_layer.items()}
    for layer in _TRIM_ORDER:
        while total(trimmed) + reserved > budget and trimmed.get(layer):
            trimmed[layer] = trimmed[layer][:-1]
    return trimmed


class ContextCompiler:
    """Assembles the final layered prompt (S1 skeleton: pure assembly).

    The caller supplies the static layer texts (L0-L3 until S3 introduces the
    segmented prompt YAML) and the recall outcomes; the compiler dedups and
    reranks the item layers, applies the optional token budget (L5→L4), and
    renders everything in canonical L0→L5 order.
    """

    def compile(
        self,
        run_context: RunContext,
        sections: Mapping[PromptLayer, str],
        retrievals: tuple[RetrievalResult, ...] = (),
        *,
        budget: int | None = None,
        source_weights: Mapping[str, float] | None = None,
    ) -> CompiledPrompt:
        """Compile static sections + recall items into a layered prompt.

        ``run_context`` supplies the L1 section (``tool_schema``): the layer is
        the one static layer the prompt YAML cannot carry, because it is
        *rendered* from the capability registry rather than written by hand.
        Seeding it here rather than at each call site keeps "where does L1 go?"
        a single decision — the LAYER_ORDER rendering below already places it
        between L0 and L2, and the trim order below never touches it.
        """
        if run_context.tool_schema:
            seeded = dict(sections)
            existing = seeded.get(PromptLayer.L1_TOOL_SCHEMA, "")
            seeded[PromptLayer.L1_TOOL_SCHEMA] = "\n".join(
                part for part in (existing, run_context.tool_schema) if part
            )
            sections = seeded
        items_by_layer: dict[PromptLayer, list[ContextItem]] = {}
        for result in retrievals:
            items_by_layer.setdefault(result.layer, []).extend(result.items)
        merged = {
            layer: rerank_items(dedup_items(tuple(items)), source_weights)
            for layer, items in items_by_layer.items()
        }
        if budget is not None:
            reserved = sum(estimate_tokens(text) for text in sections.values())
            merged = apply_item_budget(merged, budget, reserved=reserved)

        layers: dict[PromptLayer, str] = {}
        total = 0
        for layer in LAYER_ORDER:
            section = sections.get(layer, "")
            bodies = [item.body for item in merged.get(layer, ())]
            text = "\n".join(part for part in (section, *bodies) if part)
            if text:
                layers[layer] = text
                total += estimate_tokens(text)
        return CompiledPrompt(layers=layers, total_token_cost=total)

    def compile_prompt(
        self,
        run_context: RunContext,
        system_text: str,
        user_template: str = "",
        retrievals: tuple[RetrievalResult, ...] = (),
        *,
        budget: int | None = None,
        source_weights: Mapping[str, float] | None = None,
    ) -> CompiledPrompt:
        """Compile a (segmented) prompt YAML pair into a layered prompt.

        S3 entry point: ``system_text`` is parsed by the segment schema
        (markers -> L0-L5; no markers -> single L0, so unsegmented YAML keeps
        compiling byte-identically), and ``user_template`` becomes the L3
        task layer (appended to any L3 segment the system text carries).
        Everything else — dedup, rerank, budget (L5 first), rendering — is
        the S1 :meth:`compile` path.
        """
        sections = parse_system_segments(system_text)
        if user_template:
            existing = sections.get(PromptLayer.L3_TASK, "")
            sections[PromptLayer.L3_TASK] = "\n\n".join(
                part for part in (existing, user_template) if part
            )
        return self.compile(
            run_context,
            sections,
            retrievals,
            budget=budget,
            source_weights=source_weights,
        )
