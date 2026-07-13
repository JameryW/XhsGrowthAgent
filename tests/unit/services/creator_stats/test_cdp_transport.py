"""CDP browser-page transport tests for creator stats.

Creator Center signs requests in its own page JavaScript.  These tests stub
the native-page capture boundary so they never need a real Chrome, while
covering the production contract: no copied Cookie/signature headers and the
actual Note Manager response shape is normalized into note stats.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.creator_stats.client import (
    ACCOUNT_OVERVIEW_PATH,
    CREATOR_PROFILE_PATH,
    NOTE_LIST_PATH,
    CdpTransport,
    CreatorStatsClient,
)

pytestmark = pytest.mark.asyncio


def _native_account() -> dict:
    return {
        "code": 0,
        "success": True,
        "data": {
            "seven": {"view_count": 7, "like_count": 2, "publish_note_num": 1},
            "thirty": {"view_count": 30, "like_count": 8, "publish_note_num": 2},
        },
    }


def _native_note() -> dict:
    return {
        "id": "note-1",
        "display_title": "真实笔记",
        "view_count": 100,
        "likes": 11,
        "comments_count": 2,
        "collected_count": 3,
        "shared_count": 4,
        "time": "2026-07-13 10:00",
        "type": "normal",
        "images_list": [{"url": "https://img.example/cover.jpg"}],
    }


def _native_profile() -> dict:
    return {
        "code": 0,
        "success": True,
        "data": {
            "userId": "creator-1",
            "userName": "真实创作者",
            "redId": "creator_red",
            "userAvatar": "https://img.example/avatar.jpg",
            "userDesc": "真实创作者简介",
            "role": "creator",
            "zone": "上海",
            "phone": "must-not-be-persisted",
        },
    }


async def test_cdp_fetch_all_uses_native_creator_page_data():
    """CDP uses the page-captured payload, not a copied Cookie header/API call."""
    transport = CdpTransport("http://127.0.0.1:9222")
    transport.fetch_creator_center = AsyncMock(
        return_value=(_native_account(), _native_profile(), [_native_note()])
    )
    client = CreatorStatsClient(cookie="must-not-be-used", transport=transport)

    bundle = await client.fetch_all("acct", period="30d", max_pages=3)

    transport.fetch_creator_center.assert_awaited_once_with(max_pages=3)
    assert bundle.account.views == 30
    assert bundle.account.likes == 8
    assert bundle.account.note_count == 2
    assert bundle.account.creator_user_id == "creator-1"
    assert bundle.account.creator_name == "真实创作者"
    assert bundle.account.red_id == "creator_red"
    assert bundle.account.avatar_url == "https://img.example/avatar.jpg"
    assert bundle.account.bio == "真实创作者简介"
    assert bundle.account.creator_role == "creator"
    assert bundle.account.zone == "上海"
    assert "phone" not in bundle.account.to_dict()
    assert len(bundle.notes) == 1
    note = bundle.notes[0]
    assert (note.comments, note.collects, note.shares) == (2, 3, 4)
    assert note.cover_url == "https://img.example/cover.jpg"


async def test_cdp_get_adapts_native_data_without_forwarding_headers():
    transport = CdpTransport("http://127.0.0.1:9222")
    transport.fetch_creator_center = AsyncMock(
        return_value=(_native_account(), _native_profile(), [_native_note()])
    )

    status, account = await transport.get(
        f"https://creator.xiaohongshu.com{ACCOUNT_OVERVIEW_PATH}",
        headers={"Cookie": "must-not-be-forwarded", "x-s": "stale"},
        params={"date_type": 2},
    )
    assert status == 200
    assert account == _native_account()

    status, profile = await transport.get(
        f"https://creator.xiaohongshu.com{CREATOR_PROFILE_PATH}",
        headers={"Cookie": "must-not-be-forwarded"},
    )
    assert status == 200
    assert profile == _native_profile()

    status, notes = await transport.get(
        f"https://creator.xiaohongshu.com{NOTE_LIST_PATH}",
        headers={"Cookie": "must-not-be-forwarded"},
        params={"page": 0},
    )
    assert status == 200
    assert notes == {"data": {"notes": [_native_note()]}}
    assert transport.fetch_creator_center.await_count == 3


async def test_cdp_transport_aclose_clears_state():
    transport = CdpTransport("http://127.0.0.1:9222")
    browser = MagicMock()
    browser.close = AsyncMock()
    playwright = MagicMock()
    playwright.stop = AsyncMock()
    transport._browser = browser
    transport._playwright = playwright

    await transport.aclose()

    browser.close.assert_awaited_once()
    playwright.stop.assert_awaited_once()
    assert transport._browser is None
    assert transport._playwright is None
    # Idempotent — safe to call when nothing is connected.
    await transport.aclose()


async def test_client_aclose_safe_for_transport_without_aclose():
    """Back-compat: test-only transports may predate ``aclose``."""

    class _NoCloseTransport:
        async def get(self, url, *, headers, params=None):
            return 200, {}

    client = CreatorStatsClient(transport=_NoCloseTransport())
    await client.aclose()
