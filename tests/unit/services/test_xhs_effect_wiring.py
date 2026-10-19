"""票 5c Task 8：Effect 账本接线 —— 顺序、审批、判决入账。

钉住的口径（对应 docs/tool-gateway-engagement-migration.md）：
- §5.1 先记账再动手：浏览器被碰到的那一刻，intent 行已经在账本里；
- §4/§8 #6：同键第二次调用**提交前**被拒（error_code=effect_already_claimed），
  浏览器一次都不碰，账本可查；
- §7.2：审批记录进 intent 行；冷启动没有审批记录就是 dm_unconfirmed；
- 判决→账本状态走 ``state_for_engagement_verdict`` 映射表。
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.db.engagement_effects import _reset_memory_store
from backend.services.xhs_effect_ledger import (
    EffectKind,
    EffectState,
    EngagementApproval,
    EngagementEffectLedger,
    effect_idempotency_key,
)
from backend.services.xhs_engagement import XHSEngagement
from backend.services.xhs_outreach_policy import (
    OUTREACH_CONFIRMED,
    XhsOutreachPolicy,
)
from backend.services.xhs_risk_gate import check_dm_target_allowed as real_check_dm_target_allowed

GATE = "backend.services.xhs_risk_gate"
LEDGER = "backend.services.xhs_effect_ledger"


@pytest.fixture(autouse=True)
def _clean_effects():
    _reset_memory_store()
    yield
    _reset_memory_store()


def _approval() -> EngagementApproval:
    return EngagementApproval(
        thread_id="thread-1",
        approved_by="operator-1",
        approved_at="2026-10-13T00:00:00+00:00",
    )


def _engagement(page: Any) -> XHSEngagement:
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _noop_hold(**_kwargs: Any):
        yield "acc-1"

    engagement = XHSEngagement(
        cdp_endpoint="http://127.0.0.1:9224",
        account_id="acc-1",
        cooldown_seconds=0.0,
    )
    engagement._ensure_page = AsyncMock(return_value=page)
    engagement._hold_cdp = AsyncMock(side_effect=lambda: _noop_hold())
    return engagement


def _page(*query_results: Any) -> MagicMock:
    page = MagicMock(url="https://www.xiaohongshu.com/explore/note-1")
    page.evaluate = AsyncMock(return_value="")
    page.goto = AsyncMock()
    page.wait_for_selector = AsyncMock()
    page.wait_for_function = AsyncMock()
    page.query_selector = AsyncMock(side_effect=list(query_results))
    return page


def _element() -> MagicMock:
    element = MagicMock()
    element.query_selector = AsyncMock(return_value=None)
    element.fill = AsyncMock()
    element.click = AsyncMock()
    element.inner_text = AsyncMock(return_value="")
    element.get_attribute = AsyncMock(return_value="")
    return element


@pytest.fixture(autouse=True)
def _open_gates(monkeypatch: pytest.MonkeyPatch):
    for name in (
        "check_engagement_risk_pause",
        "check_comment_reply_quota",
        "check_dm_quota",
        "check_dm_target_allowed",
        "check_engagement_allowed",
    ):
        monkeypatch.setattr(f"{GATE}.{name}", lambda *a, **k: None)


async def _ledger_state(account_id: str, key: str) -> str | None:
    row = await EngagementEffectLedger().get(account_id, key)
    return None if row is None else row.state


class TestTheIntentRowPredatesAnyBrowserAction:
    async def test_the_row_is_in_the_ledger_when_the_browser_is_first_touched(self):
        """§5.1 关键：先记账再动手 —— 崩在中途才有据可查。"""
        seen: list[str | None] = []
        key = effect_idempotency_key(EffectKind.DM, "acc-1", "user-9", "你好")
        page = _page(None, _element(), _element())
        engagement = _engagement(page)

        async def _snapshot(*_a: Any, **_k: Any) -> None:
            seen.append(await _ledger_state("acc-1", key))

        page.goto = AsyncMock(side_effect=_snapshot)
        with (
            patch(f"{GATE}.is_inbound_peer", lambda *a, **k: True),
            patch(f"{GATE}.note_dm_sent", lambda *a, **k: None),
        ):
            result = await engagement.send_dm("user-9", "你好")

        assert result["status"] == "sent"
        # goto 是第一个浏览器动作：那一刻行必须已经在账本里且是 intent。
        assert seen == [EffectState.INTENT.value]
        # 判决后记账：私信路径点击发出但无平台确认 → unknown（§5.2 四态排除法）。
        assert await _ledger_state("acc-1", key) == EffectState.UNKNOWN.value

    async def test_a_blocked_call_writes_nothing_and_touches_nothing(self):
        """门禁拒绝发生在 claim 之前 —— 没有效果就没账可记。"""
        page = _page()
        engagement = _engagement(page)

        class _Block:
            risk_code = "dm_target_not_inbound"
            message = "冷启动被拒"

        with patch(f"{GATE}.check_dm_target_allowed", lambda *a, **k: _Block()):
            result = await engagement.send_dm("cold-user", "你好")

        assert result["status"] == "blocked"
        assert await EngagementEffectLedger().list("acc-1") == []
        page.goto.assert_not_awaited()


class TestTheSameKeyIsRefusedBeforeASecondSubmit:
    async def test_second_same_content_send_is_refused_and_the_ledger_is_queryable(self):
        key = effect_idempotency_key(EffectKind.DM, "acc-1", "user-9", "你好")
        page = _page(None, _element(), _element())
        engagement = _engagement(page)

        with (
            patch(f"{GATE}.is_inbound_peer", lambda *a, **k: True),
            patch(f"{GATE}.note_dm_sent", lambda *a, **k: None),
        ):
            first = await engagement.send_dm("user-9", "你好")
            second = await engagement.send_dm("user-9", "你好")

        assert first["status"] == "sent"
        assert second["status"] == "blocked"
        assert second["error_code"] == "effect_already_claimed"
        # 提交前拒绝：浏览器只被碰过一次（第一次）。
        assert page.goto.await_count == 1
        engagement._ensure_page.assert_awaited_once()
        # 账本可查（Phase B 验收 #6）。
        assert await _ledger_state("acc-1", key) == EffectState.UNKNOWN.value

    async def test_a_comment_reply_key_is_refused_the_same_way(self):
        key = effect_idempotency_key(EffectKind.COMMENT_REPLY, "acc-1", "comment-1", "谢谢")
        page = _page(_element(), _element(), _element())
        engagement = _engagement(page)

        with patch(f"{GATE}.note_comment_reply_sent", lambda *a: None):
            first = await engagement.reply_to_comment("note-1", "comment-1", "谢谢")
            second = await engagement.reply_to_comment("note-1", "comment-1", "谢谢")

        assert first["status"] == "sent"
        assert second["status"] == "blocked"
        assert second["error_code"] == "effect_already_claimed"
        assert page.goto.await_count == 1
        assert await _ledger_state("acc-1", key) == EffectState.RESOLVED_SENT.value


class TestTheApprovalRecordEntersTheIntentRow:
    async def test_cold_start_records_who_approved(self):
        key = effect_idempotency_key(EffectKind.DM, "acc-1", "cold-user", "你好")
        # 冷启动（带审批）的 query 槽位：新建私信 / 搜索 / 输入框 / 发送按钮。
        page = _page(None, None, _element(), _element())
        engagement = _engagement(page)
        policy = XhsOutreachPolicy(
            account_id="acc-1", mode=OUTREACH_CONFIRMED, daily_proactive_cap=5
        )

        with (
            patch(
                "backend.services.xhs_outreach_policy.load_outreach_policy",
                AsyncMock(return_value=policy),
            ),
            patch(f"{GATE}.note_dm_sent", lambda *a, **k: None),
        ):
            result = await engagement.send_dm("cold-user", "你好", approval=_approval())

        assert result["status"] == "sent"
        row = await EngagementEffectLedger().get("acc-1", key)
        assert row is not None
        assert row.thread_id == "thread-1"
        assert row.approved_by == "operator-1"
        assert row.approved_at == "2026-10-13T00:00:00+00:00"

    async def test_cold_start_without_an_approval_record_is_refused_by_the_gate(self):
        """§7.2：自声明 bool 换成记录 —— 没记录就不是"批过"。"""
        policy = XhsOutreachPolicy(
            account_id="acc-1", mode=OUTREACH_CONFIRMED, daily_proactive_cap=5
        )
        block = real_check_dm_target_allowed("acc-1", "cold-user", approval=None, policy=policy)
        assert block is not None
        assert block.risk_code == "dm_unconfirmed"
        # 有记录就过。
        assert (
            real_check_dm_target_allowed("acc-1", "cold-user", approval=_approval(), policy=policy)
            is None
        )

    async def test_an_inbound_reply_stores_empty_approval_columns(self):
        """入站应答无逐条审批：账本如实留空，不编造审批人。"""
        key = effect_idempotency_key(EffectKind.DM, "acc-1", "user-9", "你好")
        page = _page(None, _element(), _element())
        engagement = _engagement(page)

        with (
            patch(f"{GATE}.is_inbound_peer", lambda *a, **k: True),
            patch(f"{GATE}.note_dm_sent", lambda *a, **k: None),
        ):
            await engagement.send_dm("user-9", "你好")

        row = await EngagementEffectLedger().get("acc-1", key)
        assert row is not None
        assert row.thread_id == ""
        assert row.approved_by == ""
        assert row.approved_at == ""


class TestVerdictsLandOnTheMappedState:
    async def test_a_verified_comment_reply_is_resolved_sent(self):
        """评论路径点完后的 DOM 复查 = 内联读回命中（§5.3）。"""
        key = effect_idempotency_key(EffectKind.COMMENT_REPLY, "acc-1", "comment-1", "谢谢")
        page = _page(_element(), _element(), _element())
        engagement = _engagement(page)

        with patch(f"{GATE}.note_comment_reply_sent", lambda *a: None):
            result = await engagement.reply_to_comment("note-1", "comment-1", "谢谢")

        assert result["status"] == "sent"
        assert result["verified"] is True
        assert await _ledger_state("acc-1", key) == EffectState.RESOLVED_SENT.value

    async def test_a_verification_timeout_lands_on_unknown(self):
        key = effect_idempotency_key(EffectKind.COMMENT_REPLY, "acc-1", "comment-1", "谢谢")
        page = _page(_element(), _element(), _element())
        page.wait_for_function = AsyncMock(side_effect=TimeoutError("5s"))
        engagement = _engagement(page)

        with patch(f"{GATE}.note_comment_reply_sent", lambda *a: None):
            result = await engagement.reply_to_comment("note-1", "comment-1", "谢谢")

        assert result["status"] == "unknown"
        assert await _ledger_state("acc-1", key) == EffectState.UNKNOWN.value

    async def test_a_pre_click_failure_resolves_as_not_sent(self):
        """点击前明确失败 = 本地日志证明未发出 → resolved_not_sent（可重臂）。"""
        key = effect_idempotency_key(EffectKind.DM, "acc-1", "user-9", "你好")
        page = _page(None, _element(), None)  # 输入框在、发送按钮无
        engagement = _engagement(page)

        with (
            patch(f"{GATE}.is_inbound_peer", lambda *a, **k: True),
            patch(f"{GATE}.note_dm_sent", lambda *a, **k: None),
        ):
            result = await engagement.send_dm("user-9", "你好")

        assert result["status"] == "failed"
        assert result["error_code"] == "send_button_missing"
        assert await _ledger_state("acc-1", key) == EffectState.RESOLVED_NOT_SENT.value

    async def test_a_platform_verdict_lands_on_refused(self):
        key = effect_idempotency_key(EffectKind.DM, "acc-1", "user-9", "你好")
        engagement = _engagement(_page())

        # 门禁后的浏览器流里弹风控页：判决 blocked/risk_control → refused（§5.2）。
        engagement._send_dm_locked = AsyncMock(
            return_value={
                "status": "blocked",
                "success": False,
                "error_code": "risk_control",
                "error": "风控拦截",
                "receipt_id": "",
                "receipt_source": "none",
                "correlation_id": "dm-x",
                "verified": False,
                "retryable": False,
            }
        )
        with (
            patch(f"{GATE}.is_inbound_peer", lambda *a, **k: True),
            patch(f"{GATE}.note_dm_sent", lambda *a, **k: None),
        ):
            result = await engagement.send_dm("user-9", "你好")

        assert result["error_code"] == "risk_control"
        assert await _ledger_state("acc-1", key) == EffectState.REFUSED.value


class TestTheVerdictMappingTable:
    """映射表本体 —— 每一格都要能说出处（见 state_for_engagement_verdict）。"""

    def test_receipt_beats_everything(self):
        from backend.services.xhs_effect_ledger import state_for_engagement_verdict

        state = state_for_engagement_verdict("sent", receipt_id="plat-1", verified=True)
        assert state is EffectState.COMMITTED

    def test_a_clean_click_without_receipt_is_unknown_not_committed(self):
        from backend.services.xhs_effect_ledger import state_for_engagement_verdict

        state = state_for_engagement_verdict("sent", receipt_id="", verified=False)
        assert state is EffectState.UNKNOWN

    def test_a_verified_surface_confirmation_is_resolved_sent(self):
        from backend.services.xhs_effect_ledger import state_for_engagement_verdict

        state = state_for_engagement_verdict("sent", receipt_id="", verified=True)
        assert state is EffectState.RESOLVED_SENT

    def test_definite_pre_click_failures_are_resolved_not_sent(self):
        from backend.services.xhs_effect_ledger import state_for_engagement_verdict

        for code in (
            "comment_not_found",
            "dm_input_missing",
            "reply_input_missing",
            "send_button_missing",
            "configuration",
        ):
            state = state_for_engagement_verdict("failed", error_code=code)
            assert state is EffectState.RESOLVED_NOT_SENT, code

    def test_platform_verdicts_are_refused(self):
        from backend.services.xhs_effect_ledger import state_for_engagement_verdict

        for code in ("quota", "risk_control", "blocked"):
            state = state_for_engagement_verdict("blocked", error_code=code)
            assert state is EffectState.REFUSED, code

    def test_anything_unprovable_lands_on_the_safe_side(self):
        from backend.services.xhs_effect_ledger import state_for_engagement_verdict

        for status, code in (("failed", "exception"), ("blocked", "login_required"), ("weird", "")):
            state = state_for_engagement_verdict(status, error_code=code)
            assert state is EffectState.UNKNOWN, (status, code)
