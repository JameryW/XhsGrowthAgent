"""Context Compiler pipeline skeleton (P1b-S1, zero behavior change).

The stages are pure, deterministic functions (info.md D6': no LLM rerank).
Recall wiring arrives in S2 (with the store and the degradation events) and
layered prompt-YAML wiring in S3; nothing imports this module yet — the S4
migration replaces the per-agent ``template.replace`` paths with
:meth:`ContextCompiler.compile` in the consumer-map order.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC

from backend.context.estimator import estimate_tokens
from backend.context.models import (
    LAYER_ORDER,
    CompiledPrompt,
    ContextItem,
    PromptLayer,
    RetrievalResult,
    RunContext,
)

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
    timestamp = item.timestamp
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return (0, -timestamp.timestamp())


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
        score = item.confidence if item.ranking_score is None else item.ranking_score
        effective = score * weights.get(item.source, 1.0)
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
            candidates = [i for i, item in enumerate(trimmed[layer]) if not item.required]
            if not candidates:
                break
            index = candidates[-1]
            trimmed[layer] = trimmed[layer][:index] + trimmed[layer][index + 1 :]
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

        ``run_context`` is accepted now so the signature is stable for S2/S3
        (the compiler will read niche/task context from it instead of taking
        pre-rendered L2/L3 strings); it does not influence the S1 output.
        """
        items_by_layer: dict[PromptLayer, list[ContextItem]] = {}
        for result in retrievals:
            items_by_layer.setdefault(result.layer, []).extend(result.items)
        merged = {
            layer: dedup_items(rerank_items(tuple(items), source_weights))
            for layer, items in items_by_layer.items()
        }

        def render() -> CompiledPrompt:
            layers: dict[PromptLayer, str] = {}
            for layer in LAYER_ORDER:
                section = sections.get(layer, "")
                bodies = [item.body for item in merged.get(layer, ())]
                text = "\n".join(part for part in (section, *bodies) if part)
                if text:
                    layers[layer] = text
            text = "\n\n".join(layers.values())
            return CompiledPrompt(layers=layers, total_token_cost=estimate_tokens(text))

        prompt = render()
        if budget is not None:
            if budget < 1:
                raise ValueError("Context budget must be positive")
            for layer in _TRIM_ORDER:
                while prompt.total_token_cost > budget:
                    items = merged.get(layer, ())
                    candidates = [i for i, item in enumerate(items) if not item.required]
                    if not candidates:
                        break
                    index = candidates[-1]
                    merged[layer] = items[:index] + items[index + 1 :]
                    prompt = render()
            if prompt.total_token_cost > budget:
                raise ValueError("Required context exceeds token budget")
        return prompt
