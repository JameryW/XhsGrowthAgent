"""engagement_effects 持久层：无池内存回退 + PG SQL 形状。

钉住：
- 唯一约束是安全属性 —— CREATE TABLE 带 ``UNIQUE (account_id, idempotency_key)``，
  INSERT 带 ``ON CONFLICT ... DO NOTHING``（同键 claim 不会插入第二行）；
- ``insert_or_get`` 的 ``created`` 由 ``RETURNING`` 判定，不靠字段比对；
- ``cas_update`` 以 ``expected_state`` 为条件，条件不满足返回 ``None``（拒绝陈旧写）；
- 内存回退返回防御性副本。
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from backend.db import engagement_effects as store
from backend.db.engagement_effects import (
    EffectRow,
    _reset_memory_store,
    cas_update,
    ensure_tables,
    get_effect,
    insert_or_get,
    list_effects,
)


def _row(**overrides: Any) -> EffectRow:
    base = dict(
        account_id="acct-1",
        idempotency_key="eng:dm:acct-1:sender-1:0123456789abcdef",
        capability="xhs.dm_send",
        target_id="sender-1",
        payload_digest="0123456789abcdef",
        thread_id="thread-1",
        approved_by="operator-1",
        approved_at="2026-10-13T00:00:00+00:00",
        state="intent",
        receipt_id="",
        receipt_source="none",
        created_at="2026-10-13T00:00:00+00:00",
        updated_at="2026-10-13T00:00:00+00:00",
    )
    base.update(overrides)
    return EffectRow(**base)


class _Cursor:
    def __init__(
        self,
        *,
        fetchone_results: list[Any] | None = None,
        fetchall_results: list[Any] | None = None,
    ) -> None:
        self.sql: list[str] = []
        self.params: list[Any] = []
        self._fetchone = list(fetchone_results or [])
        self._fetchall = list(fetchall_results or [])

    async def __aenter__(self) -> _Cursor:
        return self

    async def __aexit__(self, *_args: Any) -> None:
        return None

    async def execute(self, sql: str, params: Any = None) -> None:
        self.sql.append(sql)
        self.params.append(params)

    async def fetchone(self) -> Any:
        return self._fetchone.pop(0) if self._fetchone else None

    async def fetchall(self) -> list[Any]:
        return self._fetchall.pop(0) if self._fetchall else []


class _Transaction:
    async def __aenter__(self) -> _Transaction:
        return self

    async def __aexit__(self, *_args: Any) -> None:
        return None


class _Connection:
    def __init__(self, cursor: _Cursor) -> None:
        self._cursor = cursor

    async def __aenter__(self) -> _Connection:
        return self

    async def __aexit__(self, *_args: Any) -> None:
        return None

    async def execute(self, sql: str) -> None:
        self._cursor.sql.append(sql)

    def transaction(self) -> _Transaction:
        return _Transaction()

    def cursor(self, row_factory: Any = None) -> _Cursor:
        return self._cursor


class _Pool:
    def __init__(self, cursor: _Cursor) -> None:
        self._cursor = cursor

    def connection(self) -> _Connection:
        return _Connection(self._cursor)


def _db_row(row: EffectRow) -> dict[str, Any]:
    return {
        "account_id": row.account_id,
        "idempotency_key": row.idempotency_key,
        "capability": row.capability,
        "target_id": row.target_id,
        "payload_digest": row.payload_digest,
        "thread_id": row.thread_id,
        "approved_by": row.approved_by,
        "approved_at": row.approved_at,
        "state": row.state,
        "receipt_id": row.receipt_id,
        "receipt_source": row.receipt_source,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


@pytest.fixture(autouse=True)
def _clean_effects():
    _reset_memory_store()
    yield
    _reset_memory_store()


# -- 无池内存回退 -------------------------------------------------------


class TestMemoryAdapter:
    async def test_insert_creates_then_returns_the_existing_row(self):
        row = _row()
        stored, created = await insert_or_get(row)
        assert created is True
        assert stored.idempotency_key == row.idempotency_key

        again, created_again = await insert_or_get(_row(state="committed"))
        assert created_again is False
        assert again.state == "intent"  # 既有行赢，不是第二次写入的值

    async def test_returns_defensive_copies(self):
        row = _row()
        stored, _ = await insert_or_get(row)
        assert stored is not row
        got = await get_effect(row.account_id, row.idempotency_key)
        assert got is not None and got is not stored

    async def test_cas_update_refuses_a_stale_expected_state(self):
        row = _row()
        await insert_or_get(row)
        missed = await cas_update(
            row.account_id,
            row.idempotency_key,
            expected_state="unknown",
            new_state="resolved_sent",
            updated_at="2026-10-13T00:00:05+00:00",
        )
        assert missed is None
        got = await get_effect(row.account_id, row.idempotency_key)
        assert got is not None
        assert got.state == "intent"

    async def test_cas_update_moves_state_and_keeps_approval_by_default(self):
        row = _row()
        await insert_or_get(row)
        updated = await cas_update(
            row.account_id,
            row.idempotency_key,
            expected_state="intent",
            new_state="unknown",
            updated_at="2026-10-13T00:00:05+00:00",
        )
        assert updated is not None
        assert updated.state == "unknown"
        assert updated.thread_id == "thread-1"
        assert updated.approved_by == "operator-1"
        assert updated.receipt_id == ""

    async def test_cas_update_can_replace_approval_when_rearming(self):
        row = _row(state="resolved_not_sent")
        await insert_or_get(row)
        updated = await cas_update(
            row.account_id,
            row.idempotency_key,
            expected_state="resolved_not_sent",
            new_state="intent",
            thread_id="thread-2",
            approved_by="operator-2",
            approved_at="2026-10-14T00:00:00+00:00",
            updated_at="2026-10-14T00:00:00+00:00",
        )
        assert updated is not None
        assert updated.thread_id == "thread-2"
        assert updated.approved_by == "operator-2"

    async def test_cas_update_on_a_missing_row_returns_none(self):
        missed = await cas_update(
            "acct-1", "eng:nope", expected_state="intent", new_state="unknown", updated_at="t"
        )
        assert missed is None

    async def test_list_effects_is_account_scoped(self):
        await insert_or_get(_row())
        await insert_or_get(_row(account_id="acct-2", idempotency_key="eng:dm:acct-2:x:aaaa"))
        rows = await list_effects("acct-1")
        assert [r.account_id for r in rows] == ["acct-1"]


# -- PG SQL 形状 -------------------------------------------------------


class TestPostgresSqlShape:
    async def test_create_table_declares_the_unique_constraint(self, monkeypatch):
        cursor = _Cursor()
        monkeypatch.setattr(store, "is_pool_ready", lambda: True)
        monkeypatch.setattr(store, "get_pool", lambda: _Pool(cursor))
        await ensure_tables()
        joined = "\n".join(cursor.sql)
        assert "CREATE TABLE IF NOT EXISTS engagement_effects" in joined
        assert "UNIQUE (account_id, idempotency_key)" in joined
        assert "PRIMARY KEY (account_id, idempotency_key)" in joined

    async def test_ensure_tables_is_a_noop_without_a_pool(self, monkeypatch):
        cursor = _Cursor()
        monkeypatch.setattr(store, "is_pool_ready", lambda: False)
        monkeypatch.setattr(store, "get_pool", lambda: _Pool(cursor))
        await ensure_tables()
        assert cursor.sql == []

    async def test_insert_uses_on_conflict_do_nothing_and_returning(self, monkeypatch):
        row = _row()
        cursor = _Cursor(fetchone_results=[("acct-1",), _db_row(row)])
        monkeypatch.setattr(store, "is_pool_ready", lambda: True)
        monkeypatch.setattr(store, "get_pool", lambda: _Pool(cursor))
        stored, created = await insert_or_get(row)
        assert created is True
        assert stored.state == "intent"
        insert_sql = cursor.sql[0]
        assert "ON CONFLICT (account_id, idempotency_key) DO NOTHING" in insert_sql
        assert "RETURNING account_id" in insert_sql

    async def test_insert_conflict_returns_the_existing_row(self, monkeypatch):
        existing = _row(state="committed", receipt_id="plat-1")
        cursor = _Cursor(fetchone_results=[None, _db_row(existing)])
        monkeypatch.setattr(store, "is_pool_ready", lambda: True)
        monkeypatch.setattr(store, "get_pool", lambda: _Pool(cursor))
        stored, created = await insert_or_get(_row())
        assert created is False
        assert stored.state == "committed"
        assert stored.receipt_id == "plat-1"

    async def test_cas_update_guards_on_expected_state(self, monkeypatch):
        row = _row(state="resolved_sent")
        cursor = _Cursor(fetchone_results=[_db_row(row)])
        monkeypatch.setattr(store, "is_pool_ready", lambda: True)
        monkeypatch.setattr(store, "get_pool", lambda: _Pool(cursor))
        missed = await cas_update(
            row.account_id,
            row.idempotency_key,
            expected_state="intent",
            new_state="unknown",
            updated_at="t2",
        )
        assert missed is None
        update_sql = cursor.sql[0]
        assert "WHERE account_id = %s AND idempotency_key = %s AND state = %s" in (
            " ".join(update_sql.split())
        )
        assert cursor.params[0][-1] == "intent"

    async def test_rows_from_tuple_results_are_read_by_position(self, monkeypatch):
        row = _row()
        values = tuple(_db_row(row)[name] for name in store._FIELD_ORDER)
        cursor = _Cursor(fetchall_results=[[values]])
        monkeypatch.setattr(store, "is_pool_ready", lambda: True)
        monkeypatch.setattr(store, "get_pool", lambda: _Pool(cursor))
        rows = await list_effects("acct-1")
        assert rows == [row]


def test_memory_lock_is_a_single_asyncio_lock():
    assert isinstance(store._mem_lock, asyncio.Lock)
