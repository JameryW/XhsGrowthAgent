"""Engagement Effect 账本持久化：Postgres 表 + 进程内存回退。

表形态复用 ``backend/db/creator_agent.py`` 的先例（``UNIQUE (account_id,
idempotency_key)`` + ``INSERT ... ON CONFLICT DO NOTHING``），因为 spec
（``docs/tool-gateway-engagement-migration.md`` §5.1）明确要求 DB 级唯一约束 ——
``backend/state/effects.py`` 的 ``EffectLedger`` 自认 BaseStore 无 CAS，挡不住
多写者重复提交，那正是这层要补的洞。

本模块只做持久化：state 对它只是一个 TEXT 列，状态机合法性归
``backend/services/xhs_effect_ledger.py``。``cas_update`` 提供以 ``expected_state``
为条件的乐观并发原语（CAS），让上层的状态迁移能拒绝陈旧写入。

诚实并发边界：无池内存回退是单进程的（asyncio.Lock）；PG 路径下唯一约束保护
最关键的「同键二次 claim」，``cas_update`` 保护状态迁移。多 worker 并发写同一行
依赖的就是这两个原语，不新增第三套。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from typing import Any

from backend.db.pool import get_pool, is_pool_ready

__all__ = [
    "EffectRow",
    "cas_update",
    "ensure_tables",
    "get_effect",
    "insert_or_get",
    "list_effects",
]

_COLUMNS = (
    "account_id, idempotency_key, capability, target_id, payload_digest, "
    "thread_id, approved_by, approved_at, state, receipt_id, receipt_source, "
    "created_at, updated_at"
)

#: 列顺序同 ``_COLUMNS``；tuple 行按下标取，dict 行按键取（与
#: ``creator_agent._get`` 同一宽容策略）。
_FIELD_ORDER = (
    "account_id",
    "idempotency_key",
    "capability",
    "target_id",
    "payload_digest",
    "thread_id",
    "approved_by",
    "approved_at",
    "state",
    "receipt_id",
    "receipt_source",
    "created_at",
    "updated_at",
)


@dataclass(frozen=True)
class EffectRow:
    """一行 engagement effect（§5.1 字段，正文不入账本）。

    ``payload_digest`` 是正文摘要（16 位 hex），与 §4.1 幂等键里的摘要段同源，
    键可以从行上复算 —— 账本自审计。``receipt_id`` 只来自平台回显（§5.4），
    没有回显时为空串 + ``receipt_source="none"``。
    """

    account_id: str
    idempotency_key: str
    capability: str
    target_id: str
    payload_digest: str
    thread_id: str
    approved_by: str
    approved_at: str
    state: str
    receipt_id: str
    receipt_source: str
    created_at: str
    updated_at: str


_mem_effects: dict[tuple[str, str], EffectRow] = {}
_mem_lock = asyncio.Lock()

_CREATE_EFFECTS_SQL = """
CREATE TABLE IF NOT EXISTS engagement_effects (
    account_id       TEXT NOT NULL,
    idempotency_key  TEXT NOT NULL,
    capability       TEXT NOT NULL,
    target_id        TEXT NOT NULL,
    payload_digest   TEXT NOT NULL,
    thread_id        TEXT NOT NULL,
    approved_by      TEXT NOT NULL,
    approved_at      TEXT NOT NULL,
    state            TEXT NOT NULL,
    receipt_id       TEXT NOT NULL DEFAULT '',
    receipt_source   TEXT NOT NULL DEFAULT 'none',
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    PRIMARY KEY (account_id, idempotency_key),
    UNIQUE (account_id, idempotency_key)
);
"""

_CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_engagement_effects_state
    ON engagement_effects (account_id, state, created_at DESC);
"""


def _reset_memory_store() -> None:
    """Clear the process-memory adapter for isolated tests."""
    _mem_effects.clear()


async def ensure_tables() -> None:
    if not is_pool_ready():
        return
    pool = get_pool()
    async with pool.connection() as conn:
        await conn.execute(_CREATE_EFFECTS_SQL)
        await conn.execute(_CREATE_INDEX_SQL)


def _field(row: Any, index: int) -> Any:
    key = _FIELD_ORDER[index]
    return row[key] if isinstance(row, dict) else row[index]


def _row_from_db(row: Any) -> EffectRow:
    return EffectRow(*[_field(row, i) for i in range(len(_FIELD_ORDER))])


def _row_params(row: EffectRow) -> tuple[Any, ...]:
    return tuple(getattr(row, name) for name in _FIELD_ORDER)


async def _select_row(cur: Any, account_id: str, idempotency_key: str) -> EffectRow | None:
    await cur.execute(
        f"""
        SELECT {_COLUMNS} FROM engagement_effects
        WHERE account_id = %s AND idempotency_key = %s
        """,
        (account_id, idempotency_key),
    )
    found = await cur.fetchone()
    return _row_from_db(found) if found is not None else None


async def insert_or_get(row: EffectRow) -> tuple[EffectRow, bool]:
    """写入 intent 行；同键已存在则返回既有行 + ``created=False``。

    唯一约束在这里就是安全属性：``ON CONFLICT DO NOTHING`` 保证「同键第二次
    claim」在提交前就能被上层看见并拒绝（§4 表：只有键+账本才有这一格）。
    ``created=True`` 仅当本次真的插入了新行（``RETURNING`` 判定，不比对字段）。
    """
    if not is_pool_ready():
        async with _mem_lock:
            key = (row.account_id, row.idempotency_key)
            existing = _mem_effects.get(key)
            if existing is not None:
                return replace(existing), False
            stored = replace(row)
            _mem_effects[key] = stored
            return replace(stored), True

    pool = get_pool()
    async with pool.connection() as conn, conn.transaction(), conn.cursor() as cur:
        await cur.execute(
            f"""
            INSERT INTO engagement_effects ({_COLUMNS})
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (account_id, idempotency_key) DO NOTHING
            RETURNING account_id
            """,
            _row_params(row),
        )
        inserted = await cur.fetchone()
        stored = await _select_row(cur, row.account_id, row.idempotency_key)
        if stored is None:
            raise RuntimeError("effect insert did not return a durable row")
    return replace(stored), inserted is not None


async def cas_update(
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
) -> EffectRow | None:
    """以 ``expected_state`` 为条件更新一行；条件不满足返回 ``None``（拒绝陈旧写）。

    ``thread_id`` / ``approved_by`` / ``approved_at`` 传 ``None`` 表示保持原值
    （状态迁移不动审批字段）；重臂（re-arm）时上层会显式传入新一轮审批。
    """
    if not is_pool_ready():
        async with _mem_lock:
            key = (account_id, idempotency_key)
            existing = _mem_effects.get(key)
            if existing is None or existing.state != expected_state:
                return None
            updated = replace(
                existing,
                state=new_state,
                receipt_id=receipt_id,
                receipt_source=receipt_source,
                thread_id=existing.thread_id if thread_id is None else thread_id,
                approved_by=existing.approved_by if approved_by is None else approved_by,
                approved_at=existing.approved_at if approved_at is None else approved_at,
                updated_at=updated_at,
            )
            _mem_effects[key] = updated
            return replace(updated)

    pool = get_pool()
    sets = ["state = %s", "receipt_id = %s", "receipt_source = %s", "updated_at = %s"]
    params: list[Any] = [new_state, receipt_id, receipt_source, updated_at]
    if thread_id is not None:
        sets.append("thread_id = %s")
        params.append(thread_id)
    if approved_by is not None:
        sets.append("approved_by = %s")
        params.append(approved_by)
    if approved_at is not None:
        sets.append("approved_at = %s")
        params.append(approved_at)
    params.extend([account_id, idempotency_key, expected_state])
    async with pool.connection() as conn, conn.transaction(), conn.cursor() as cur:
        await cur.execute(
            f"""
            UPDATE engagement_effects SET {", ".join(sets)}
            WHERE account_id = %s AND idempotency_key = %s AND state = %s
            """,
            tuple(params),
        )
        stored = await _select_row(cur, account_id, idempotency_key)
    if stored is None or stored.state != new_state:
        # 行不存在，或条件没被满足（并发下别人先动了）。
        return None
    return replace(stored)


async def get_effect(account_id: str, idempotency_key: str) -> EffectRow | None:
    if not is_pool_ready():
        row = _mem_effects.get((account_id, idempotency_key))
        return replace(row) if row else None
    pool = get_pool()
    async with pool.connection() as conn, conn.cursor() as cur:
        return await _select_row(cur, account_id, idempotency_key)


async def list_effects(account_id: str) -> list[EffectRow]:
    if not is_pool_ready():
        rows = [
            replace(row)
            for (stored_account, _), row in _mem_effects.items()
            if stored_account == account_id
        ]
        rows.sort(key=lambda item: (item.created_at, item.idempotency_key), reverse=True)
        return rows
    pool = get_pool()
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            f"""
            SELECT {_COLUMNS} FROM engagement_effects
            WHERE account_id = %s
            ORDER BY created_at DESC, idempotency_key DESC
            """,
            (account_id,),
        )
        found = await cur.fetchall()
    return [_row_from_db(row) for row in found]
