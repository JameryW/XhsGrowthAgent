"""Blocking CDP-host resolution must never run on the event loop.

``socket.gethostbyname('host.containers.internal')`` spends the full DNS timeout
on a host where that name does not exist (~12s on Windows).  Called from inside an
async workflow node it blocked the loop, which made every API request—including
``/status``—wait for the whole workflow.  The resolver now runs via
``asyncio.to_thread`` and its answer is cached.
"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_cdp_host_resolution_runs_off_the_event_loop(monkeypatch):
    from backend.db import accounts

    def blocking_resolve() -> str:
        time.sleep(0.25)
        return "10.0.0.5"

    monkeypatch.setattr(accounts, "_resolve_cdp_host", blocking_resolve)
    monkeypatch.setattr("backend.db.pool.is_pool_ready", lambda: True)

    async def fake_get_account(_account_id: str):
        return SimpleNamespace(cdp_port=9223)

    monkeypatch.setattr(accounts, "get_account", fake_get_account)

    ticks = 0

    async def ticker() -> None:
        nonlocal ticks
        for _ in range(10):
            await asyncio.sleep(0.02)
            ticks += 1

    endpoint, _ = await asyncio.gather(accounts.get_account_cdp_endpoint("acct"), ticker())

    assert endpoint == "http://10.0.0.5:9223"
    # If the DNS sleep ran on the loop, the ticker could not progress.
    assert ticks >= 5


def test_cdp_host_resolution_is_cached():
    from backend.db import accounts

    accounts._resolve_cdp_host.cache_clear()
    try:
        first = accounts._resolve_cdp_host()
        second = accounts._resolve_cdp_host()
        assert first == second
        assert accounts._resolve_cdp_host.cache_info().hits >= 1
    finally:
        accounts._resolve_cdp_host.cache_clear()
