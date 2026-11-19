"""Span-level learning from human revisions (PORT).

The evaluator already returns free-form revision hints.  This module turns the
*actual* human-approved rewrite into small old→new spans so later drafts can
reuse a correction without replaying the whole editing session.

The functions are deterministic and side-effect free.  The two async helpers
persist the learned spans in the account store; callers treat failures as
best-effort and never block a publish decision on them.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from difflib import SequenceMatcher
from typing import Any

logger = logging.getLogger("xhs_growth.services.port")

MAX_SPAN_CHARS = 160
MAX_LEARNED_SPANS = 120
MIN_SUPPORT_FOR_REUSE = 2

PORT_NAMESPACE_SUFFIX = "port_learning"


@dataclass(frozen=True)
class PortSpan:
    """One reusable fragment-level correction."""

    old: str
    new: str
    reason: str = ""
    support: int = 1
    last_seen: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "old": self.old,
            "new": self.new,
            "reason": self.reason,
            "support": self.support,
            "last_seen": self.last_seen,
        }


@dataclass(frozen=True)
class PortLearningResult:
    spans: tuple[PortSpan, ...] = field(default_factory=tuple)
    applied: tuple[PortSpan, ...] = field(default_factory=tuple)
    text: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "spans": [span.as_dict() for span in self.spans],
            "applied": [span.as_dict() for span in self.applied],
            "text": self.text,
        }


def normalize_fragment(value: str) -> str:
    """Collapse whitespace so the same edit matches across line wrapping."""
    return " ".join(str(value or "").split())


def _clip(value: str) -> str:
    value = normalize_fragment(value)
    if len(value) <= MAX_SPAN_CHARS:
        return value
    return value[: MAX_SPAN_CHARS - 1] + "…"


def mine_span_revisions(
    old_text: str,
    new_text: str,
    *,
    max_spans: int = 8,
    min_chars: int = 2,
) -> list[PortSpan]:
    """Extract replacement spans between two drafts.

    Pure insertions/deletions are skipped: applying them to a different draft
    is too likely to produce a broken sentence, while replaced fragments carry
    a reusable local convention (e.g. a weaker hook for a concrete benefit).
    """
    old = str(old_text or "")
    new = str(new_text or "")
    if not old or not new or old == new:
        return []
    matcher = SequenceMatcher(None, old, new, autojunk=False)
    spans: list[PortSpan] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "replace":
            continue
        old_span = old[i1:i2].strip()
        new_span = new[j1:j2].strip()
        if len(old_span) < min_chars or len(new_span) < min_chars:
            continue
        spans.append(PortSpan(old=_clip(old_span), new=_clip(new_span)))
        if len(spans) >= max_spans:
            break
    return spans


def merge_port_memory(
    existing: Iterable[Mapping[str, Any] | PortSpan] | None,
    revisions: Iterable[PortSpan],
    *,
    max_entries: int = MAX_LEARNED_SPANS,
    now: datetime | None = None,
) -> list[PortSpan]:
    """Merge new corrections into learned memory and age-out rare entries."""
    stamp = (now or datetime.now(UTC)).isoformat()
    merged: dict[str, PortSpan] = {}
    for raw in existing or ():
        if isinstance(raw, PortSpan):
            key = normalize_fragment(raw.old)
            if key:
                merged[key] = PortSpan(
                    old=key,
                    new=normalize_fragment(raw.new),
                    reason=raw.reason,
                    support=max(1, raw.support),
                    last_seen=raw.last_seen,
                )
            continue
        key = normalize_fragment(str(raw.get("old") or ""))
        if not key:
            continue
        merged[key] = PortSpan(
            old=key,
            new=normalize_fragment(str(raw.get("new") or "")),
            reason=str(raw.get("reason") or ""),
            support=max(1, int(raw.get("support") or 1)),
            last_seen=str(raw.get("last_seen") or ""),
        )
    for revision in revisions:
        key = normalize_fragment(revision.old)
        if not key or not revision.new:
            continue
        prior = merged.get(key)
        merged[key] = PortSpan(
            old=key,
            new=revision.new,
            reason=revision.reason or (prior.reason if prior else ""),
            support=(prior.support if prior else 0) + 1,
            last_seen=stamp,
        )
    ordered = sorted(
        merged.values(),
        key=lambda span: (span.support, span.last_seen),
        reverse=True,
    )
    return ordered[:max_entries]


def apply_port_memory(
    text: str,
    memory: Iterable[Mapping[str, Any]],
    *,
    min_support: int = MIN_SUPPORT_FOR_REUSE,
    max_applications: int = 5,
) -> PortLearningResult:
    """Apply only repeatedly observed corrections, never a one-off edit."""
    updated = str(text or "")
    applied: list[PortSpan] = []
    candidates = sorted(
        (
            span
            for span in (
                PortSpan(
                    old=normalize_fragment(str(raw.get("old") or "")),
                    new=normalize_fragment(str(raw.get("new") or "")),
                    reason=str(raw.get("reason") or ""),
                    support=max(1, int(raw.get("support") or 1)),
                    last_seen=str(raw.get("last_seen") or ""),
                )
                for raw in memory
            )
            if span.old and span.new and span.support >= min_support
        ),
        key=lambda span: span.support,
        reverse=True,
    )
    for span in candidates:
        if len(applied) >= max_applications:
            break
        if span.old not in updated or span.old == span.new:
            continue
        updated = updated.replace(span.old, span.new)
        applied.append(span)
    return PortLearningResult(
        spans=tuple(candidates),
        applied=tuple(applied),
        text=updated,
    )


def _memory_namespace(account_id: str) -> tuple[str, ...]:
    return ("accounts", account_id or "default", PORT_NAMESPACE_SUFFIX)


async def load_port_memory(store: Any, account_id: str) -> list[dict[str, Any]]:
    """Read learned spans; a missing store/record is simply empty memory."""
    if store is None:
        return []
    try:
        item = await store.aget(_memory_namespace(account_id), "spans")
    except Exception as exc:  # pragma: no cover - defensive store boundary
        logger.debug("port memory read skipped: %s", exc)
        return []
    value = getattr(item, "value", None) if item is not None else None
    if not isinstance(value, dict):
        return []
    spans = value.get("spans")
    return [dict(span) for span in spans or [] if isinstance(span, Mapping)]


async def save_port_memory(store: Any, account_id: str, spans: list[PortSpan]) -> None:
    """Persist learned spans; callers treat this as best-effort."""
    if store is None:
        return
    try:
        await store.aput(
            _memory_namespace(account_id),
            "spans",
            {"spans": [span.as_dict() for span in spans]},
        )
    except Exception as exc:  # pragma: no cover - defensive store boundary
        logger.debug("port memory write skipped: %s", exc)
        raise
