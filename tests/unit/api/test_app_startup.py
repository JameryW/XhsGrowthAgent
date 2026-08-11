from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_postgres_startup_fallback_closes_app_pool(monkeypatch):
    import importlib

    app_module = importlib.import_module("backend.api.app")
    from backend.db import pool as pool_module

    fake_pool = SimpleNamespace(close=AsyncMock())
    monkeypatch.setattr(pool_module, "_pool", fake_pool)

    await app_module._reset_app_pool_after_postgres_failure()

    fake_pool.close.assert_awaited_once()
    assert pool_module._pool is None
