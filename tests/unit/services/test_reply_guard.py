"""Unit tests for the outgoing reply guard (ledger #59 + #94)."""

from __future__ import annotations

from backend.services.decision_contracts import ToolReceipt
from backend.services.reply_guard import (
    REPLY_GUARD_ENV,
    default_sensitive_attributes,
    guard_reply,
    guard_reply_if_enabled,
    reply_guard_enabled,
)

CLEAN_REPLY = "国庆档期还有 3 台车，可以先看下路线再定。"

CLAIM_REPLY = "已帮您查好 10 月 3 号的档期，还有 2 台车。"

PRESUPPOSITION_REPLY = "看您上次带老人小孩，这次还选经济型吗？国庆档期还剩 3 台车，随时可以定。"


class TestSwitch:
    def test_default_is_off(self, monkeypatch) -> None:
        monkeypatch.delenv(REPLY_GUARD_ENV, raising=False)
        assert reply_guard_enabled() is False

    def test_truthy_values_turn_it_on(self, monkeypatch) -> None:
        for value in ("1", "true", "YES", "on"):
            monkeypatch.setenv(REPLY_GUARD_ENV, value)
            assert reply_guard_enabled() is True

    def test_disabled_guard_reports_unchecked_and_keeps_the_text(self, monkeypatch) -> None:
        monkeypatch.delenv(REPLY_GUARD_ENV, raising=False)
        report = guard_reply_if_enabled(CLAIM_REPLY)
        assert report.checked is False
        assert report.blocked is False
        assert report.text == CLAIM_REPLY

    def test_enabled_guard_runs_the_real_check(self, monkeypatch) -> None:
        monkeypatch.setenv(REPLY_GUARD_ENV, "1")
        report = guard_reply_if_enabled(CLAIM_REPLY)
        assert report.checked is True
        assert report.blocked is True


class TestUnusableReplies:
    def test_completion_claim_without_a_receipt_is_blocked(self) -> None:
        report = guard_reply(CLAIM_REPLY)
        assert report.blocked is True
        assert "action_claim_without_receipt" in report.reasons
        assert report.missing_receipts == ("claim-1",)
        assert report.text == ""

    def test_matching_success_receipt_lets_the_claim_through(self) -> None:
        receipt = ToolReceipt(action="查好档期", status="succeeded", entity_id="schedule-1")
        report = guard_reply(CLAIM_REPLY, receipts=[receipt])
        assert report.blocked is False
        assert report.missing_receipts == ()
        assert report.text == CLAIM_REPLY

    def test_mapping_receipts_are_accepted(self) -> None:
        report = guard_reply(
            CLAIM_REPLY,
            receipts=[{"action": "查好档期", "status": "ok", "entity_id": "schedule-1"}],
        )
        assert report.blocked is False

    def test_receipt_without_entity_or_detail_is_not_success(self) -> None:
        report = guard_reply(
            CLAIM_REPLY,
            receipts=[ToolReceipt(action="查好档期", status="succeeded")],
        )
        assert report.blocked is True
        assert report.missing_receipts == ("claim-1",)

    def test_hollow_reply_is_blocked(self) -> None:
        report = guard_reply("亲亲稍等")
        assert report.blocked is True
        assert "hollow_reply" in report.reasons

    def test_empty_reply_is_blocked(self) -> None:
        report = guard_reply("   ")
        assert report.blocked is True
        assert "hollow_reply" in report.reasons


class TestPresuppositionScrub:
    def test_unraised_sensitive_attribute_is_scrubbed_not_blocked(self) -> None:
        report = guard_reply(PRESUPPOSITION_REPLY)
        assert report.blocked is False
        assert report.scrubbed is True
        assert report.removed_clauses == 2
        assert "presupposed_sensitive_attribute" in report.reasons
        assert "带老人" not in report.text
        assert "经济型" not in report.text
        assert "国庆档期还剩 3 台车" in report.text

    def test_mentioned_terms_keep_the_attribute_legal(self) -> None:
        report = guard_reply(PRESUPPOSITION_REPLY, mentioned_terms=("带老人", "经济型"))
        assert report.scrubbed is False
        assert report.text == PRESUPPOSITION_REPLY

    def test_allowed_labels_skip_a_whole_attribute(self) -> None:
        report = guard_reply(PRESUPPOSITION_REPLY, allowed_labels=("budget", "family"))
        assert report.scrubbed is False

    def test_scrub_that_empties_the_reply_is_blocked(self) -> None:
        report = guard_reply("看您上次带孩子来")
        assert report.blocked is True
        assert report.text == ""
        assert "presupposition_scrub_emptied_reply" in report.reasons

    def test_scrub_that_leaves_only_filler_is_blocked(self) -> None:
        report = guard_reply("看您上次带孩子来，亲亲稍等")
        assert report.blocked is True
        assert "hollow_reply_after_scrub" in report.reasons

    def test_default_attributes_cover_the_four_domains(self) -> None:
        labels = {attribute.label for attribute in default_sensitive_attributes()}
        assert labels == {"family", "health", "budget", "occupation"}


class TestReport:
    def test_report_serialises_both_texts_and_evidence(self) -> None:
        receipt = ToolReceipt(action="查好档期", status="succeeded", entity_id="schedule-1")
        payload = guard_reply(CLAIM_REPLY, receipts=[receipt]).as_dict()
        assert payload["checked"] is True
        assert payload["blocked"] is False
        assert payload["text"] == CLAIM_REPLY
        assert payload["original_text"] == CLAIM_REPLY
        assert payload["claims"][0]["action"] == "查好"
        assert payload["findings"] == []

    def test_clean_reply_keeps_the_original_text(self) -> None:
        report = guard_reply(CLEAN_REPLY)
        assert report.blocked is False
        assert report.scrubbed is False
        assert report.reasons == ()
        assert report.text == CLEAN_REPLY
