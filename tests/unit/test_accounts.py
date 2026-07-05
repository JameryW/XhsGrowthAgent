"""Tests for accounts DB module (unit-level, mock-based)."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def setup_crypto():
    """Ensure ENCRYPTION_KEY is set for tests."""
    from backend.db.crypto import generate_key

    os.environ["ENCRYPTION_KEY"] = generate_key()
    import backend.db.crypto as crypto_mod

    crypto_mod._fernet = None
    yield
    os.environ.pop("ENCRYPTION_KEY", None)
    crypto_mod._fernet = None


def _make_mock_pool(conn):
    """Build a mock pool whose .connection() returns conn as async context manager."""
    mock_pool = MagicMock()

    @asynccontextmanager
    async def conn_ctx(*_args, **_kwargs):
        yield conn

    mock_pool.connection = conn_ctx
    return mock_pool


def _make_mock_conn(cursor):
    """Build a mock connection whose .cursor() returns cursor as async context manager."""
    mock_conn = MagicMock()

    @asynccontextmanager
    async def cursor_ctx(*_args, **_kwargs):
        yield cursor

    mock_conn.cursor = cursor_ctx
    return mock_conn


@pytest.mark.asyncio
async def test_list_legacy_credentials_returns_masked():
    """Legacy account_credentials rows can still be read for migrations."""
    from backend.db.accounts import list_credentials
    from backend.db.crypto import encrypt_value

    encrypted = encrypt_value("abc123def456ghi789")
    list_cursor = AsyncMock()
    list_cursor.fetchall.return_value = [
        {"account_id": "acc-1", "key_name": "LEGACY_KEY", "encrypted_value": encrypted}
    ]
    list_conn = _make_mock_conn(list_cursor)
    list_pool = _make_mock_pool(list_conn)

    with patch("backend.db.accounts.get_pool", return_value=list_pool):
        creds = await list_credentials("acc-1")

    assert len(creds) == 1
    assert creds[0].key_name == "LEGACY_KEY"
    assert creds[0].value == "abc123def456ghi789"
    assert creds[0].masked == "abc1...i789"


@pytest.mark.asyncio
async def test_delete_account_uses_rowcount():
    """Regression: psycopg3 conn.execute() returns a Cursor, not a status string.

    Before the fix, `tag == "DELETE 1"` was always False, so DELETE always
    appeared to fail (404) even after the row was actually removed.
    """
    from backend.db.accounts import delete_account

    # Cursor with rowcount=1 → success
    cur = MagicMock()
    cur.rowcount = 1
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value=cur)
    pool = _make_mock_pool(conn)

    with patch("backend.db.accounts.get_pool", return_value=pool):
        ok = await delete_account("acc-1")
    assert ok is True

    # rowcount=0 → not found
    cur.rowcount = 0
    with patch("backend.db.accounts.get_pool", return_value=pool):
        ok = await delete_account("acc-missing")
    assert ok is False


@pytest.mark.asyncio
async def test_get_account_cdp_endpoint_returns_endpoint_when_port_bound():
    """Account with cdp_port > 0 → endpoint string with the resolved host."""
    from backend.db.accounts import AccountRow, get_account_cdp_endpoint

    account = AccountRow(id="acc-1", name="acc", is_active=True, cdp_port=9223)
    with (
        patch("backend.db.accounts.get_account", new_callable=AsyncMock, return_value=account),
        patch("backend.db.pool.is_pool_ready", return_value=True),
        patch("backend.db.accounts._resolve_cdp_host", return_value="127.0.0.1"),
    ):
        endpoint = await get_account_cdp_endpoint("acc-1")
    assert endpoint == "http://127.0.0.1:9223"


@pytest.mark.asyncio
async def test_get_account_cdp_endpoint_empty_when_port_zero():
    """Account with cdp_port=0 → empty string (caller falls back to global)."""
    from backend.db.accounts import AccountRow, get_account_cdp_endpoint

    account = AccountRow(id="acc-1", name="acc", is_active=True, cdp_port=0)
    with (
        patch("backend.db.accounts.get_account", new_callable=AsyncMock, return_value=account),
        patch("backend.db.pool.is_pool_ready", return_value=True),
    ):
        endpoint = await get_account_cdp_endpoint("acc-1")
    assert endpoint == ""


@pytest.mark.asyncio
async def test_get_account_cdp_endpoint_empty_when_account_missing():
    """Non-existent account → empty string (no port binding to resolve)."""
    from backend.db.accounts import get_account_cdp_endpoint

    with (
        patch("backend.db.accounts.get_account", new_callable=AsyncMock, return_value=None),
        patch("backend.db.pool.is_pool_ready", return_value=True),
    ):
        endpoint = await get_account_cdp_endpoint("no-such-acc")
    assert endpoint == ""


@pytest.mark.asyncio
async def test_get_account_cdp_endpoint_empty_when_db_unavailable():
    """Pool not ready → empty string (graceful degradation, no DB hit)."""
    from backend.db.accounts import get_account_cdp_endpoint

    get_acc = AsyncMock()
    with (
        patch("backend.db.pool.is_pool_ready", return_value=False),
        patch("backend.db.accounts.get_account", get_acc),
    ):
        endpoint = await get_account_cdp_endpoint("acc-1")
    assert endpoint == ""
    get_acc.assert_not_awaited()  # must short-circuit before touching the DB


@pytest.mark.asyncio
async def test_allocate_cdp_port_skips_occupied():
    """Port allocation picks the first free port after base+1, skipping used ones."""
    from backend.db.accounts import AccountRow, _allocate_cdp_port

    settings = MagicMock()
    settings.platform.cdp_base_port = 9222

    # Accounts already holding 9223 and 9225 → allocator should pick 9224.
    existing = [
        AccountRow(id="a1", name="a1", cdp_port=9223),
        AccountRow(id="a2", name="a2", cdp_port=9225),
    ]
    with (
        patch("backend.db.pool.is_pool_ready", return_value=True),
        patch("backend.db.accounts.list_accounts", new_callable=AsyncMock, return_value=existing),
    ):
        port = await _allocate_cdp_port(settings)
    assert port == 9224


@pytest.mark.asyncio
async def test_allocate_cdp_port_returns_zero_when_db_unavailable():
    """Pool not ready → 0 (account created without port binding, falls back to global)."""
    from backend.db.accounts import _allocate_cdp_port

    settings = MagicMock()
    settings.platform.cdp_base_port = 9222
    with patch("backend.db.pool.is_pool_ready", return_value=False):
        port = await _allocate_cdp_port(settings)
    assert port == 0


@pytest.mark.asyncio
async def test_ensure_tables_runs_alter_column_idempotently():
    """ensure_tables issues ALTER TABLE ADD COLUMN IF NOT EXISTS for both new columns.

    This locks the migration pattern (idempotent upgrade) — running ensure_tables
    on a pre-existing accounts table must not fail and must issue both ALTERs.
    """
    from backend.db.accounts import ensure_tables

    conn = AsyncMock()
    pool = _make_mock_pool(conn)
    with patch("backend.db.accounts.get_pool", return_value=pool):
        await ensure_tables()

    executed_sql = [str(c.args[0]) if c.args else "" for c in conn.execute.call_args_list]
    assert any("ADD COLUMN IF NOT EXISTS chrome_profile_path" in sql for sql in executed_sql)
    assert any("ADD COLUMN IF NOT EXISTS cdp_port" in sql for sql in executed_sql)


if __name__ == "__main__":
    import asyncio

    asyncio.run(test_list_legacy_credentials_returns_masked())
    print("All accounts tests passed")
