"""Outgoing reply guard for the manual engagement tools (ledger schemes #59, #94).

One outgoing text, two deterministic contracts, checked before anything is sent:

* ``filter_unusable_reply`` (ledger #59) blocks replies that claim an action the
  run never performed (an ``已帮您锁定`` with no tool receipt behind it) and
  replies that carry no information at all (亲亲稍等, 私信您啦).
* ``build_presupposition_safe_reply`` (ledger #94) drops clauses that assert a
  sensitive attribute the customer never raised this turn — the "看您上次带老人
  小孩预算比较紧" shape, where persistent memory leaks back into the reply.

The two are composed here rather than in the tools because the decision is the
same decision: *may this text leave the building, and verbatim or edited?* The
module is pure: no LLM, no network, no state, no clock. Callers pass the text
plus optional tool receipts and get back either the text to send or a refusal.

Switch: :data:`REPLY_GUARD_ENV`. Default off — when the switch is off
``guard_reply_if_enabled`` reports ``checked=False`` and the caller must behave
exactly as before.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from backend.services.decision_contracts import (
    ActionClaim,
    ToolReceipt,
    filter_unusable_reply,
)
from backend.services.memory_contracts import (
    PresuppositionFinding,
    SensitiveAttribute,
    build_presupposition_safe_reply,
)

logger = logging.getLogger("xhs_growth.services.reply_guard")

__all__ = [
    "REPLY_GUARD_ENV",
    "ReplyGuardReport",
    "default_sensitive_attributes",
    "guard_reply",
    "guard_reply_if_enabled",
    "reply_guard_enabled",
]

#: Opt-in switch for the two manual engagement tools.
REPLY_GUARD_ENV = "XHS_REPLY_GUARD"

_TRUTHY = frozenset({"1", "true", "yes", "on"})

#: Attributes a rental/travel DM must not assert unless the customer raised them.
#:
#: Deliberately short and concrete: only phrases a reply would have to *restate*
#: to be useful.  ``term in mentioned_terms`` disables a hit, so a customer who
#: says 带孩子 themselves keeps the topic legal for the rest of the reply.
_DEFAULT_ATTRIBUTES: tuple[SensitiveAttribute, ...] = (
    SensitiveAttribute(
        label="family",
        terms=("带老人", "带孩子", "带小孩", "一家人", "亲子"),
        severity="high",
    ),
    SensitiveAttribute(
        label="health",
        terms=("高反", "高原反应", "晕车", "身体不好"),
        severity="high",
    ),
    SensitiveAttribute(
        label="budget",
        terms=("预算比较紧", "预算紧", "预算有限", "经济型"),
        severity="medium",
    ),
    SensitiveAttribute(
        label="occupation",
        terms=("学生党", "宝妈", "上班族"),
        severity="low",
    ),
)


@dataclass(frozen=True)
class ReplyGuardReport:
    """The verdict for one outgoing text.

    ``text`` is what may be sent: the original text when nothing was scrubbed,
    the clause-pruned text when a presupposition was dropped, and an empty
    string when the reply is blocked (callers must not send it at all).
    """

    checked: bool
    blocked: bool
    original_text: str
    text: str
    reasons: tuple[str, ...] = ()
    claims: tuple[ActionClaim, ...] = ()
    missing_receipts: tuple[str, ...] = ()
    findings: tuple[PresuppositionFinding, ...] = ()
    scrubbed: bool = False
    removed_clauses: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "checked": self.checked,
            "blocked": self.blocked,
            "reasons": list(self.reasons),
            "claims": [claim.as_dict() for claim in self.claims],
            "missing_receipts": list(self.missing_receipts),
            "findings": [finding.as_dict() for finding in self.findings],
            "scrubbed": self.scrubbed,
            "removed_clauses": self.removed_clauses,
            "text": self.text,
            "original_text": self.original_text,
        }


def reply_guard_enabled() -> bool:
    """Whether the opt-in switch is on (``1/true/yes/on``)."""

    return os.environ.get(REPLY_GUARD_ENV, "").strip().lower() in _TRUTHY


def default_sensitive_attributes() -> tuple[SensitiveAttribute, ...]:
    """The built-in attribute list, for callers that want to extend it."""

    return _DEFAULT_ATTRIBUTES


def _unchecked(text: str) -> ReplyGuardReport:
    return ReplyGuardReport(checked=False, blocked=False, original_text=text, text=text)


def _dedupe(reasons: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(reasons))


def guard_reply(
    text: str,
    *,
    receipts: Iterable[ToolReceipt | Mapping[str, Any]] | None = None,
    customer_question: str = "",
    attributes: Sequence[SensitiveAttribute] | None = None,
    mentioned_terms: Iterable[str] = (),
    allowed_labels: Iterable[str] = (),
    min_chars: int = 12,
) -> ReplyGuardReport:
    """Check one outgoing reply; return the text to send, or a refusal.

    ``receipts`` are the tool receipts this run actually holds.  A completion
    claim matching none of them is blocked — that is the whole point of #59:
    the guard cannot verify a claim against a platform it never called, so it
    requires the caller to hand over evidence instead of trusting the wording.

    Presupposition hits are scrubbed rather than blocked, except when the scrub
    leaves nothing to say: an empty or content-free remainder is a refusal, not
    a sendable message.
    """

    original = str(text or "")
    unused = filter_unusable_reply(
        original,
        receipts=receipts,
        customer_question=customer_question,
        min_chars=min_chars,
    )
    attrs = tuple(attributes) if attributes is not None else _DEFAULT_ATTRIBUTES
    presupposition = build_presupposition_safe_reply(
        original,
        attrs,
        mentioned_terms=mentioned_terms,
        allowed_labels=allowed_labels,
    )

    reasons: list[str] = list(unused.reasons)
    blocked = unused.blocked
    scrubbed = bool(presupposition.findings)
    safe_text = presupposition.safe_draft if scrubbed else original

    if scrubbed:
        reasons.append("presupposed_sensitive_attribute")
        if not safe_text.strip():
            blocked = True
            reasons.append("presupposition_scrub_emptied_reply")
            safe_text = ""

    if scrubbed and not blocked:
        after = filter_unusable_reply(
            safe_text,
            receipts=receipts,
            customer_question=customer_question,
            min_chars=min_chars,
        )
        if after.hollow:
            blocked = True
            reasons.append("hollow_reply_after_scrub")

    report = ReplyGuardReport(
        checked=True,
        blocked=blocked,
        original_text=original,
        text="" if blocked else safe_text,
        reasons=_dedupe(reasons),
        claims=unused.claims,
        missing_receipts=unused.missing_receipts,
        findings=presupposition.findings,
        scrubbed=scrubbed,
        removed_clauses=presupposition.removed_clauses,
    )
    if blocked:
        logger.warning(
            "出站话术护栏拦截回复: %s",
            ", ".join(report.reasons) or "unknown",
        )
    return report


def guard_reply_if_enabled(
    text: str,
    *,
    receipts: Iterable[ToolReceipt | Mapping[str, Any]] | None = None,
    customer_question: str = "",
    attributes: Sequence[SensitiveAttribute] | None = None,
    mentioned_terms: Iterable[str] = (),
    allowed_labels: Iterable[str] = (),
    min_chars: int = 12,
) -> ReplyGuardReport:
    """Run :func:`guard_reply` only when the switch is on; otherwise report unchecked."""

    if not reply_guard_enabled():
        return _unchecked(str(text or ""))
    return guard_reply(
        text,
        receipts=receipts,
        customer_question=customer_question,
        attributes=attributes,
        mentioned_terms=mentioned_terms,
        allowed_labels=allowed_labels,
        min_chars=min_chars,
    )
