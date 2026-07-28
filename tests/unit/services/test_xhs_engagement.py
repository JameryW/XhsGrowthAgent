"""Regression tests for persistent-CDP engagement safety boundaries."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.xhs_engagement import (
    EngagementConfigurationError,
    XHSEngagement,
)


@pytest.mark.asyncio
async def test_missing_cdp_fails_before_starting_playwright() -> None:
    engagement = XHSEngagement()

    with pytest.raises(EngagementConfigurationError, match="cdp_endpoint"):
        await engagement._ensure_browser()


@pytest.mark.asyncio
async def test_cdp_connects_and_reuses_existing_xhs_page() -> None:
    page = MagicMock(url="https://www.xiaohongshu.com/message")
    context = MagicMock(pages=[page])
    context.new_page = AsyncMock()
    browser = MagicMock(contexts=[context])
    playwright = MagicMock()
    playwright.chromium.connect_over_cdp = AsyncMock(return_value=browser)
    playwright.chromium.launch = AsyncMock()
    playwright.stop = AsyncMock()
    manager = MagicMock()
    manager.start = AsyncMock(return_value=playwright)

    engagement = XHSEngagement(cdp_endpoint="http://127.0.0.1:9224")
    with patch("playwright.async_api.async_playwright", return_value=manager):
        connected = await engagement._ensure_browser()
        selected = await engagement._ensure_page()

    assert connected is browser
    assert selected is page
    playwright.chromium.connect_over_cdp.assert_awaited_once_with("http://127.0.0.1:9224")
    playwright.chromium.launch.assert_not_called()
    context.new_page.assert_not_awaited()
    await engagement.close()
    playwright.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_risk_page_blocks_note_navigation_without_retry() -> None:
    page = MagicMock(url="https://www.xiaohongshu.com/explore/note-1")
    page.evaluate = AsyncMock(return_value="风险控制 安全验证")
    page.goto = AsyncMock()
    engagement = XHSEngagement(cdp_endpoint="http://127.0.0.1:9224")
    engagement._ensure_page = AsyncMock(return_value=page)

    result = await engagement.reply_to_comment(
        note_id="note-1",
        comment_id="comment-1",
        reply_content="回复",
    )

    assert result["status"] == "blocked"
    assert result["error_code"] == "risk_control"
    page.goto.assert_not_awaited()
