"""Tests for console_users DB module — password hashing + verify flow.

Hashing is sync stdlib (pbkdf2_hmac) — testable without DB.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


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
    # execute on the conn itself for non-cursor calls
    mock_conn.execute = AsyncMock()
    return mock_conn


@pytest.fixture(autouse=True)
def _fast_pbkdf2(monkeypatch: pytest.MonkeyPatch):
    """Shrink PBKDF2 rounds for the test suite.

    The tests verify hash/verify wiring (roundtrip, unique salt, login match),
    not the 200k-round cost — full rounds only add wall-clock here.
    """
    monkeypatch.setattr("backend.db.console_users._PBKDF2_ROUNDS", 1_000)


def test_password_hash_roundtrip():
    """Correct password verifies; wrong password rejects."""
    from backend.db.console_users import _hash_password, _verify_password

    h = _hash_password("hunter2")
    assert _verify_password("hunter2", h)
    assert not _verify_password("hunter3", h)


def test_password_hash_unique_salt():
    """Hashing the same password twice produces different output (random salt)."""
    from backend.db.console_users import _hash_password

    assert _hash_password("hunter2") != _hash_password("hunter2")


def test_password_verify_malformed_hash_fails_closed():
    """Garbage stored hashes return False, never True or raise."""
    from backend.db.console_users import _verify_password

    assert not _verify_password("hunter2", "garbage")
    assert not _verify_password("hunter2", "")
    assert not _verify_password("hunter2", "$$$")
    assert not _verify_password("hunter2", "md5$1$abc$def")  # wrong algo prefix


@pytest.mark.asyncio
async def test_verify_login_returns_user_on_match():
    """verify_login returns ConsoleUserRow when password matches."""
    from backend.db.console_users import _hash_password, verify_login

    pwd_hash = _hash_password("hunter2")

    cursor = AsyncMock()
    cursor.fetchone.return_value = {
        "id": "u-1",
        "username": "alice",
        "password_hash": pwd_hash,
        "created_at": "2026-06-19T00:00:00",
        "last_login_at": None,
    }
    conn = _make_mock_conn(cursor)
    pool = _make_mock_pool(conn)

    with patch("backend.db.console_users.get_pool", return_value=pool):
        user = await verify_login("alice", "hunter2")

    assert user is not None
    assert user.id == "u-1"
    assert user.username == "alice"


@pytest.mark.asyncio
async def test_verify_login_returns_none_on_wrong_password():
    """verify_login returns None when password doesn't match."""
    from backend.db.console_users import _hash_password, verify_login

    cursor = AsyncMock()
    cursor.fetchone.return_value = {
        "id": "u-1",
        "username": "alice",
        "password_hash": _hash_password("hunter2"),
        "created_at": "2026-06-19T00:00:00",
        "last_login_at": None,
    }
    conn = _make_mock_conn(cursor)
    pool = _make_mock_pool(conn)

    with patch("backend.db.console_users.get_pool", return_value=pool):
        user = await verify_login("alice", "wrong-password")

    assert user is None


@pytest.mark.asyncio
async def test_verify_login_returns_none_on_unknown_user():
    """verify_login returns None when user not found."""
    from backend.db.console_users import verify_login

    cursor = AsyncMock()
    cursor.fetchone.return_value = None
    conn = _make_mock_conn(cursor)
    pool = _make_mock_pool(conn)

    with patch("backend.db.console_users.get_pool", return_value=pool):
        user = await verify_login("nobody", "anything")

    assert user is None


if __name__ == "__main__":
    import asyncio

    test_password_hash_roundtrip()
    test_password_hash_unique_salt()
    test_password_verify_malformed_hash_fails_closed()
    asyncio.run(test_verify_login_returns_user_on_match())
    asyncio.run(test_verify_login_returns_none_on_wrong_password())
    asyncio.run(test_verify_login_returns_none_on_unknown_user())
    print("All console_users tests passed")
