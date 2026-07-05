"""Tests for system_config DB module — global config + migration."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def setup_crypto():
    from backend.db.crypto import generate_key

    os.environ["ENCRYPTION_KEY"] = generate_key()
    import backend.db.crypto as crypto_mod

    crypto_mod._fernet = None
    yield
    os.environ.pop("ENCRYPTION_KEY", None)
    crypto_mod._fernet = None


def _make_mock_pool(conn):
    mock_pool = MagicMock()

    @asynccontextmanager
    async def conn_ctx(*_args, **_kwargs):
        yield conn

    mock_pool.connection = conn_ctx
    return mock_pool


def _make_mock_conn(cursor):
    mock_conn = MagicMock()

    @asynccontextmanager
    async def cursor_ctx(*_args, **_kwargs):
        yield cursor

    mock_conn.cursor = cursor_ctx
    mock_conn.execute = AsyncMock()
    return mock_conn


def test_system_key_groups_cover_all_keys():
    """Every SYSTEM_KEY should appear in exactly one group (UI rendering invariant)."""
    from backend.db.system_config import SYSTEM_KEY_GROUPS, SYSTEM_KEYS

    grouped = [k for g in SYSTEM_KEY_GROUPS for k in g["keys"]]
    assert sorted(grouped) == sorted(SYSTEM_KEYS), (
        f"groups have {sorted(grouped)} but SYSTEM_KEYS has {sorted(SYSTEM_KEYS)}"
    )


@pytest.mark.asyncio
async def test_set_config_filters_unknown_keys():
    """Unknown keys are dropped, not written."""
    from backend.db.system_config import set_config

    conn = AsyncMock()
    pool = _make_mock_pool(conn)

    with patch("backend.db.system_config.get_pool", return_value=pool):
        await set_config({"NOT_A_REAL_KEY": "x", "ANTHROPIC_API_KEY": "sk-1234567890"})

    # Should have called execute exactly once (for the valid key)
    assert conn.execute.call_count == 1


@pytest.mark.asyncio
async def test_set_config_empty_value_deletes():
    """Empty string deletes the key."""
    from backend.db.system_config import set_config

    conn = AsyncMock()
    pool = _make_mock_pool(conn)

    with patch("backend.db.system_config.get_pool", return_value=pool):
        await set_config({"ANTHROPIC_API_KEY": ""})

    calls = conn.execute.call_args_list
    assert any("DELETE" in str(c) for c in calls)


@pytest.mark.asyncio
async def test_activate_system_config_pushes_to_environ():
    """activate_system_config decrypts rows and writes to os.environ."""
    from backend.db.crypto import encrypt_value
    from backend.db.system_config import activate_system_config

    encrypted = encrypt_value("sk-test-value-1234")
    cursor = AsyncMock()
    cursor.fetchall.return_value = [
        {
            "key_name": "ANTHROPIC_API_KEY",
            "encrypted_value": encrypted,
            "updated_at": "2026-06-19T00:00:00",
        }
    ]
    conn = _make_mock_conn(cursor)
    pool = _make_mock_pool(conn)

    os.environ.pop("ANTHROPIC_API_KEY", None)

    with patch("backend.db.system_config.get_pool", return_value=pool):
        loaded = await activate_system_config()

    assert "ANTHROPIC_API_KEY" in loaded
    assert os.environ.get("ANTHROPIC_API_KEY") == "sk-test-value-1234"

    os.environ.pop("ANTHROPIC_API_KEY", None)


@pytest.mark.asyncio
async def test_migrate_from_accounts_skips_when_already_populated():
    """Migration is idempotent: no-op once system_config has rows."""
    from backend.db.system_config import migrate_from_accounts

    cursor = AsyncMock()
    cursor.fetchone.return_value = (5,)  # count_config returns 5
    conn = _make_mock_conn(cursor)
    pool = _make_mock_pool(conn)

    with patch("backend.db.system_config.get_pool", return_value=pool):
        n = await migrate_from_accounts()

    assert n == 0


if __name__ == "__main__":
    import asyncio

    test_system_keys_disjoint_from_xhs_keys()
    test_system_key_groups_cover_all_keys()
    asyncio.run(test_set_config_filters_unknown_keys())
    asyncio.run(test_set_config_empty_value_deletes())
    asyncio.run(test_activate_system_config_pushes_to_environ())
    asyncio.run(test_migrate_from_accounts_skips_when_already_populated())
    print("All system_config tests passed")
