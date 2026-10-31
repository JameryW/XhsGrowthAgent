"""Post-decide semantic near-dupe hints for the promotion ledger (票 5ac / Q3).

``decide_promotion`` stays pure and key-level only. After a machine verdict whose
``dedupe`` is ``NEEDS_REVIEW``, callers may optionally ``asearch`` the target
namespace and attach a structured hint to ledger ``detail``. The hint never
changes ``disposition`` / ``reason`` / ``dedupe`` and never auto-merges rows.

Cost rule: pay embedding only on that post-decide path (not on every candidate).
When the store or semantic index is missing, or ``asearch`` raises → **skip-hint**
(optionally record ``status=unavailable``); never flip the promotion decision.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from backend.memory.index import semantic_index_status
from backend.memory.promotion import (
    DedupeVerdict,
    PromotionCandidate,
    PromotionDecision,
)

__all__ = [
    "DETAIL_KEY",
    "detail_with_near_dupe_hint",
    "merge_promotion_detail",
    "near_dupe_hint_for",
]

logger = logging.getLogger("xhs_growth.memory.promotion_semantic")

#: Ledger ``detail`` object key for the near-dupe enrichment fragment.
DETAIL_KEY = "semantic_near_dupe"

_DEFAULT_LIMIT = 5


def _namespace(account_id: str, namespace: str) -> tuple[str, str, str]:
    return ("accounts", account_id, namespace)


def _neighbor_from_item(item: Any, *, candidate_key: str) -> dict[str, Any] | None:
    key = getattr(item, "key", None)
    if not isinstance(key, str) or not key or key == candidate_key:
        return None
    neighbor: dict[str, Any] = {"key": key}
    value = getattr(item, "value", None)
    if isinstance(value, dict):
        source_ref = value.get("source_ref")
        if isinstance(source_ref, str) and source_ref.strip():
            neighbor["source_ref"] = source_ref.strip()
        promotion_id = value.get("promotion_id")
        if isinstance(promotion_id, str) and promotion_id.strip():
            neighbor["promotion_id"] = promotion_id.strip()
    score = getattr(item, "score", None)
    if isinstance(score, bool):
        pass
    elif isinstance(score, (int, float)):
        neighbor["score"] = float(score)
    return neighbor


async def near_dupe_hint_for(
    decision: PromotionDecision,
    candidate: PromotionCandidate,
    *,
    store: Any | None,
    account_id: str,
    limit: int = _DEFAULT_LIMIT,
    index_enabled: bool | None = None,
) -> dict[str, Any] | None:
    """Build a ``detail`` fragment when key-level dedupe already needs a person.

    Returns ``None`` when ``dedupe`` is not ``NEEDS_REVIEW`` (no embedding cost).
    Otherwise returns ``{DETAIL_KEY: {...}}`` with ``status`` of ``hits``,
    ``none``, or ``unavailable``. Never raises for search/index failures.
    """
    if decision.dedupe is not DedupeVerdict.NEEDS_REVIEW:
        return None

    enabled = (
        index_enabled if index_enabled is not None else bool(semantic_index_status().get("enabled"))
    )
    if store is None or not enabled:
        return {DETAIL_KEY: {"status": "unavailable"}}

    try:
        items = await store.asearch(
            _namespace(account_id, candidate.namespace),
            query=candidate.body,
            limit=limit,
        )
    except Exception:
        logger.warning(
            "semantic near-dupe asearch failed; skipping hint (decision unchanged)",
            exc_info=True,
        )
        return {DETAIL_KEY: {"status": "unavailable"}}

    neighbors: list[dict[str, Any]] = []
    for item in items or ():
        neighbor = _neighbor_from_item(item, candidate_key=candidate.key)
        if neighbor is not None:
            neighbors.append(neighbor)

    if not neighbors:
        return {DETAIL_KEY: {"status": "none"}}
    return {DETAIL_KEY: {"status": "hits", "neighbors": neighbors}}


def merge_promotion_detail(existing: str, hint: dict[str, Any] | None) -> str:
    """Merge a near-dupe hint into ledger ``detail`` without corrupting plain text.

    Encoding choice (票 5ac):

    - empty ``existing`` → JSON object carrying the hint keys;
    - ``existing`` is a JSON **object** → shallow-merge hint keys (keeps human-
      review / future structured conventions intact);
    - ``existing`` is a plain non-JSON string (e.g. hy degraded error summary) →
      leave unchanged; do not wrap or splice JSON into it.
    """
    if hint is None:
        return existing
    raw = (existing or "").strip()
    if not raw:
        return json.dumps(hint, ensure_ascii=False, sort_keys=True)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return existing
    if not isinstance(parsed, dict):
        return existing
    merged = dict(parsed)
    merged.update(hint)
    return json.dumps(merged, ensure_ascii=False, sort_keys=True)


async def detail_with_near_dupe_hint(
    decision: PromotionDecision,
    candidate: PromotionCandidate,
    *,
    store: Any | None,
    account_id: str,
    existing_detail: str = "",
    limit: int = _DEFAULT_LIMIT,
    index_enabled: bool | None = None,
) -> str:
    """Resolve near-dupe enrichment and merge it into ``existing_detail``."""
    hint = await near_dupe_hint_for(
        decision,
        candidate,
        store=store,
        account_id=account_id,
        limit=limit,
        index_enabled=index_enabled,
    )
    return merge_promotion_detail(existing_detail, hint)
