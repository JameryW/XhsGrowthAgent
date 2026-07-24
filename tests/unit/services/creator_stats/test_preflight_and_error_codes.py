"""Login preflight, error_code classification, and post-login sync gating."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from backend.services.creator_stats.pipeline import (
    clear_post_login_sync_gate,
    preflight_creator_login,
    sync_account_stats,
    sync_after_login,
)
from backend.services.creator_stats.types import (
    ERROR_AUTH_EXPIRED,
    ERROR_BROWSER_UNAVAILABLE,
    ERROR_FETCH_FAILED,
    SyncResult,
    classify_sync_error,
)


def test_classify_sync_error_auth_and_browser():
    assert (
        classify_sync_error("creator center login page is showing", status_code=None)
        == ERROR_AUTH_EXPIRED
    )
    assert classify_sync_error("x", status_code=401) == ERROR_AUTH_EXPIRED
    assert classify_sync_error("CDP connect failed: refused") == ERROR_BROWSER_UNAVAILABLE
    assert classify_sync_error("timeout waiting for notes") == ERROR_FETCH_FAILED


def test_sync_result_auto_fills_error_code():
    r = SyncResult(account_id="a", error="re-login the bound Chrome profile")
    assert r.error_code == ERROR_AUTH_EXPIRED
    assert r.to_dict()["error_code"] == ERROR_AUTH_EXPIRED


@pytest.mark.asyncio
async def test_preflight_blocks_stale_id_token():
    with patch(
        "backend.services.xhs_login.inspect_profile_login_status",
        new=AsyncMock(
            return_value={
                "status": "logged_out",
                "is_logged_in": False,
                "reason": "stale_id_token",
                "signals": ["id_token"],
            }
        ),
    ):
        blocked = await preflight_creator_login("acc-1", "http://127.0.0.1:9225")
    assert blocked is not None
    assert blocked.account_synced is False
    assert blocked.error_code == ERROR_AUTH_EXPIRED
    assert "id_token" in (blocked.error or "")


@pytest.mark.asyncio
async def test_preflight_allows_logged_in():
    with patch(
        "backend.services.xhs_login.inspect_profile_login_status",
        new=AsyncMock(
            return_value={
                "status": "logged_in",
                "is_logged_in": True,
                "reason": "strong_cookie",
                "signals": ["access-token-creator.xiaohongshu.com"],
            }
        ),
    ):
        assert await preflight_creator_login("acc-1", "http://127.0.0.1:9225") is None


@pytest.mark.asyncio
async def test_preflight_allows_www_session_pair():
    with patch(
        "backend.services.xhs_login.inspect_profile_login_status",
        new=AsyncMock(
            return_value={
                "status": "logged_in",
                "is_logged_in": True,
                "reason": "strong_cookie",
                "signals": ["id_token", "web_session"],
            }
        ),
    ):
        assert await preflight_creator_login("acc-1", "http://127.0.0.1:9225") is None


@pytest.mark.asyncio
async def test_preflight_inconclusive_does_not_block():
    with patch(
        "backend.services.xhs_login.inspect_profile_login_status",
        new=AsyncMock(
            return_value={
                "status": "unavailable",
                "is_logged_in": False,
                "reason": "cdp_unreachable",
            }
        ),
    ):
        assert await preflight_creator_login("acc-1", "http://127.0.0.1:9225") is None


@pytest.mark.asyncio
async def test_sync_account_stats_uses_preflight_for_cdp_path():
    blocked = SyncResult(
        account_id="acc-1",
        source="creator_statistics",
        error="stale",
        error_code=ERROR_AUTH_EXPIRED,
    )
    with patch(
        "backend.services.creator_stats.pipeline.preflight_creator_login",
        new=AsyncMock(return_value=blocked),
    ) as preflight:
        result = await sync_account_stats(
            "acc-1",
            cdp_endpoint="http://127.0.0.1:9225",
            run_creative_analysis=False,
        )
    preflight.assert_awaited_once()
    assert result is blocked
    assert result.error_code == ERROR_AUTH_EXPIRED


@pytest.mark.asyncio
async def test_sync_after_login_is_once_per_account():
    clear_post_login_sync_gate("acc-pl")
    ok = SyncResult(
        account_id="acc-pl",
        account_synced=True,
        notes_imported=1,
        source="creator_statistics",
    )
    with (
        patch(
            "backend.db.accounts.get_account_cdp_endpoint",
            new=AsyncMock(return_value="http://127.0.0.1:9225"),
        ),
        patch(
            "backend.services.creator_stats.pipeline.sync_account_stats",
            new=AsyncMock(return_value=ok),
        ) as sync,
    ):
        r1 = await sync_after_login("acc-pl")
        r2 = await sync_after_login("acc-pl")
    assert r1 is not None and r1.account_synced
    assert r2 is None
    sync.assert_awaited_once()
    clear_post_login_sync_gate("acc-pl")
