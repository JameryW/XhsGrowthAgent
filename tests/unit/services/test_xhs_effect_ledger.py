"""票 5c：§5 Effect 账本 + §5.2/§5.3 状态机语义。

钉住的口径（每条对应 spec 一句话）：
- §4.1 键从效果算（同内容同键 / 异内容异键），16 位 hex 摘要在键里；
- §5.1 先 claim 再动手，审批三件套进 intent 行；
- §5.2 重复键提交前拒绝且账本可查；intent 不可重试（先和解）；
- §5.2/§5.3 unknown 只能经读回离开；refused 是终局；
- 重臂只对 resolved_not_sent 开放（读回证明未发出）。
"""

from __future__ import annotations

import pytest

from backend.db.engagement_effects import _reset_memory_store
from backend.services.xhs_effect_ledger import (
    CAPABILITY_BY_KIND,
    LEGAL_TRANSITIONS,
    TERMINAL_STATES,
    EffectAlreadyClaimedError,
    EffectKind,
    EffectNotFoundError,
    EffectState,
    EffectStateConflictError,
    EngagementApproval,
    EngagementEffectLedger,
    IllegalEffectTransitionError,
    effect_idempotency_key,
    payload_digest_for,
)


@pytest.fixture(autouse=True)
def _clean_effects():
    _reset_memory_store()
    yield
    _reset_memory_store()


@pytest.fixture()
def ledger() -> EngagementEffectLedger:
    return EngagementEffectLedger()


def _approval() -> EngagementApproval:
    return EngagementApproval(
        thread_id="thread-1", approved_by="operator-1", approved_at="2026-10-13T00:00:00+00:00"
    )


async def _claim(ledger: EngagementEffectLedger, *, content: str = "你好"):
    return await ledger.claim_intent(
        kind=EffectKind.DM,
        account_id="acct-1",
        target_id="sender-1",
        content=content,
        approval=_approval(),
    )


# -- §4.1 键 ------------------------------------------------------------


class TestTheKeyIsDerivedFromTheEffect:
    def test_same_effect_yields_the_same_key(self):
        a = effect_idempotency_key(EffectKind.DM, "acct-1", "sender-1", "你好")
        b = effect_idempotency_key(EffectKind.DM, "acct-1", "sender-1", "你好")
        assert a == b

    def test_different_content_yields_a_different_key(self):
        a = effect_idempotency_key(EffectKind.DM, "acct-1", "sender-1", "你好")
        b = effect_idempotency_key(EffectKind.DM, "acct-1", "sender-1", "你好！")
        assert a != b

    def test_key_shape_is_the_spec_formula(self):
        key = effect_idempotency_key(EffectKind.COMMENT_REPLY, "acct-1", "cmt-9", "你好")
        digest = payload_digest_for("你好")
        assert key == f"eng:comment_reply:acct-1:cmt-9:{digest}"

    def test_digest_is_16_hex(self):
        digest = payload_digest_for("你好")
        assert len(digest) == 16
        assert set(digest) <= set("0123456789abcdef")

    def test_kind_and_target_discriminate(self):
        base = effect_idempotency_key(EffectKind.DM, "acct-1", "sender-1", "你好")
        other_kind = effect_idempotency_key(EffectKind.COMMENT_REPLY, "acct-1", "sender-1", "你好")
        other_target = effect_idempotency_key(EffectKind.DM, "acct-1", "sender-2", "你好")
        assert base != other_kind
        assert base != other_target

    def test_the_row_digest_is_the_key_digest(self):
        """账本自审计：键可以从行上复算。"""
        key = effect_idempotency_key(EffectKind.DM, "acct-1", "sender-1", "你好")
        assert key.endswith(payload_digest_for("你好"))


# -- §5.1 claim：先记账再动手 -------------------------------------------


class TestClaimWritesTheIntentRowBeforeAnySubmit:
    async def test_claim_records_intent_with_approval_and_capability(self, ledger):
        row = await _claim(ledger)
        assert row.state == EffectState.INTENT.value
        assert row.capability == CAPABILITY_BY_KIND[EffectKind.DM]
        assert row.target_id == "sender-1"
        assert row.thread_id == "thread-1"
        assert row.approved_by == "operator-1"
        assert row.approved_at == "2026-10-13T00:00:00+00:00"
        assert row.payload_digest == payload_digest_for("你好")
        # §5.4：没有平台回显就没有回执
        assert row.receipt_id == ""
        assert row.receipt_source == "none"

    async def test_the_row_is_queryable_from_the_ledger(self, ledger):
        row = await _claim(ledger)
        found = await ledger.get(row.account_id, row.idempotency_key)
        assert found is not None
        assert found.idempotency_key == row.idempotency_key

    def test_approval_fields_must_not_be_empty(self):
        with pytest.raises(ValueError):
            EngagementApproval(thread_id="", approved_by="op", approved_at="t")
        with pytest.raises(ValueError):
            EngagementApproval(thread_id="th", approved_by="", approved_at="t")
        with pytest.raises(ValueError):
            EngagementApproval(thread_id="th", approved_by="op", approved_at="")


# -- §5.2 重复键提交前拒绝 ----------------------------------------------


class TestDuplicateKeysAreRefusedBeforeSubmit:
    async def test_second_claim_is_refused_and_the_ledger_is_queryable(self, ledger):
        first = await _claim(ledger)
        with pytest.raises(EffectAlreadyClaimedError) as excinfo:
            await _claim(ledger)
        existing = excinfo.value.existing
        assert existing.idempotency_key == first.idempotency_key
        assert existing.state == EffectState.INTENT.value
        # 账本可查（Phase B 验收 #6）
        found = await ledger.get(first.account_id, first.idempotency_key)
        assert found is not None

    async def test_an_intent_row_blocks_a_retry_until_reconciled(self, ledger):
        # §5.2：intent 可重试=否（先和解）
        await _claim(ledger)
        with pytest.raises(EffectAlreadyClaimedError):
            await _claim(ledger)

    async def test_committed_refused_unknown_and_resolved_sent_all_block(self, ledger):
        row = await _claim(ledger)
        key = (row.account_id, row.idempotency_key)
        for make_terminal in (
            lambda: ledger.record_committed(*key, receipt_id="plat-1"),
            lambda: ledger.record_refused(*key),
            lambda: ledger.record_unknown(*key),
        ):
            _reset_memory_store()
            await _claim(ledger)
            await make_terminal()
            with pytest.raises(EffectAlreadyClaimedError):
                await _claim(ledger)


# -- §5.2/§5.3 状态机 ----------------------------------------------------


class TestTheStateMachine:
    async def test_committed_needs_a_platform_receipt(self, ledger):
        row = await _claim(ledger)
        with pytest.raises(ValueError):
            await ledger.record_committed(row.account_id, row.idempotency_key, receipt_id="")

    async def test_committed_from_intent_records_the_platform_receipt(self, ledger):
        row = await _claim(ledger)
        done = await ledger.record_committed(
            row.account_id, row.idempotency_key, receipt_id="plat-42"
        )
        assert done.state == EffectState.COMMITTED.value
        assert done.receipt_id == "plat-42"
        assert done.receipt_source == "platform"

    async def test_refused_is_terminal(self, ledger):
        row = await _claim(ledger)
        done = await ledger.record_refused(row.account_id, row.idempotency_key)
        assert done.state == EffectState.REFUSED.value
        for move in (
            lambda: ledger.record_committed(row.account_id, row.idempotency_key, receipt_id="p"),
            lambda: ledger.record_refused(row.account_id, row.idempotency_key),
            lambda: ledger.record_unknown(row.account_id, row.idempotency_key),
            lambda: ledger.record_readback(row.account_id, row.idempotency_key, sent=True),
        ):
            with pytest.raises(IllegalEffectTransitionError):
                await move()

    async def test_unknown_can_only_leave_through_a_readback(self, ledger):
        row = await _claim(ledger)
        await ledger.record_unknown(row.account_id, row.idempotency_key)
        # 判决类出口全部拒绝 —— unknown 的离开方式只有读回
        for move in (
            lambda: ledger.record_committed(row.account_id, row.idempotency_key, receipt_id="p"),
            lambda: ledger.record_refused(row.account_id, row.idempotency_key),
            lambda: ledger.record_unknown(row.account_id, row.idempotency_key),
            # 本地日志对 unknown 无话可说（"可能已发出"证明不了未发出）
            lambda: ledger.record_not_sent(row.account_id, row.idempotency_key),
        ):
            with pytest.raises(IllegalEffectTransitionError):
                await move()

    async def test_readback_hit_resolves_unknown_as_sent(self, ledger):
        row = await _claim(ledger)
        await ledger.record_unknown(row.account_id, row.idempotency_key)
        done = await ledger.record_readback(row.account_id, row.idempotency_key, sent=True)
        assert done.state == EffectState.RESOLVED_SENT.value

    async def test_readback_miss_resolves_unknown_as_not_sent(self, ledger):
        row = await _claim(ledger)
        await ledger.record_unknown(row.account_id, row.idempotency_key)
        done = await ledger.record_readback(row.account_id, row.idempotency_key, sent=False)
        assert done.state == EffectState.RESOLVED_NOT_SENT.value

    async def test_readback_also_reconciles_a_crashed_intent(self, ledger):
        row = await _claim(ledger)
        done = await ledger.record_readback(row.account_id, row.idempotency_key, sent=True)
        assert done.state == EffectState.RESOLVED_SENT.value

    async def test_resolved_sent_is_terminal(self, ledger):
        row = await _claim(ledger)
        await ledger.record_readback(row.account_id, row.idempotency_key, sent=True)
        for move in (
            lambda: ledger.record_committed(row.account_id, row.idempotency_key, receipt_id="p"),
            lambda: ledger.record_unknown(row.account_id, row.idempotency_key),
            lambda: ledger.record_readback(row.account_id, row.idempotency_key, sent=False),
        ):
            with pytest.raises(IllegalEffectTransitionError):
                await move()

    async def test_transitions_on_a_missing_row_raise_not_found(self, ledger):
        for move in (
            lambda: ledger.record_committed("acct-1", "eng:nope", receipt_id="p"),
            lambda: ledger.record_refused("acct-1", "eng:nope"),
            lambda: ledger.record_unknown("acct-1", "eng:nope"),
            lambda: ledger.record_readback("acct-1", "eng:nope", sent=True),
        ):
            with pytest.raises(EffectNotFoundError):
                await move()


class TestTheTransitionTablePinsTheSpecVocabulary:
    def test_all_six_states_are_in_the_table(self):
        assert set(LEGAL_TRANSITIONS) == set(EffectState)

    def test_unknown_only_exits_to_readback_outcomes(self):
        assert LEGAL_TRANSITIONS[EffectState.UNKNOWN] == {
            EffectState.RESOLVED_SENT,
            EffectState.RESOLVED_NOT_SENT,
        }

    def test_only_resolved_not_sent_rearms(self):
        assert LEGAL_TRANSITIONS[EffectState.RESOLVED_NOT_SENT] == {EffectState.INTENT}
        for state in (
            EffectState.COMMITTED,
            EffectState.REFUSED,
            EffectState.RESOLVED_SENT,
        ):
            assert LEGAL_TRANSITIONS[state] == frozenset()

    def test_terminal_states_are_the_three_without_exits_plus_refused(self):
        assert {
            EffectState.COMMITTED,
            EffectState.REFUSED,
            EffectState.RESOLVED_SENT,
        } == TERMINAL_STATES


# -- 重臂 ---------------------------------------------------------------


class TestReArmOnlyAfterProvenNonOccurrence:
    async def test_resolved_not_sent_allows_the_same_key_again(self, ledger):
        row = await _claim(ledger)
        await ledger.record_unknown(row.account_id, row.idempotency_key)
        await ledger.record_readback(row.account_id, row.idempotency_key, sent=False)
        again = await _claim(ledger)
        assert again.idempotency_key == row.idempotency_key
        assert again.state == EffectState.INTENT.value

    async def test_re_arm_records_the_new_approval(self, ledger):
        row = await _claim(ledger)
        await ledger.record_unknown(row.account_id, row.idempotency_key)
        await ledger.record_readback(row.account_id, row.idempotency_key, sent=False)
        fresh = EngagementApproval(
            thread_id="thread-2",
            approved_by="operator-2",
            approved_at="2026-10-14T00:00:00+00:00",
        )
        again = await ledger.claim_intent(
            kind=EffectKind.DM,
            account_id="acct-1",
            target_id="sender-1",
            content="你好",
            approval=fresh,
        )
        assert again.thread_id == "thread-2"
        assert again.approved_by == "operator-2"

    async def test_re_arm_keeps_the_same_ledger_row(self, ledger):
        row = await _claim(ledger)
        await ledger.record_unknown(row.account_id, row.idempotency_key)
        await ledger.record_readback(row.account_id, row.idempotency_key, sent=False)
        await _claim(ledger)
        rows = await ledger.list("acct-1")
        assert len(rows) == 1

    async def test_resolved_sent_never_rearms(self, ledger):
        row = await _claim(ledger)
        await ledger.record_readback(row.account_id, row.idempotency_key, sent=True)
        with pytest.raises(EffectAlreadyClaimedError):
            await _claim(ledger)


# -- CAS 拒绝陈旧写 -----------------------------------------------------


class TestStaleWritesAreRefused:
    async def test_a_concurrent_state_move_is_refused(self, ledger, monkeypatch):
        row = await _claim(ledger)
        account_id, key = row.account_id, row.idempotency_key

        # 模拟并发：读到 intent 之后、写入之前，别人先把行推走。
        original = ledger._effects.get_effect

        async def _moved(*args, **kwargs):
            found = await original(*args, **kwargs)
            await ledger._effects.cas_update(
                account_id,
                key,
                expected_state=EffectState.INTENT.value,
                new_state=EffectState.UNKNOWN.value,
                updated_at="2026-10-13T00:00:01+00:00",
            )
            return found

        monkeypatch.setattr(ledger._effects, "get_effect", _moved)
        with pytest.raises(EffectStateConflictError):
            await ledger.record_committed(account_id, key, receipt_id="plat-1")
