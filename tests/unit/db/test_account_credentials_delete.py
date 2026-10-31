"""``account_credentials`` delete path (票 5ax).

Added for the outreach policy's management write: *clearing* a policy means
removing the two rows so the deployment default applies again.  An empty-value
upsert cannot express that — a row is a statement (see
``services.xhs_credentials``), and an empty one would keep the account final.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from backend.db.accounts import delete_credential

pytestmark = pytest.mark.asyncio


class _Cursor:
    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount


class _Connection:
    def __init__(self, log: list[tuple[str, Any]], rowcount: int) -> None:
        self._log = log
        self._rowcount = rowcount

    async def __aenter__(self) -> _Connection:
        return self

    async def __aexit__(self, *_args: Any) -> None:
        return None

    async def execute(self, sql: str, params: Any = None) -> _Cursor:
        self._log.append((sql, params))
        return _Cursor(self._rowcount)


class _Pool:
    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount
        self.log: list[tuple[str, Any]] = []

    def connection(self) -> _Connection:
        return _Connection(self.log, self.rowcount)


async def test_the_delete_is_keyed_by_account_and_key() -> None:
    pool = _Pool(rowcount=1)

    with patch("backend.db.accounts.get_pool", return_value=pool):
        removed = await delete_credential("acc-1", "XHS_OUTREACH_MODE")

    assert removed is True
    assert len(pool.log) == 1
    sql, params = pool.log[0]
    assert "DELETE FROM account_credentials" in sql
    assert "account_id = %s" in sql and "key_name = %s" in sql
    assert params == ("acc-1", "XHS_OUTREACH_MODE")


async def test_deleting_a_missing_row_is_false_not_an_error() -> None:
    """Idempotent: clearing an unset policy must be a no-op, not a failure."""
    pool = _Pool(rowcount=0)

    with patch("backend.db.accounts.get_pool", return_value=pool):
        removed = await delete_credential("acc-1", "XHS_OUTREACH_DAILY_PROACTIVE_CAP")

    assert removed is False
