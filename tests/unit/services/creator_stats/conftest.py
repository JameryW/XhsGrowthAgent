"""Shared fixtures for creator-stats unit tests."""

from __future__ import annotations

import pytest

from backend.db.creator_stats import _reset_memory_store as _reset_stats


@pytest.fixture(autouse=True)
def _clear_creator_stats():
    """Prevent cross-test pollution of in-memory note stats."""
    _reset_stats()
    yield
    _reset_stats()
