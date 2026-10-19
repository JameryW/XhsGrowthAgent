"""票 5d：§5.3 读回 —— unknown 的唯一出口（开放问题 #2 的落地）。

钉住的口径（安全不对称是设计核心）：
- 三值判决 hit / miss / inconclusive：**读不到永远不是 miss** —— 假 miss 解锁
  重臂 = 同一效果再发一次（给同一个真人发两条），假 hit 只是键锁死（无双发）；
- 空列表是 inconclusive 不是 miss（没打开会话证明不了空）；
- reconcile 只动 unknown/intent 行，正文摘要对不上拒绝和解；
- hit → resolved_sent，miss → resolved_not_sent（可重臂），inconclusive 原封不动。
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.db.engagement_effects import _reset_memory_store
from backend.services.xhs_effect_ledger import (
    EffectAlreadyClaimedError,
    EffectKind,
    EffectState,
    EngagementApproval,
    EngagementEffectLedger,
    effect_idempotency_key,
)
from backend.services.xhs_engagement import (
    READBACK_HIT,
    READBACK_INCONCLUSIVE,
    READBACK_MISS,
    XHSEngagement,
)


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


@asynccontextmanager
async def _noop_hold(**_kwargs: Any):
    yield "acc-1"


def _engagement(page: Any) -> XHSEngagement:
    engagement = XHSEngagement(
        cdp_endpoint="http://127.0.0.1:9224",
        account_id="acc-1",
        cooldown_seconds=0.0,
    )
    engagement._ensure_page = AsyncMock(return_value=page)
    engagement._hold_cdp = AsyncMock(side_effect=lambda: _noop_hold())
    return engagement


def _text_item(text: str, *, readable: bool = True) -> MagicMock:
    item = MagicMock()
    if readable:
        item.inner_text = AsyncMock(return_value=text)
    else:
        item.inner_text = AsyncMock(side_effect=RuntimeError("detached"))
    return item


def _page(
    *,
    comment_element: Any = None,
    reply_items: Any = None,
    message_items: Any = None,
    search_input: Any = None,
    user_result: Any = None,
) -> MagicMock:
    page = MagicMock(url="https://www.xiaohongshu.com/explore/note-1")
    page.evaluate = AsyncMock(return_value="")  # 无风控/登录标记
    page.goto = AsyncMock()
    page.wait_for_selector = AsyncMock()
    page.wait_for_function = AsyncMock()
    # query_selector 顺序：comment_element（评论读回）或 search/user（私信读回）
    page.query_selector = AsyncMock(side_effect=[comment_element, search_input, user_result][:])
    page.query_selector_all = AsyncMock(
        side_effect=lambda selector: reply_items if "reply" in selector else message_items
    )
    return page


async def _claim_dm(ledger: EngagementEffectLedger, *, content: str = "你好"):
    return await ledger.claim_intent(
        kind=EffectKind.DM,
        account_id="acc-1",
        target_id="user-9",
        content=content,
        approval=_approval(),
    )


# -- 三值判决（评论侧）-------------------------------------------------


class TestCommentReadbackIsThreeValued:
    async def test_a_visible_matching_reply_is_a_hit(self):
        page = _page(
            comment_element=MagicMock(),
            reply_items=[_text_item("  你好 "), _text_item("别的回复")],
        )
        engagement = _engagement(page)

        verdict = await engagement.readback_comment_reply("note-1", "comment-1", "你好")

        assert verdict == READBACK_HIT

    async def test_an_enumerable_reply_list_without_the_reply_is_a_miss(self):
        page = _page(
            comment_element=MagicMock(),
            reply_items=[_text_item("别人的回复")],
        )
        engagement = _engagement(page)

        verdict = await engagement.readback_comment_reply("note-1", "comment-1", "你好")

        assert verdict == READBACK_MISS

    async def test_an_empty_enumerable_reply_list_is_inconclusive_not_miss(self):
        """空列表可能是回复折叠未展开 —— 读不到 ≠ 不存在，不能证伪就没有 miss 资格。"""
        page = _page(comment_element=MagicMock(), reply_items=[])
        engagement = _engagement(page)

        verdict = await engagement.readback_comment_reply("note-1", "comment-1", "你好")

        assert verdict == READBACK_INCONCLUSIVE

    async def test_a_missing_comment_element_is_inconclusive_not_miss(self):
        """评论本体都找不到：证明不了有，也证明不了没有。"""
        page = _page(comment_element=None, reply_items=[_text_item("x")])
        engagement = _engagement(page)

        verdict = await engagement.readback_comment_reply("note-1", "comment-1", "你好")

        assert verdict == READBACK_INCONCLUSIVE

    async def test_an_unreadable_reply_item_is_inconclusive_not_miss(self):
        """有条目读不出来 = 「没有」证明不了 —— 读不到永远不是 miss。"""
        page = _page(
            comment_element=MagicMock(),
            reply_items=[_text_item("你好"), _text_item("", readable=False)],
        )
        engagement = _engagement(page)
        # 第一条就是 hit，先测 unreadable 单独在场的保守侧：
        page2 = _page(
            comment_element=MagicMock(),
            reply_items=[_text_item("别的", readable=False)],
        )
        engagement2 = _engagement(page2)

        assert await engagement.readback_comment_reply("n", "c", "你好") == READBACK_HIT
        assert await engagement2.readback_comment_reply("n", "c", "你好") == READBACK_INCONCLUSIVE


# -- 三值判决（私信侧）-------------------------------------------------


class TestDmReadbackIsThreeValued:
    async def test_a_visible_matching_message_is_a_hit(self):
        page = _page(
            search_input=MagicMock(),
            user_result=MagicMock(),
            message_items=[_text_item("  你好 "), _text_item("对方的话")],
        )
        engagement = _engagement(page)

        verdict = await engagement.readback_dm("user-9", "你好")

        assert verdict == READBACK_HIT

    async def test_an_enumerable_conversation_without_the_message_is_a_miss(self):
        page = _page(
            search_input=MagicMock(),
            user_result=MagicMock(),
            message_items=[_text_item("对方的话")],
        )
        engagement = _engagement(page)

        verdict = await engagement.readback_dm("user-9", "你好")

        assert verdict == READBACK_MISS

    async def test_an_empty_conversation_is_inconclusive_not_miss(self):
        """一条消息都读不到 = 既没打开会话也证明不了空。假 miss 解锁重臂=双发。"""
        page = _page(search_input=MagicMock(), user_result=MagicMock(), message_items=[])
        engagement = _engagement(page)

        verdict = await engagement.readback_dm("user-9", "你好")

        assert verdict == READBACK_INCONCLUSIVE

    async def test_an_unreadable_message_item_is_inconclusive_not_miss(self):
        page = _page(
            search_input=MagicMock(),
            user_result=MagicMock(),
            message_items=[_text_item("别的", readable=False)],
        )
        engagement = _engagement(page)

        verdict = await engagement.readback_dm("user-9", "你好")

        assert verdict == READBACK_INCONCLUSIVE


# -- reconcile：读回后才落账 -------------------------------------------


class TestReconcileMovesTheLedgerOnlyOnARealReadback:
    async def test_a_hit_resolves_unknown_as_sent(self):
        ledger = EngagementEffectLedger()
        row = await _claim_dm(ledger)
        await ledger.record_unknown(row.account_id, row.idempotency_key)
        page = _page(
            search_input=MagicMock(),
            user_result=MagicMock(),
            message_items=[_text_item("你好")],
        )
        engagement = _engagement(page)

        out = await engagement.reconcile_effect("acc-1", row.idempotency_key, content="你好")

        assert out["readback"] == READBACK_HIT
        assert out["changed"] is True
        assert out["state"] == EffectState.RESOLVED_SENT.value

    async def test_a_miss_resolves_unknown_as_not_sent_and_reopens_the_key(self):
        ledger = EngagementEffectLedger()
        row = await _claim_dm(ledger)
        await ledger.record_unknown(row.account_id, row.idempotency_key)
        page = _page(
            search_input=MagicMock(),
            user_result=MagicMock(),
            message_items=[_text_item("对方的话")],
        )
        engagement = _engagement(page)

        out = await engagement.reconcile_effect("acc-1", row.idempotency_key, content="你好")

        assert out["readback"] == READBACK_MISS
        assert out["state"] == EffectState.RESOLVED_NOT_SENT.value
        # resolved_not_sent 是唯一可重臂状态（§5.2：确认没提交后可以继续）。
        again = await _claim_dm(ledger)
        assert again.state == EffectState.INTENT.value

    async def test_an_inconclusive_readback_leaves_the_row_untouched(self):
        ledger = EngagementEffectLedger()
        row = await _claim_dm(ledger)
        await ledger.record_unknown(row.account_id, row.idempotency_key)
        page = _page(search_input=MagicMock(), user_result=MagicMock(), message_items=[])
        engagement = _engagement(page)

        out = await engagement.reconcile_effect("acc-1", row.idempotency_key, content="你好")

        assert out["readback"] == READBACK_INCONCLUSIVE
        assert out["changed"] is False
        assert out["state"] == EffectState.UNKNOWN.value
        # unknown 未和解 ⇒ 键仍堵着（§5.2：intent 也要先和解才能再试）。
        with pytest.raises(EffectAlreadyClaimedError):
            await _claim_dm(ledger)

    async def test_the_content_digest_must_match_the_row(self):
        """正文摘要对不上 = 调用方想和解的不是这一行，拒绝（§5.1 正文不入账本）。"""
        ledger = EngagementEffectLedger()
        row = await _claim_dm(ledger)
        await ledger.record_unknown(row.account_id, row.idempotency_key)
        engagement = _engagement(_page())

        with pytest.raises(ValueError, match="payload_digest"):
            await engagement.reconcile_effect("acc-1", row.idempotency_key, content="另一条内容")

    async def test_a_terminal_row_is_not_reconciled(self):
        ledger = EngagementEffectLedger()
        row = await _claim_dm(ledger)
        await ledger.record_refused(row.account_id, row.idempotency_key)
        engagement = _engagement(_page())

        out = await engagement.reconcile_effect("acc-1", row.idempotency_key, content="你好")

        assert out["changed"] is False
        assert out["state"] == EffectState.REFUSED.value

    async def test_a_comment_readback_requires_the_note_id(self):
        ledger = EngagementEffectLedger()
        row = await ledger.claim_intent(
            kind=EffectKind.COMMENT_REPLY,
            account_id="acc-1",
            target_id="comment-1",
            content="谢谢",
            approval=_approval(),
        )
        await ledger.record_unknown(row.account_id, row.idempotency_key)
        engagement = _engagement(_page())

        with pytest.raises(ValueError, match="note_id"):
            await engagement.reconcile_effect("acc-1", row.idempotency_key, content="谢谢")

    async def test_a_comment_hit_resolves_via_the_note_page(self):
        ledger = EngagementEffectLedger()
        row = await ledger.claim_intent(
            kind=EffectKind.COMMENT_REPLY,
            account_id="acc-1",
            target_id="comment-1",
            content="谢谢",
            approval=_approval(),
        )
        await ledger.record_unknown(row.account_id, row.idempotency_key)
        page = _page(
            comment_element=MagicMock(),
            reply_items=[_text_item("谢谢")],
        )
        engagement = _engagement(page)

        out = await engagement.reconcile_effect(
            "acc-1", row.idempotency_key, content="谢谢", note_id="note-1"
        )

        assert out["readback"] == READBACK_HIT
        assert out["state"] == EffectState.RESOLVED_SENT.value

    async def test_an_unknown_key_stays_blocked_until_a_real_readback(self):
        """端到端：unknown → inconclusive（还堵）→ hit（解锁为终局）。"""
        key = effect_idempotency_key(EffectKind.DM, "acc-1", "user-9", "你好")
        ledger = EngagementEffectLedger()
        row = await _claim_dm(ledger)
        await ledger.record_unknown(row.account_id, row.idempotency_key)

        empty = _engagement(
            _page(search_input=MagicMock(), user_result=MagicMock(), message_items=[])
        )
        first = await empty.reconcile_effect("acc-1", key, content="你好")
        assert first["state"] == EffectState.UNKNOWN.value

        hit = _engagement(
            _page(
                search_input=MagicMock(),
                user_result=MagicMock(),
                message_items=[_text_item("你好")],
            )
        )
        second = await hit.reconcile_effect("acc-1", key, content="你好")
        assert second["state"] == EffectState.RESOLVED_SENT.value
