"""Engagement Effect 账本 —— 触达副作用的幂等与状态机（spec §4/§5）。

小红书没有幂等提交接口（§4），所以保护来自**键 + 账本**：提交前 claim 能查到
"这个键已经发过"并**拒绝**，提交后判决入账，`unknown` 能被读回和解。

四个设计点，每个都对应 spec 里一句明确的话：

1. **键从效果算，不从请求算**（§4.1）：
   ``eng:{kind}:{account_id}:{target_id}:{sha256(content)[:16]}``。
   per-attempt 的 uuid 会让"同一次效果被提交两次"在账本里表现为两条互不相干的
   记录 —— 恰好是键唯一能提供的那点保护也消失了。
2. **先记账再动手**（§5.1）：intent 行在提交**之前**写，崩在中途才有据可查。
3. **六态状态机**（§5.2/§5.3）：`intent` / `committed` / `refused` / `unknown`
   两个读回出口 `resolved_sent` / `resolved_not_sent`。`unknown` **只能经读回离开**；
   `intent` 与 `unknown` 的区别是"我们还没提交" vs "可能提交了" —— 前者在确认
   没提交后可以继续（重臂），后者只能读回。
4. **审批进 intent 行**（§7.2）：`human_confirmed` 那种调用方自声明的 bool 不可信任；
   这里记录谁批的（`approved_by` / `approved_at` / `thread_id`），Gateway 侧不存
   审批状态。

与 ``backend/state/effects.py`` 的 ``EffectLedger`` 的分工：那个是 publish 用的
BaseStore 账本（无 CAS，docstring 自认多写者需要 DB 级唯一约束）；这个是 spec §5.1
点名的 DB 级账本（``UNIQUE (account_id, idempotency_key)``），状态词汇也是 §5.2
自己的六词，两套不要混。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from backend.db import engagement_effects as store
from backend.db.engagement_effects import EffectRow

__all__ = [
    "CAPABILITY_BY_KIND",
    "DEFINITE_NON_SEND_ERROR_CODES",
    "PLATFORM_VERDICT_ERROR_CODES",
    "EffectAlreadyClaimedError",
    "EffectKind",
    "EffectNotFoundError",
    "EffectState",
    "EffectStateConflictError",
    "EngagementApproval",
    "EngagementEffectLedger",
    "IllegalEffectTransitionError",
    "LEGAL_TRANSITIONS",
    "TERMINAL_STATES",
    "effect_idempotency_key",
    "payload_digest_for",
    "state_for_engagement_verdict",
]


class EffectKind(StrEnum):
    """§4.1 键里的 kind；capability（§5.1）由它派生。"""

    COMMENT_REPLY = "comment_reply"
    DM = "dm"


#: §5.1 capability 列的取值。
CAPABILITY_BY_KIND: dict[EffectKind, str] = {
    EffectKind.COMMENT_REPLY: "xhs.comment_reply",
    EffectKind.DM: "xhs.dm_send",
}


class EffectState(StrEnum):
    """§5.2 四态 + §5.3 两个读回出口，共六词。"""

    INTENT = "intent"
    COMMITTED = "committed"
    REFUSED = "refused"
    UNKNOWN = "unknown"
    RESOLVED_SENT = "resolved_sent"
    RESOLVED_NOT_SENT = "resolved_not_sent"


#: 合法状态迁移。两个口径钉在这里：
#: - ``UNKNOWN`` 的出口**只有**两个 resolved_*（§5.3：unknown 只能经读回离开）；
#: - ``RESOLVED_NOT_SENT → INTENT`` 是重臂：读回证明上一次**没有**发出，同一逻辑
#:   效果允许再次尝试（§5.2 "前者可以在确认没提交后继续"）。其余 resolved/终态
#:   一律封死 —— 已发出或终局判决的键永远不能再发一次。
LEGAL_TRANSITIONS: dict[EffectState, frozenset[EffectState]] = {
    EffectState.INTENT: frozenset(
        {
            EffectState.COMMITTED,
            EffectState.REFUSED,
            EffectState.UNKNOWN,
            EffectState.RESOLVED_SENT,
            EffectState.RESOLVED_NOT_SENT,
        }
    ),
    EffectState.UNKNOWN: frozenset({EffectState.RESOLVED_SENT, EffectState.RESOLVED_NOT_SENT}),
    EffectState.RESOLVED_NOT_SENT: frozenset({EffectState.INTENT}),
    EffectState.COMMITTED: frozenset(),
    EffectState.REFUSED: frozenset(),
    EffectState.RESOLVED_SENT: frozenset(),
}

#: 没有出边的状态（含 refused —— 重试会烧额度，§5.2 明文不重试）。
TERMINAL_STATES: frozenset[EffectState] = frozenset(
    state for state, targets in LEGAL_TRANSITIONS.items() if not targets
)


class EffectAlreadyClaimedError(Exception):
    """同键已在账本里且不处于可重臂状态 —— 提交前拒绝（§4 表右列）。"""

    def __init__(self, existing: EffectRow) -> None:
        self.existing = existing
        super().__init__(
            f"effect already claimed: {existing.idempotency_key} (state={existing.state})"
        )


class EffectNotFoundError(Exception):
    """账本里没有这行。"""


class IllegalEffectTransitionError(Exception):
    """状态机外的迁移 —— 含一切从 unknown 直接去 committed/refused 的企图。"""


class EffectStateConflictError(Exception):
    """CAS 失败：读到的状态已经被别人改掉，本次写入被拒（拒绝陈旧写）。"""


@dataclass(frozen=True)
class EngagementApproval:
    """§7.2 审批记录 —— 调用前置条件，不是 payload 里一个可自声明的 bool。

    三个字段都必须非空：空的 ``approved_by`` 就是那个 bool 洞换了个形状。
    """

    thread_id: str
    approved_by: str
    approved_at: str

    def __post_init__(self) -> None:
        for name in ("thread_id", "approved_by", "approved_at"):
            if not getattr(self, name):
                raise ValueError(f"EngagementApproval.{name} must not be empty")


def payload_digest_for(content: str) -> str:
    """正文摘要（16 位 hex）—— 与 §4.1 键里的摘要段同源，行上可复算键。"""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def effect_idempotency_key(kind: EffectKind, account_id: str, target_id: str, content: str) -> str:
    """§4.1 键：从**效果**算，不从请求算。"""
    digest = payload_digest_for(content)
    return f"eng:{kind.value}:{account_id}:{target_id}:{digest}"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


#: 提交动作**从未**发生的失败码：全部出现在点击之前（Phase A 保证
#: FAILED=definite failure），本地动作日志就是"确认没提交"的证据
#: （§5.2 "intent 可以在确认没提交后继续"）。
DEFINITE_NON_SEND_ERROR_CODES: frozenset[str] = frozenset(
    {
        "comment_not_found",
        "dm_input_missing",
        "reply_input_missing",
        "send_button_missing",
        "configuration",  # 页面都起不来（_ensure_page），任何动作都没做
    }
)

#: §5.2 refused 名单（额度、风控、blocked）—— 平台给的终局判决，重试会烧额度。
PLATFORM_VERDICT_ERROR_CODES: frozenset[str] = frozenset({"quota", "risk_control", "blocked"})


def state_for_engagement_verdict(
    status: str,
    *,
    error_code: str = "",
    receipt_id: str = "",
    verified: bool = False,
) -> EffectState:
    """把互动判决（``xhs_engagement`` 的 verdict dict）翻译成账本状态。

    映射表，每一行都有出处：

    ==============  ==========================================================
    判决             账本状态
    ==============  ==========================================================
    sent + 回执      ``committed``（§5.2/§5.4：只有平台回显的 id 才算回执）
    sent + verified  ``resolved_sent``（§5.3 读回命中 —— 评论路径点完后的 DOM
                     复查就是一次内联读回：拉目标真实状态，命中）
    sent 其余        ``unknown``（私信路径点击发出、无平台确认。§5.2 四态里
                     只能落 unknown：没回执不能算 committed，平台没拒绝不算
                     refused，已提交不算 intent —— 与 Phase A 自己的注释一致：
                     "the click is evidence that we submitted, not that the
                     platform accepted"）
    unknown          ``unknown``（§5.2 答复丢失）
    提交前失败码      ``resolved_not_sent``（本地日志证明未发出 → 可重臂）
    平台终局码        ``refused``（§5.2 名单：额度、风控、blocked）
    其余             ``unknown``（证明不了"未发出" ⇒ 保守侧，先堵重试）
    ==============  ==========================================================

    诚实边界：`risk_control` 若发生在点击**之后**才弹出拦截页，真实状态是
    "可能已发出"（§3.3 的歧义）。当前按 §5.2 名单记 ``refused`` —— 两者都堵
    重试（不会双发），差别只在读回后能否重臂。等 §9.2 读回能力落地后应复核
    这一档；`login_required` 不在 §5.2 名单里，落保守侧 ``unknown``。
    """
    if status == "sent":
        if receipt_id:
            return EffectState.COMMITTED
        if verified:
            return EffectState.RESOLVED_SENT
        return EffectState.UNKNOWN
    if status == "unknown":
        return EffectState.UNKNOWN
    if error_code in PLATFORM_VERDICT_ERROR_CODES:
        return EffectState.REFUSED
    if error_code in DEFINITE_NON_SEND_ERROR_CODES:
        return EffectState.RESOLVED_NOT_SENT
    return EffectState.UNKNOWN


class _EffectStore(Protocol):
    """账本存储的形状（``backend.db.engagement_effects`` 及测试替身）。"""

    async def insert_or_get(self, row: EffectRow) -> tuple[EffectRow, bool]: ...

    async def cas_update(
        self,
        account_id: str,
        idempotency_key: str,
        *,
        expected_state: str,
        new_state: str,
        receipt_id: str = "",
        receipt_source: str = "none",
        thread_id: str | None = None,
        approved_by: str | None = None,
        approved_at: str | None = None,
        updated_at: str,
    ) -> EffectRow | None: ...

    async def get_effect(self, account_id: str, idempotency_key: str) -> EffectRow | None: ...

    async def list_effects(self, account_id: str) -> list[EffectRow]: ...


class EngagementEffectLedger:
    """claim / 判决 / 读回三段 API。方法即 §5 的三段生命周期。"""

    def __init__(self, effects: _EffectStore | None = None) -> None:
        # 默认走 DB 适配层（无池时是内存回退）；typed store 而不是 Any ——
        # Any 会让每个 return 点都变成 no-any-return。
        self._effects: _EffectStore = store if effects is None else effects

    # -- claim（提交前）--------------------------------------------------

    async def claim_intent(
        self,
        *,
        kind: EffectKind,
        account_id: str,
        target_id: str,
        content: str,
        approval: EngagementApproval | None = None,
    ) -> EffectRow:
        """提交**之前**登记 intent 行；同键不可重臂时抛 ``EffectAlreadyClaimedError``。

        ``approval`` 是 §7.2 的审批记录；入站应答可以没有逐条审批（策略即授权），
        此时三列如实留空 —— 账本记录"谁批的"，**该不该有**审批由闸门
        （``check_dm_target_allowed``）判定，两件事不混在一个地方。

        返回的行是账本里的权威副本（重臂时是上一行就地翻回 intent，不是新行）。
        """
        now = _now_iso()
        key = effect_idempotency_key(kind, account_id, target_id, content)
        row = EffectRow(
            account_id=account_id,
            idempotency_key=key,
            capability=CAPABILITY_BY_KIND[kind],
            target_id=target_id,
            payload_digest=payload_digest_for(content),
            thread_id=approval.thread_id if approval else "",
            approved_by=approval.approved_by if approval else "",
            approved_at=approval.approved_at if approval else "",
            state=EffectState.INTENT.value,
            receipt_id="",
            receipt_source="none",
            created_at=now,
            updated_at=now,
        )
        stored, created = await self._effects.insert_or_get(row)
        if created:
            return stored
        if EffectState(stored.state) is not EffectState.RESOLVED_NOT_SENT:
            # intent 也拒绝：§5.2 "intent 可重试=否（先和解）"。
            raise EffectAlreadyClaimedError(stored)
        # 重臂：上一次读回证明未发出（resolved_not_sent 是唯一可重臂状态）。
        re_armed = await self._effects.cas_update(
            account_id,
            key,
            expected_state=EffectState.RESOLVED_NOT_SENT.value,
            new_state=EffectState.INTENT.value,
            thread_id=approval.thread_id if approval else "",
            approved_by=approval.approved_by if approval else "",
            approved_at=approval.approved_at if approval else "",
            updated_at=_now_iso(),
        )
        if re_armed is None:
            raise EffectStateConflictError(
                f"re-arm lost the race for {key} (state moved off resolved_not_sent)"
            )
        return re_armed

    async def get(self, account_id: str, idempotency_key: str) -> EffectRow | None:
        """账本可查（Phase B 验收 #6 的那个"账本可查"）。"""
        return await self._effects.get_effect(account_id, idempotency_key)

    async def list(self, account_id: str) -> list[EffectRow]:
        return await self._effects.list_effects(account_id)

    # -- 判决（提交后）--------------------------------------------------

    async def record_committed(
        self, account_id: str, idempotency_key: str, *, receipt_id: str
    ) -> EffectRow:
        """平台回显了回执（§5.4：只有平台 id 才算，本地标识一律不进）。"""
        if not receipt_id:
            raise ValueError("committed requires a platform receipt_id (§5.4)")
        return await self._transition(
            account_id,
            idempotency_key,
            new_state=EffectState.COMMITTED,
            from_states={EffectState.INTENT},
            receipt_id=receipt_id,
            receipt_source="platform",
        )

    async def record_refused(self, account_id: str, idempotency_key: str) -> EffectRow:
        """平台给了终局判决（额度、风控、blocked）—— 重试会烧额度，不再重试。"""
        return await self._transition(
            account_id,
            idempotency_key,
            new_state=EffectState.REFUSED,
            from_states={EffectState.INTENT},
        )

    async def record_unknown(self, account_id: str, idempotency_key: str) -> EffectRow:
        """提交动作已发出，答复丢了 —— 只能读回，不自动重试。"""
        return await self._transition(
            account_id,
            idempotency_key,
            new_state=EffectState.UNKNOWN,
            from_states={EffectState.INTENT},
        )

    async def record_not_sent(self, account_id: str, idempotency_key: str) -> EffectRow:
        """本地动作日志证明**从未提交**（点击前的明确失败）→ resolved_not_sent。

        与 ``record_readback(sent=False)`` 同一落点、不同证据：这条不需要读回，
        因为提交动作根本没发生。只允许从 ``intent`` 离开 —— ``unknown`` 的离开
        方式**只有**读回（§5.3），本地日志对 unknown 无话可说。
        """
        return await self._transition(
            account_id,
            idempotency_key,
            new_state=EffectState.RESOLVED_NOT_SENT,
            from_states={EffectState.INTENT},
        )

    # -- 读回（unknown 的唯一出口）--------------------------------------

    async def record_readback(
        self, account_id: str, idempotency_key: str, *, sent: bool
    ) -> EffectRow:
        """读回真实状态后的和解出口（§5.3）：命中 → resolved_sent，未命中 → resolved_not_sent。

        这是 ``unknown`` **唯一**的离开方式。`intent` 也能经读回和解（崩溃后
        "到底发出去没有"同样只能由真实状态回答）。
        """
        return await self._transition(
            account_id,
            idempotency_key,
            new_state=(EffectState.RESOLVED_SENT if sent else EffectState.RESOLVED_NOT_SENT),
            from_states={EffectState.INTENT, EffectState.UNKNOWN},
        )

    # -- 内部 ------------------------------------------------------------

    async def _transition(
        self,
        account_id: str,
        idempotency_key: str,
        *,
        new_state: EffectState,
        from_states: set[EffectState],
        receipt_id: str = "",
        receipt_source: str = "none",
    ) -> EffectRow:
        existing = await self._effects.get_effect(account_id, idempotency_key)
        if existing is None:
            raise EffectNotFoundError(f"no effect row for {account_id}/{idempotency_key}")
        current = EffectState(existing.state)
        if current not in from_states or new_state not in LEGAL_TRANSITIONS.get(
            current, frozenset()
        ):
            legal = sorted(s.value for s in LEGAL_TRANSITIONS.get(current, frozenset()))
            raise IllegalEffectTransitionError(
                f"{current.value} -> {new_state.value} not allowed (legal from here: {legal})"
            )
        updated = await self._effects.cas_update(
            account_id,
            idempotency_key,
            expected_state=current.value,
            new_state=new_state.value,
            receipt_id=receipt_id,
            receipt_source=receipt_source,
            updated_at=_now_iso(),
        )
        if updated is None:
            raise EffectStateConflictError(
                f"CAS refused {current.value} -> {new_state.value} for {idempotency_key}"
            )
        return updated
