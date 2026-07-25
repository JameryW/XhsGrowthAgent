"""Shared fixtures for creator-stats unit tests."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest

from backend.api.deps import get_current_user
from backend.db.accounts import AccountRow
from backend.db.creator_stats import _reset_memory_store as _reset_stats

if TYPE_CHECKING:
    from collections.abc import Iterator

    from fastapi import FastAPI

TEST_USER = {"id": "user-test", "username": "tester"}


@pytest.fixture(autouse=True)
def _clear_creator_stats():
    """Prevent cross-test pollution of in-memory note stats."""
    _reset_stats()
    yield
    _reset_stats()


@pytest.fixture(autouse=True)
def _deterministic_enrichment(monkeypatch):
    """Keep crawl behavior deterministic unless a test opts into randomness.

    Production defaults randomly skip whole enrichment stages (light runs) and
    individual notes; tests that are not about that randomness must see every
    candidate visited every time.
    """
    monkeypatch.setenv("CREATOR_STATS_LIGHT_RUN_CHANCE", "0")
    monkeypatch.setenv("CREATOR_STATS_ENRICH_SKIP_CHANCE", "0")
    monkeypatch.setenv("CREATOR_STATS_PAGE_STOP_CHANCE", "0")


@contextmanager
def grant_test_user(app: FastAPI) -> Iterator[None]:
    """Authenticate requests as a console user who owns any requested account.

    Private routes resolve ``Depends(get_current_user)`` and then run
    ``account_scope`` ownership checks; override the dependency and stub the
    account lookup so every requested account id is owned by the test user.
    """

    async def _user() -> dict[str, str]:
        return TEST_USER

    async def _get_account(account_id: str) -> AccountRow:
        return AccountRow(
            id=account_id,
            name=account_id,
            is_active=True,
            owner_user_id=TEST_USER["id"],
        )

    app.dependency_overrides[get_current_user] = _user
    try:
        with patch(
            "backend.api.account_scope.get_account",
            new_callable=AsyncMock,
            side_effect=_get_account,
        ):
            yield
    finally:
        app.dependency_overrides.pop(get_current_user, None)
