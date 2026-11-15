"""Deterministic DM qualification and outbound authorization gate.

The DM handler is manual-only, but manual does not mean safe: an operator can
still paste a WeChat id, a phone number, a price the account has not approved,
or a promise about inventory.  The ledger's Phase-2 proposal 11 asks for a
small state machine around the five qualification slots (date, duration,
item tier, budget, pickup region) plus a hard output check.

Everything here is pure and regex-driven.  The service layer decides whether
to send; this module only answers "is the slot set ready?" and "does this
message contain a forbidden commitment?".  Keeping it side-effect free makes
the safety rules testable without a browser, a database, or an LLM.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

MIN_READY_FILL_RATIO = 0.8
DEFAULT_MAX_QUESTIONS = 2


class QualificationSlot(StrEnum):
    DATE = "date"
    DURATION = "duration"
    ITEM_TIER = "item_tier"
    BUDGET = "budget"
    PICKUP_REGION = "pickup_region"


SLOT_LABELS: dict[QualificationSlot, str] = {
    QualificationSlot.DATE: "用车日期",
    QualificationSlot.DURATION: "租期",
    QualificationSlot.ITEM_TIER: "车型/品类",
    QualificationSlot.BUDGET: "预算",
    QualificationSlot.PICKUP_REGION: "取车区域",
}
REQUIRED_SLOTS: tuple[QualificationSlot, ...] = (
    QualificationSlot.DATE,
    QualificationSlot.ITEM_TIER,
    QualificationSlot.PICKUP_REGION,
)
# Highest information gain first; budget and duration are useful but must not
# delay a date/tier/region conversation.
QUESTION_ORDER: tuple[QualificationSlot, ...] = (
    QualificationSlot.DATE,
    QualificationSlot.ITEM_TIER,
    QualificationSlot.PICKUP_REGION,
    QualificationSlot.DURATION,
    QualificationSlot.BUDGET,
)

_DATE_RE = re.compile(
    r"(?:今天|明天|后天|本周[一二三四五六日天]|下周[一二三四五六日天]|"
    r"\d{1,2}\s*月\s*\d{1,2}\s*[日号]|\d{4}[-/]\d{1,2}[-/]\d{1,2})"
)
_DURATION_RE = re.compile(r"\d+\s*(?:天|日|晚|周|个月)")
_TIER_RE = re.compile(
    r"(?:经济型?|舒适型?|豪华型?|SUV|轿车|商务车|跑车|七座|五座|新能源)(?:\s*SUV)?",
    re.IGNORECASE,
)
_BUDGET_RE = re.compile(r"(?:预算|价格|费用)?\s*(\d{2,6}\s*(?:元|块|万))")
_REGION_RE = re.compile(r"(?:在|去|到)?\s*([\u4e00-\u9fa5]{2,8})\s*(?:取车|提车|门店|机场|高铁站)")
_REGION_LABEL_RE = re.compile(r"(?:区域|地点)\s*[:：]\s*([\u4e00-\u9fa5]{2,8})")

_URL_RE = re.compile(r"https?://|www\.", re.IGNORECASE)
_CONTACT_RE = re.compile(
    r"微信|weixin|\bvx\b|v信|加我|手机号|电话号码|1[3-9]\d{9}",
    re.IGNORECASE,
)
_COMMITMENT_RE = re.compile(r"最低价|底价|保证有车|肯定有车|库存充足|一定能提")
_PRICE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:元|块|万)")


@dataclass
class QualificationFSM:
    """The five-slot state plus deterministic extraction and output checks."""

    slots: dict[str, str] = field(default_factory=dict)

    def fill(self, slot: QualificationSlot, value: str) -> bool:
        text = (value or "").strip()
        if not text:
            return False
        key = slot.value
        if self.slots.get(key) == text:
            return False
        self.slots[key] = text
        return True

    def fill_from_text(self, text: str) -> list[QualificationSlot]:
        """Extract any slots present in one inbound message.

        Later observations overwrite earlier ones (the customer corrected
        themselves), except that an empty match never erases a value.
        """
        found: list[QualificationSlot] = []
        raw = text or ""
        extractors: tuple[tuple[QualificationSlot, re.Pattern[str]], ...] = (
            (QualificationSlot.DATE, _DATE_RE),
            (QualificationSlot.DURATION, _DURATION_RE),
            (QualificationSlot.ITEM_TIER, _TIER_RE),
            (QualificationSlot.BUDGET, _BUDGET_RE),
            (QualificationSlot.PICKUP_REGION, _REGION_LABEL_RE),
            (QualificationSlot.PICKUP_REGION, _REGION_RE),
        )
        for slot, pattern in extractors:
            match = pattern.search(raw)
            if match is None:
                continue
            value = match.group(1).strip() if match.groups() else match.group(0).strip()
            if slot is QualificationSlot.BUDGET:
                value = match.group(1).strip()
            if value and self.fill(slot, value):
                found.append(slot)
        return found

    @property
    def fill_ratio(self) -> float:
        return len([slot for slot in QUESTION_ORDER if self.slots.get(slot.value)]) / len(
            QUESTION_ORDER
        )

    def missing(self) -> list[QualificationSlot]:
        return [slot for slot in QUESTION_ORDER if not self.slots.get(slot.value)]

    @property
    def ready(self) -> bool:
        """Required slots present and at least 80% of the five slots filled."""
        if self.fill_ratio < MIN_READY_FILL_RATIO:
            return False
        return all(self.slots.get(slot.value) for slot in REQUIRED_SLOTS)

    def next_questions(self, max_questions: int = DEFAULT_MAX_QUESTIONS) -> list[str]:
        """At most ``max_questions`` labels, highest-gain slot first."""
        questions = [SLOT_LABELS[slot] for slot in QUESTION_ORDER if not self.slots.get(slot.value)]
        return questions[: max(1, max_questions)]

    def to_dict(self) -> dict[str, Any]:
        return {
            "slots": dict(self.slots),
            "missing": [slot.value for slot in self.missing()],
            "fill_ratio": round(self.fill_ratio, 4),
            "ready": self.ready,
            "next_questions": self.next_questions(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> QualificationFSM:
        if not isinstance(data, dict):
            return cls()
        raw = data.get("slots")
        if not isinstance(raw, dict):
            raw = data
        slots: dict[str, str] = {}
        for slot in QUESTION_ORDER:
            value = raw.get(slot.value) or raw.get(slot.name)
            if value:
                slots[slot.value] = str(value)
        return cls(slots=slots)


def gate_outbound(
    fsm: QualificationFSM,
    message: str,
    *,
    known_prices: tuple[float, ...] | list[float] = (),
) -> dict[str, Any]:
    """Check one outbound DM against authorization boundaries.

    A blocked result is *not* a verdict about the customer; it is a list of
    reasons the operator (or the human-review card) must resolve.  The service
    turns denial into a blocked engagement result before the effect ledger is
    even claimed, so nothing is sent and no quota is consumed.
    """
    text = message or ""
    violations: list[str] = []
    if _URL_RE.search(text):
        violations.append("external_link")
    if _CONTACT_RE.search(text):
        violations.append("external_contact")
    if _COMMITMENT_RE.search(text):
        violations.append("unauthorized_commitment")
    allowed_prices = {round(float(price), 2) for price in known_prices}
    for match in _PRICE_RE.finditer(text):
        value = round(float(match.group(1)), 2)
        if value not in allowed_prices:
            violations.append("unverified_price")
            break
    missing = [slot.value for slot in fsm.missing()]
    ready = fsm.ready
    allowed = ready and not violations
    reasons: list[str] = []
    if not ready:
        reasons.append("填写完整的日期、车型/品类与取车区域后才可进入人工确认")
    if violations:
        reasons.append("消息含外链/联系方式/未核实报价或承诺，已拦截")
    return {
        "allowed": allowed,
        "ready": ready,
        "violations": violations,
        "missing_slots": missing,
        "fill_ratio": round(fsm.fill_ratio, 4),
        "reasons": reasons,
        "requires_human_review": ready and not violations,
    }


__all__ = [
    "DEFAULT_MAX_QUESTIONS",
    "MIN_READY_FILL_RATIO",
    "QUESTION_ORDER",
    "REQUIRED_SLOTS",
    "SLOT_LABELS",
    "QualificationFSM",
    "QualificationSlot",
    "gate_outbound",
]
