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
async def test_set_and_list_credentials():
    """set_credentials stores encrypted values, list_credentials returns masked."""
    from backend.db.accounts import list_credentials, set_credentials
    from backend.db.crypto import encrypt_value

    # set_credentials: uses pool.connection() then conn.execute()
    set_conn = AsyncMock()
    set_pool = _make_mock_pool(set_conn)

    with patch("backend.db.accounts.get_pool", return_value=set_pool):
        await set_credentials("acc-1", {"ANTHROPIC_API_KEY": "sk-ant-1234567890abcdef"})

    assert set_conn.execute.called

    # list_credentials: uses pool.connection() then conn.cursor()
    encrypted = encrypt_value("sk-ant-1234567890abcdef")
    list_cursor = AsyncMock()
    list_cursor.fetchall.return_value = [
        {"account_id": "acc-1", "key_name": "ANTHROPIC_API_KEY", "encrypted_value": encrypted}
    ]
    list_conn = _make_mock_conn(list_cursor)
    list_pool = _make_mock_pool(list_conn)

    with patch("backend.db.accounts.get_pool", return_value=list_pool):
        creds = await list_credentials("acc-1")

    assert len(creds) == 1
    assert creds[0].key_name == "ANTHROPIC_API_KEY"
    assert creds[0].value == "sk-ant-1234567890abcdef"
    assert creds[0].masked == "sk-a...cdef"


@pytest.mark.asyncio
async def test_activate_credentials_sets_env():
    """activate_credentials loads values into os.environ."""
    from backend.db.accounts import activate_credentials
    from backend.db.crypto import encrypt_value

    encrypted = encrypt_value("test-api-key")

    list_cursor = AsyncMock()
    list_cursor.fetchall.return_value = [
        {"account_id": "acc-1", "key_name": "ANTHROPIC_API_KEY", "encrypted_value": encrypted}
    ]
    list_conn = _make_mock_conn(list_cursor)
    pool = _make_mock_pool(list_conn)

    os.environ.pop("ANTHROPIC_API_KEY", None)

    with patch("backend.db.accounts.get_pool", return_value=pool):
        loaded = await activate_credentials("acc-1")

    assert "ANTHROPIC_API_KEY" in loaded
    assert os.environ.get("ANTHROPIC_API_KEY") == "test-api-key"

    # Cleanup
    os.environ.pop("ANTHROPIC_API_KEY", None)


@pytest.mark.asyncio
async def test_deactivate_credentials_removes_env():
    """deactivate_credentials removes managed keys from os.environ."""
    from backend.db.accounts import deactivate_credentials

    os.environ["ANTHROPIC_API_KEY"] = "should-be-removed"
    os.environ["XHS_COOKIE"] = "should-be-removed"

    await deactivate_credentials()

    assert "ANTHROPIC_API_KEY" not in os.environ
    assert "XHS_COOKIE" not in os.environ


@pytest.mark.asyncio
async def test_set_credentials_empty_value_deletes():
    """Setting a credential to empty string should delete it from DB."""
    from backend.db.accounts import set_credentials

    set_conn = AsyncMock()
    set_pool = _make_mock_pool(set_conn)

    with patch("backend.db.accounts.get_pool", return_value=set_pool):
        await set_credentials("acc-1", {"ANTHROPIC_API_KEY": ""})

    # Should have called execute with DELETE, not INSERT
    calls = set_conn.execute.call_args_list
    assert any("DELETE" in str(c) for c in calls)


@pytest.mark.asyncio
async def test_activate_clears_previous_account_keys():
    """Switching active account must wipe stale keys before loading new ones.

    Regression: account A had ANTHROPIC_API_KEY, switching to B (no anthropic
    key) must remove it from os.environ — otherwise agents read stale creds.
    """
    from backend.db.accounts import activate_credentials
    from backend.db.crypto import encrypt_value

    # Simulate previous account having left ANTHROPIC + XHS_COOKIE in env
    os.environ["ANTHROPIC_API_KEY"] = "stale-from-account-A"
    os.environ["XHS_COOKIE"] = "stale-cookie-A"

    # New account B only has OPENAI_API_KEY
    encrypted = encrypt_value("sk-openai-new")
    list_cursor = AsyncMock()
    list_cursor.fetchall.return_value = [
        {"account_id": "acc-B", "key_name": "OPENAI_API_KEY", "encrypted_value": encrypted}
    ]
    list_conn = _make_mock_conn(list_cursor)
    pool = _make_mock_pool(list_conn)

    with patch("backend.db.accounts.get_pool", return_value=pool):
        loaded = await activate_credentials("acc-B")

    assert os.environ.get("OPENAI_API_KEY") == "sk-openai-new"
    assert "ANTHROPIC_API_KEY" not in os.environ, "stale key from previous account leaked"
    assert "XHS_COOKIE" not in os.environ, "stale cookie from previous account leaked"
    assert loaded == {"OPENAI_API_KEY": "sk-openai-new"}

    os.environ.pop("OPENAI_API_KEY", None)


if __name__ == "__main__":
    import asyncio
    asyncio.run(test_set_and_list_credentials())
    asyncio.run(test_activate_credentials_sets_env())
    asyncio.run(test_deactivate_credentials_removes_env())
    asyncio.run(test_set_credentials_empty_value_deletes())
    asyncio.run(test_activate_clears_previous_account_keys())
    print("All accounts tests passed")
