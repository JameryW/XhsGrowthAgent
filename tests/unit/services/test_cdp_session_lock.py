"""Shared CDP session lock tests."""

from __future__ import annotations

import asyncio

import pytest

from backend.services.cdp_session_lock import (
    CdpSessionBusyError,
    cdp_session_holder,
    hold_cdp_session,
    is_cdp_session_busy,
    reset_cdp_session_locks_for_tests,
)


@pytest.fixture(autouse=True)
def _reset_locks():
    reset_cdp_session_locks_for_tests()
    yield
    reset_cdp_session_locks_for_tests()


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
