"""Shared CDP session lock tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.cdp_session_lock import (
    CdpSessionBusyError,
    cdp_session_holder,
    hold_cdp_session,
    is_cdp_session_busy,
    is_cdp_session_busy_async,
    reset_cdp_session_locks_for_tests,
)


@pytest.fixture(autouse=True)
def _reset_locks(monkeypatch):
    # Disable cross-feature cool-down so lock unit tests stay fast.
    monkeypatch.setenv("XHS_BROWSER_ACTION_COOLDOWN_SECONDS", "0")
    from backend.services.xhs_risk_gate import reset_gates_for_tests

    reset_cdp_session_locks_for_tests()
    reset_gates_for_tests()
    yield
    reset_cdp_session_locks_for_tests()
    reset_gates_for_tests()


@pytest.mark.asyncio
async def test_hold_cdp_session_exclusive_nonblocking():
    async with hold_cdp_session(account_id="a1", owner="publisher", wait=True):
        assert is_cdp_session_busy(account_id="a1")
        assert cdp_session_holder(account_id="a1") == "publisher"
        with pytest.raises(CdpSessionBusyError) as exc:
            async with hold_cdp_session(
                account_id="a1", owner="creator_stats", wait=False
            ):
                pass
        assert exc.value.holder == "publisher"
    assert not is_cdp_session_busy(account_id="a1")


@pytest.mark.asyncio
async def test_different_accounts_do_not_block():
    async with hold_cdp_session(account_id="a1", owner="pub", wait=True):
        async with hold_cdp_session(account_id="a2", owner="eng", wait=False):
            assert cdp_session_holder(account_id="a2") == "eng"


@pytest.mark.asyncio
async def test_wait_timeout_raises_busy():
    async with hold_cdp_session(account_id="a1", owner="pub", wait=True):
        with pytest.raises(CdpSessionBusyError):
            async with hold_cdp_session(
                account_id="a1", owner="other", wait=True, timeout=0.05
            ):
                pass


@pytest.mark.asyncio
async def test_pg_busy_raises_when_pool_up(monkeypatch):
    """When Postgres reports the advisory lock is held, fail fast (non-wait)."""
    monkeypatch.setattr(
        "backend.services.cdp_session_lock._try_acquire_pg",
        AsyncMock(return_value=("busy", None)),
    )
    with pytest.raises(CdpSessionBusyError) as exc:
        async with hold_cdp_session(account_id="a1", owner="stats", wait=False):
            pass
    assert exc.value.holder == "remote"


@pytest.mark.asyncio
async def test_pg_unavailable_degrades_to_local(monkeypatch):
    monkeypatch.setattr(
        "backend.services.cdp_session_lock._try_acquire_pg",
        AsyncMock(return_value=("unavailable", None)),
    )
    async with hold_cdp_session(account_id="a1", owner="stats", wait=False):
        assert is_cdp_session_busy(account_id="a1")


@pytest.mark.asyncio
async def test_async_busy_probe_uses_local_first():
    async with hold_cdp_session(account_id="a1", owner="pub", wait=True):
        assert await is_cdp_session_busy_async(account_id="a1") is True
    assert await is_cdp_session_busy_async(account_id="a1") is False

@pytest.mark.asyncio
async def test_snapshot_cdp_sessions_shows_holder(monkeypatch):
    monkeypatch.setattr(
        "backend.services.cdp_session_lock._try_acquire_pg",
        AsyncMock(return_value=("unavailable", None)),
    )
    from backend.services.cdp_session_lock import snapshot_cdp_sessions

    async with hold_cdp_session(account_id="a1", owner="publisher", wait=True):
        rows = snapshot_cdp_sessions()
        assert any(r["holder"] == "publisher" and "account:a1" in r["key"] for r in rows)
    assert snapshot_cdp_sessions() == []
