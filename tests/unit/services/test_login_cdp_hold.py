"""QR login acquires/releases the shared CDP session lock."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.cdp_session_lock import (
    is_cdp_session_busy,
    reset_cdp_session_locks_for_tests,
)
from backend.services.xhs_login import LoginError, XhsLoginSession


@pytest.fixture(autouse=True)
def _reset():
    reset_cdp_session_locks_for_tests()
    yield
    reset_cdp_session_locks_for_tests()


@pytest.mark.asyncio
async def test_start_busy_raises_login_error(monkeypatch):
    monkeypatch.setattr(
        "backend.services.cdp_session_lock._try_acquire_pg",
        AsyncMock(return_value=("unavailable", None)),
    )
    monkeypatch.setenv("XHS_CDP_LOGIN_LOCK_TIMEOUT_S", "0.05")
    # Hold the lock as publisher first.
    from backend.services.cdp_session_lock import hold_cdp_session

    session = XhsLoginSession("acc-1", "/tmp/profile", cdp_endpoint="http://127.0.0.1:9222")
    async with hold_cdp_session(account_id="acc-1", owner="publisher", wait=True):
        with pytest.raises(LoginError, match="占用"):
            await session.start()


@pytest.mark.asyncio
async def test_stop_releases_cdp_hold(monkeypatch):
    monkeypatch.setattr(
        "backend.services.cdp_session_lock._try_acquire_pg",
        AsyncMock(return_value=("unavailable", None)),
    )
    session = XhsLoginSession("acc-1", "/tmp/profile", cdp_endpoint="http://127.0.0.1:9222")
    await session._ensure_cdp_hold()
    assert is_cdp_session_busy(account_id="acc-1")
    await session.stop()
    assert not is_cdp_session_busy(account_id="acc-1")
