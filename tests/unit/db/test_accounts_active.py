"""get_active_account determinism tests.

Legacy rows may leave more than one ``is_active = TRUE`` account; the reader
must pick deterministically (most recently updated) instead of an arbitrary
row.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from backend.db.accounts import get_active_account

pytestmark = pytest.mark.asyncio


class _Cursor:
    def __init__(self) -> None:
        self.sql: list[str] = []
        self.params: list[Any] = []

    async def __aenter__(self) -> _Cursor:
        return self

    async def __aexit__(self, *_args: Any) -> None:
        return None

    async def execute(self, sql: str, params: Any = None) -> None:
        self.sql.append(sql)
        self.params.append(params)

    async def fetchone(self) -> None:
        return None


class _Connection:
    def __init__(self, cursor: _Cursor) -> None:
        self._cursor = cursor

    async def __aenter__(self) -> _Connection:
        return self

    async def __aexit__(self, *_args: Any) -> None:
        return None

    def cursor(self, row_factory: Any = None) -> _Cursor:
        return self._cursor


class _Pool:
    def __init__(self, cursor: _Cursor) -> None:
        self._cursor = cursor

    def connection(self) -> _Connection:
        return _Connection(self._cursor)


async def test_get_active_account_orders_by_most_recently_updated():
    cursor = _Cursor()
    with patch("backend.db.accounts.get_pool", return_value=_Pool(cursor)):
        assert await get_active_account() is None

    assert cursor.sql
    assert "ORDER BY updated_at DESC" in cursor.sql[0]


async def test_get_active_account_owner_scoped_orders_by_most_recently_updated():
    cursor = _Cursor()
    with patch("backend.db.accounts.get_pool", return_value=_Pool(cursor)):
        assert await get_active_account(owner_user_id="user-1") is None

    assert cursor.sql
    assert "ORDER BY updated_at DESC" in cursor.sql[0]
    assert "owner_user_id" in cursor.sql[0]
