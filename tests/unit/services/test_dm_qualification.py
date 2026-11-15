"""Deterministic DM qualification slots and outbound authorization gate."""

from __future__ import annotations

from backend.services.dm_qualification import (
    QualificationFSM,
    QualificationSlot,
    gate_outbound,
)


def _ready_fsm() -> QualificationFSM:
    fsm = QualificationFSM()
    fsm.fill(QualificationSlot.DATE, "明天")
    fsm.fill(QualificationSlot.ITEM_TIER, "经济型 SUV")
    fsm.fill(QualificationSlot.PICKUP_REGION, "北京机场")
    fsm.fill(QualificationSlot.DURATION, "3 天")
    return fsm


def test_slots_extract_required_qualification_and_ready() -> None:
    fsm = QualificationFSM()
    found = fsm.fill_from_text("明天 经济型 SUV，北京机场取车，预算 300 元，租 3 天")

    assert found
    assert fsm.slots["date"] == "明天"
    assert fsm.slots["item_tier"] == "经济型 SUV"
    assert fsm.slots["pickup_region"] == "北京机场"
    assert fsm.slots["budget"] == "300 元"
    assert fsm.ready is True
    assert fsm.next_questions() == []


def test_incomplete_slots_block_and_ask_at_most_two_questions() -> None:
    fsm = QualificationFSM()

    gate = gate_outbound(fsm, "您好，请问有什么可以帮您？")

    assert gate["allowed"] is False
    assert gate["ready"] is False
    assert gate["requires_human_review"] is False
    assert len(fsm.next_questions()) == 2


def test_safe_ready_message_is_allowed() -> None:
    gate = gate_outbound(_ready_fsm(), "明天经济型 SUV 北京机场取车，可以安排。")

    assert gate["allowed"] is True
    assert gate["ready"] is True
    assert gate["requires_human_review"] is True
    assert gate["violations"] == []


def test_external_contact_and_unverified_price_are_blocked() -> None:
    fsm = _ready_fsm()

    contact = gate_outbound(fsm, "加我微信 vx123，明天取车。")
    price = gate_outbound(fsm, "这个车 999 元一天。", known_prices=(500.0,))
    known = gate_outbound(fsm, "这个车 500 元一天。", known_prices=(500.0,))

    assert "external_contact" in contact["violations"]
    assert contact["allowed"] is False
    assert "unverified_price" in price["violations"]
    assert known["allowed"] is True


def test_state_round_trips_for_the_tool_boundary() -> None:
    fsm = _ready_fsm()
    restored = QualificationFSM.from_dict(fsm.to_dict())

    assert restored.slots == fsm.slots
    assert restored.ready is True
