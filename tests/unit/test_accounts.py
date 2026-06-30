"""Tests for accounts DB module (unit-level, mock-based).

After the console-account-system refactor, accounts hold only XHS_KEYS
(XHS_COOKIE, XHS_USER_ID). Other keys are filtered out and live in
backend.db.system_config instead.
"""

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
async def test_set_and_list_credentials():
    """set_credentials stores XHS-key values; list_credentials returns masked."""
    from backend.db.accounts import list_credentials, set_credentials
    from backend.db.crypto import encrypt_value

    set_conn = AsyncMock()
    set_pool = _make_mock_pool(set_conn)

    with patch("backend.db.accounts.get_pool", return_value=set_pool):
        await set_credentials("acc-1", {"XHS_COOKIE": "abc123def456ghi789"})

    assert set_conn.execute.called

    encrypted = encrypt_value("abc123def456ghi789")
    list_cursor = AsyncMock()
    list_cursor.fetchall.return_value = [
        {"account_id": "acc-1", "key_name": "XHS_COOKIE", "encrypted_value": encrypted}
    ]
    list_conn = _make_mock_conn(list_cursor)
    list_pool = _make_mock_pool(list_conn)

    with patch("backend.db.accounts.get_pool", return_value=list_pool):
        creds = await list_credentials("acc-1")

    assert len(creds) == 1
    assert creds[0].key_name == "XHS_COOKIE"
    assert creds[0].value == "abc123def456ghi789"
    assert creds[0].masked == "abc1...i789"


@pytest.mark.asyncio
async def test_set_credentials_drops_non_xhs_keys():
    """Non-XHS keys (e.g. LLM keys) are silently dropped — they belong in system_config."""
    from backend.db.accounts import set_credentials

    set_conn = AsyncMock()
    set_pool = _make_mock_pool(set_conn)

    with patch("backend.db.accounts.get_pool", return_value=set_pool):
        await set_credentials("acc-1", {"ANTHROPIC_API_KEY": "sk-ant-xxxxxxxxxxxx"})

    # No INSERT/DELETE issued for the non-XHS key.
    assert not set_conn.execute.called


@pytest.mark.asyncio
async def test_activate_credentials_sets_env():
    """activate_credentials loads XHS_KEYS values into os.environ."""
    from backend.db.accounts import activate_credentials
    from backend.db.crypto import encrypt_value

    encrypted = encrypt_value("cookie-value-123")

    list_cursor = AsyncMock()
    list_cursor.fetchall.return_value = [
        {"account_id": "acc-1", "key_name": "XHS_COOKIE", "encrypted_value": encrypted}
    ]
    list_conn = _make_mock_conn(list_cursor)
    pool = _make_mock_pool(list_conn)

    os.environ.pop("XHS_COOKIE", None)

    with patch("backend.db.accounts.get_pool", return_value=pool):
        loaded = await activate_credentials("acc-1")

    assert "XHS_COOKIE" in loaded
    assert os.environ.get("XHS_COOKIE") == "cookie-value-123"

    os.environ.pop("XHS_COOKIE", None)


@pytest.mark.asyncio
async def test_deactivate_credentials_removes_env():
    """deactivate_credentials removes managed keys from os.environ."""
    from backend.db.accounts import deactivate_credentials

    os.environ["XHS_COOKIE"] = "should-be-removed"
    os.environ["XHS_USER_ID"] = "should-be-removed"

    await deactivate_credentials()

    assert "XHS_COOKIE" not in os.environ
    assert "XHS_USER_ID" not in os.environ


@pytest.mark.asyncio
async def test_set_credentials_empty_value_deletes():
    """Setting a credential to empty string should delete it from DB."""
    from backend.db.accounts import set_credentials

    set_conn = AsyncMock()
    set_pool = _make_mock_pool(set_conn)

    with patch("backend.db.accounts.get_pool", return_value=set_pool):
        await set_credentials("acc-1", {"XHS_COOKIE": ""})

    calls = set_conn.execute.call_args_list
    assert any("DELETE" in str(c) for c in calls)


@pytest.mark.asyncio
async def test_activate_clears_previous_account_keys():
    """Switching active account must wipe stale XHS keys before loading new ones."""
    from backend.db.accounts import activate_credentials
    from backend.db.crypto import encrypt_value

    os.environ["XHS_COOKIE"] = "stale-cookie-A"
    os.environ["XHS_USER_ID"] = "stale-user-A"

    encrypted = encrypt_value("new-cookie-B")
    list_cursor = AsyncMock()
    list_cursor.fetchall.return_value = [
        {"account_id": "acc-B", "key_name": "XHS_COOKIE", "encrypted_value": encrypted}
    ]
    list_conn = _make_mock_conn(list_cursor)
    pool = _make_mock_pool(list_conn)

    with patch("backend.db.accounts.get_pool", return_value=pool):
        loaded = await activate_credentials("acc-B")

    assert os.environ.get("XHS_COOKIE") == "new-cookie-B"
    assert "XHS_USER_ID" not in os.environ, "stale user_id from previous account leaked"
    assert loaded == {"XHS_COOKIE": "new-cookie-B"}

    os.environ.pop("XHS_COOKIE", None)


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


if __name__ == "__main__":
    import asyncio

    asyncio.run(test_set_and_list_credentials())
    asyncio.run(test_set_credentials_drops_non_xhs_keys())
    asyncio.run(test_activate_credentials_sets_env())
    asyncio.run(test_deactivate_credentials_removes_env())
    asyncio.run(test_set_credentials_empty_value_deletes())
    asyncio.run(test_activate_clears_previous_account_keys())
    print("All accounts tests passed")
