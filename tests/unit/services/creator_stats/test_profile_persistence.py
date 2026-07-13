"""Regression coverage for Creator Center public profile persistence."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.db.creator_stats import ensure_tables, get_account_stats


def _make_mock_pool(conn: MagicMock) -> MagicMock:
    pool = MagicMock()

    @asynccontextmanager
    async def connection_context():
        yield conn

    pool.connection = connection_context
    return pool


def _make_mock_conn(cursor: AsyncMock) -> MagicMock:
    conn = MagicMock()

    @asynccontextmanager
    async def cursor_context():
        yield cursor

    conn.cursor = cursor_context
    return conn


@pytest.mark.asyncio
async def test_ensure_tables_adds_public_profile_columns_idempotently():
    """Existing creator-account tables receive every public-profile column."""
    conn = MagicMock()
    conn.execute = AsyncMock()
    pool = _make_mock_pool(conn)

    with (
        patch("backend.db.creator_stats.is_pool_ready", return_value=True),
        patch("backend.db.creator_stats.get_pool", return_value=pool),
    ):
        await ensure_tables()

    statements = [str(call.args[0]) for call in conn.execute.call_args_list]
    for column in (
        "creator_user_id",
        "creator_name",
        "red_id",
        "avatar_url",
        "bio",
        "creator_role",
        "zone",
    ):
        assert any(f"ADD COLUMN IF NOT EXISTS {column}" in sql for sql in statements)


@pytest.mark.asyncio
async def test_get_account_stats_maps_profile_columns_from_postgres_row():
    """Tuple rows preserve the public-profile field order used by the reader query."""
    cursor = AsyncMock()
    cursor.fetchone.return_value = (
        "acct-1",
        "creator-1",
        "昵称",
        "red-id",
        "https://img.example/avatar.jpg",
        "简介",
        "creator",
        "上海",
        100,
        20,
        3,
        4,
        5,
        6,
        7,
        "30d",
        "2026-07-13T00:00:00+00:00",
        "creator_statistics",
    )
    conn = _make_mock_conn(cursor)
    pool = _make_mock_pool(conn)

    with (
        patch("backend.db.creator_stats.is_pool_ready", return_value=True),
        patch("backend.db.creator_stats.get_pool", return_value=pool),
    ):
        account = await get_account_stats("acct-1")

    assert account is not None
    assert account.creator_user_id == "creator-1"
    assert account.creator_name == "昵称"
    assert account.red_id == "red-id"
    assert account.avatar_url == "https://img.example/avatar.jpg"
    assert account.bio == "简介"
    assert account.creator_role == "creator"
    assert account.zone == "上海"
    assert account.views == 100
    assert account.note_count == 7
