"""Blocking CDP-host resolution must never run on the event loop, and must expire.

``socket.gethostbyname('host.containers.internal')`` spends the full DNS timeout
on a host where that name does not exist (~12s on Windows).  Called from inside an
async workflow node it blocked the loop, which made every API request—including
``/status``—wait for the whole workflow.  The resolver now runs via
``asyncio.to_thread`` and its answer is cached with a TTL so a container host that
resolves late (or one transient failure) does not pin ``127.0.0.1`` until restart.
"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest


@pytest.fixture(autouse=True)
def _clear_host_cache():
    from backend.db import accounts

    accounts._clear_cdp_host_cache()
    yield
    accounts._clear_cdp_host_cache()


def _fake_clock(monkeypatch, start: float = 1000.0):
    from backend.db import accounts

    clock = {"now": start}
    monkeypatch.setattr(accounts, "time", SimpleNamespace(monotonic=lambda: clock["now"]))
    return clock


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

    async def endpoint_call() -> tuple[str, int]:
        endpoint = await accounts.get_account_cdp_endpoint("acct")
        # Sample the tick counter *when the endpoint returns*.  Asserting after
        # asyncio.gather would be vacuous: gather waits for the ticker, so it
        # always reaches 10 even when the resolver blocked the loop.
        return endpoint, ticks

    (endpoint, ticks_at_return), _ = await asyncio.gather(endpoint_call(), ticker())

    assert endpoint == "http://10.0.0.5:9223"
    assert ticks_at_return >= 5  # loop kept running while DNS slept in a thread


def test_cdp_host_failure_is_cached_until_ttl(monkeypatch):
    from backend.db import accounts

    clock = _fake_clock(monkeypatch)
    calls = {"n": 0}

    def failing_resolve() -> str:
        calls["n"] += 1
        raise OSError("name does not exist")

    monkeypatch.setattr(accounts, "_resolve_cdp_host_uncached", failing_resolve)

    assert accounts._resolve_cdp_host() == "127.0.0.1"
    assert accounts._resolve_cdp_host() == "127.0.0.1"
    assert calls["n"] == 1  # cached inside the TTL

    clock["now"] += accounts._CDP_HOST_TTL_SECONDS + 1
    assert accounts._resolve_cdp_host() == "127.0.0.1"
    assert calls["n"] == 2  # TTL expired: a late-resolving container host recovers


def test_cdp_host_success_is_cached(monkeypatch):
    from backend.db import accounts

    _fake_clock(monkeypatch)
    calls = {"n": 0}

    def resolving() -> str:
        calls["n"] += 1
        return "10.0.0.7"

    monkeypatch.setattr(accounts, "_resolve_cdp_host_uncached", resolving)

    assert accounts._resolve_cdp_host() == "10.0.0.7"
    assert accounts._resolve_cdp_host() == "10.0.0.7"
    assert calls["n"] == 1


def test_clear_cache_lets_a_new_host_be_found(monkeypatch):
    from backend.db import accounts

    _fake_clock(monkeypatch)
    monkeypatch.setattr(accounts, "_resolve_cdp_host_uncached", lambda: "127.0.0.1")
    assert accounts._resolve_cdp_host() == "127.0.0.1"

    monkeypatch.setattr(accounts, "_resolve_cdp_host_uncached", lambda: "10.0.0.9")
    accounts._clear_cdp_host_cache()
    assert accounts._resolve_cdp_host() == "10.0.0.9"
