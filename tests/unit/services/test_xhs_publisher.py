"""Tests for XHSPublisher — Playwright-based note publisher.

Covers the real publishing path that previously had no tests. Uses AsyncMock
for the Playwright Page/Browser so tests run without the [browser] extra.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.xhs_publisher import (
    _NOTE_ID_RE,
    PublisherConfigurationError,
    XHSPublisher,
)


@pytest.fixture
def publisher() -> XHSPublisher:
    return XHSPublisher(cookie="a=1; b=2", headless=True)


def _make_image(tmp_path: Path) -> str:
    """Create a tiny fake image file so it passes os.path.exists."""
    p = tmp_path / "img.jpg"
    p.write_bytes(b"x")
    return str(p)


class TestUploadImages:
    """_upload_images — the image upload step (regression: args= vs arg=)."""

    async def test_uses_arg_not_args_for_wait_for_function(
        self, publisher: XHSPublisher, tmp_path: Path
    ):
        """wait_for_function must be called with `arg=` (Playwright Python API).

        Regression guard: previously passed `args=`, which Playwright silently
        ignored, leaving arguments[0] undefined → `.length >= undefined` always
        false → 60s timeout on every publish with images.
        """
        img = _make_image(tmp_path)
        page = AsyncMock()
        upload_input = AsyncMock()
        page.query_selector = AsyncMock(return_value=upload_input)

        await publisher._upload_images(page, [img])

        upload_input.set_input_files.assert_awaited_once_with([img])
        page.wait_for_function.assert_awaited_once()
        # The fix: `arg` keyword present, `args` absent
        kwargs = page.wait_for_function.await_args.kwargs
        assert "arg" in kwargs, "must use arg= (Playwright Python API)"
        assert "args" not in kwargs, "args= is silently ignored — the bug"
        assert kwargs["arg"] == 1
        assert kwargs["timeout"] == 60000
        # Regression: Playwright injects `arg` as the function's first parameter,
        # NOT as `arguments` — arrow functions don't bind `arguments`, so the old
        # `arguments[0]` body threw ReferenceError on every poll → 60s timeout.
        js = page.wait_for_function.await_args.args[0]
        assert "arguments[0]" not in js, "use a named param, not arguments[0]"
        assert "(n)" in js and "n" in js, "JS must declare a param to receive arg"

    async def test_raises_when_no_valid_images(self, publisher: XHSPublisher):
        """No valid image files → ValueError, not a silent no-op."""
        page = AsyncMock()
        with pytest.raises(ValueError, match="没有有效的图片文件"):
            await publisher._upload_images(page, ["/nonexistent/path.jpg"])


class TestPublishNote:
    """publish_note — top-level orchestration."""

    async def test_returns_auth_failed_when_login_fails(self, publisher: XHSPublisher):
        """Expired cookie → auth_failed status, no publish attempt."""
        publisher._check_login = AsyncMock(return_value=False)  # type: ignore[method-assign]
        publisher._ensure_page = AsyncMock(return_value=MagicMock())  # type: ignore[method-assign]

        result = await publisher.publish_note(
            title="t", body="b", image_paths=["/x.jpg"], hashtags=["#h"]
        )
        assert result["status"] == "auth_failed"
        assert "error" in result

    async def test_success_path_returns_published(self, publisher: XHSPublisher):
        """Full mocked happy path → status=published with post_url."""
        page = AsyncMock()
        page.on = MagicMock()  # sync handler registration — real page.on is sync, not a coroutine
        publisher._ensure_page = AsyncMock(return_value=page)  # type: ignore[method-assign]
        publisher._check_login = AsyncMock(return_value=True)  # type: ignore[method-assign]
        publisher._wait_for_publish_ready = AsyncMock(return_value=True)  # type: ignore[method-assign]
        publisher._upload_images = AsyncMock()  # type: ignore[method-assign]
        publisher._fill_content = AsyncMock()  # type: ignore[method-assign]
        publisher._add_hashtags = AsyncMock()  # type: ignore[method-assign]
        publisher._click_publish = AsyncMock()  # type: ignore[method-assign]
        success = {
            "post_id": "abc",
            "post_url": "https://x/note/abc",
            "status": "published",
            "published_at": "now",
        }
        publisher._wait_for_success = AsyncMock(return_value=success)  # type: ignore[method-assign]

        result = await publisher.publish_note(
            title="title", body="body", image_paths=["/x.jpg"], hashtags=["#a", "#b"]
        )
        assert result["status"] == "published"
        assert result["post_id"] == "abc"
        publisher._add_hashtags.assert_awaited_once()
        page.goto.assert_not_called()


class TestClickPublish:
    """_click_publish — real submit button selection."""

    async def test_prefers_direct_publish_button(self, publisher: XHSPublisher):
        page = MagicMock()
        direct_first = MagicMock()
        direct_first.click = AsyncMock()
        direct_locator = MagicMock()
        direct_locator.count = AsyncMock(return_value=1)
        direct_locator.first = direct_first

        empty_locator = MagicMock()
        empty_locator.count = AsyncMock(return_value=0)

        def locator(selector: str):
            if selector == ".publish-page-publish-btn button.bg-red":
                return direct_locator
            return empty_locator

        page.locator = MagicMock(side_effect=locator)

        await publisher._click_publish(page)

        direct_first.click.assert_awaited_once_with(timeout=15000)
        page.locator.assert_any_call(".publish-page-publish-btn button.bg-red")
        selectors = [call.args[0] for call in page.locator.call_args_list]
        assert "xhs-publish-btn" not in selectors


class TestWaitForSuccess:
    """_wait_for_success — platform result detection after clicking publish."""

    async def test_unbound_phone_toast_returns_failed(self, publisher: XHSPublisher):
        page = AsyncMock()
        page.url = publisher.CREATOR_URL
        publisher._collect_visible_alerts = AsyncMock(return_value=["未绑定手机号"])  # type: ignore[method-assign]

        result = await publisher._wait_for_success(page)

        assert result["status"] == "failed"
        assert result["post_id"] == ""
        assert result["post_url"] == ""
        assert result["error"] == "未绑定手机号"
        page.wait_for_selector.assert_not_awaited()


class TestPublishPageNavigation:
    """Publish page navigation should not block on never-idle creator traffic."""

    async def test_check_login_uses_domcontentloaded(self, publisher: XHSPublisher):
        page = AsyncMock()
        page.url = publisher.CREATOR_URL
        publisher._ensure_page = AsyncMock(return_value=page)  # type: ignore[method-assign]
        publisher._wait_for_publish_ready = AsyncMock(return_value=True)  # type: ignore[method-assign]

        result = await publisher._check_login()

        assert result is True
        page.goto.assert_awaited_once_with(
            publisher.CREATOR_URL,
            wait_until="domcontentloaded",
            timeout=45000,
        )


class TestPublishRetrySafety:
    """publish_note failure must reset the dirty page so a retry starts clean."""

    async def test_failure_resets_page_for_retry(self, publisher: XHSPublisher):
        """On exception, _page is closed and nulled — retry gets a fresh page.

        XHSClient.publish_post retries up to 3x. Without this reset, _ensure_page
        returns the same stuck page every attempt, so retries fail the same way.
        """
        page = AsyncMock()
        page.on = MagicMock()  # sync handler registration — real page.on is sync
        publisher._ensure_page = AsyncMock(return_value=page)  # type: ignore[method-assign]
        publisher._check_login = AsyncMock(side_effect=RuntimeError("page exploded"))  # type: ignore[method-assign]
        publisher._page = page  # simulate an already-attached page

        result = await publisher.publish_note(title="t", body="b", image_paths=["/x.jpg"])

        assert result["status"] == "error"
        page.close.assert_awaited_once()
        assert publisher._page is None, "dirty page must be reset for retry"


class TestNoteIdExtraction:
    """_wait_for_success extracts post_id from the post-publish landing URL.

    Previously only matched /note/{id}, so a success landing on /explore/{id}
    or /discovery/item/{id} left post_id empty — which then skipped recording
    the publish to ContentHistory (PublisherAgent gates history on post_id).
    """

    @pytest.mark.parametrize(
        "url,expected",
        [
            (
                "https://www.xiaohongshu.com/note/65a3b2c1d4e5f6a7b8c9d0e1",
                "65a3b2c1d4e5f6a7b8c9d0e1",
            ),
            (
                "https://www.xiaohongshu.com/explore/65a3b2c1d4e5f6a7b8c9d0e1",
                "65a3b2c1d4e5f6a7b8c9d0e1",
            ),
            (
                "https://www.xiaohongshu.com/discovery/item/65a3b2c1d4e5f6a7b8c9d0e1",
                "65a3b2c1d4e5f6a7b8c9d0e1",
            ),
            (
                "https://www.xiaohongshu.com/explore/65a3b2c1d4e5f6a7b8c9d0e1?x=1",
                "65a3b2c1d4e5f6a7b8c9d0e1",
            ),
            ("https://creator.xiaohongshu.com/publish/success", ""),  # no note id
        ],
    )
    def test_extract_note_id(self, url: str, expected: str):
        match = _NOTE_ID_RE.search(url)
        post_id = match.group(1) if match else ""
        assert post_id == expected


class TestCDPMode:
    """CDP 连接真实 Chrome 模式——绕过 XHS 反爬的关键路径。"""

    def test_cdp_endpoint_stored(self):
        """cdp_endpoint 传入后存为实例属性，决定是否允许连接持久 Chrome。"""
        pub_cdp = XHSPublisher(cookie="", cdp_endpoint="http://127.0.0.1:9222")
        pub_launch = XHSPublisher(cookie="", cdp_endpoint="")
        assert pub_cdp.cdp_endpoint == "http://127.0.0.1:9222"
        assert pub_launch.cdp_endpoint == ""

    @pytest.mark.asyncio
    async def test_missing_cdp_fails_closed_before_starting_browser(self):
        """No account CDP must not fall back to a new browser or Cookie state."""
        publisher = XHSPublisher(cookie="a=1")

        with pytest.raises(PublisherConfigurationError, match="cdp_endpoint"):
            await publisher._ensure_browser()

    @pytest.mark.asyncio
    async def test_cdp_mode_uses_existing_context_no_stealth_no_cookie(self, monkeypatch):
        """CDP 模式 _ensure_page 用 browser.contexts[0]，不 new_context/不注 cookie。"""
        existing_context = MagicMock()
        existing_context.new_page = AsyncMock(return_value=MagicMock(name="page"))
        existing_context.add_cookies = AsyncMock()  # 不该被调
        existing_context.add_init_script = MagicMock()  # 不该被调
        browser = MagicMock()
        browser.contexts = [existing_context]
        browser.new_context = AsyncMock()  # 不该被调

        publisher = XHSPublisher(cookie="a=1", cdp_endpoint="http://127.0.0.1:9222")
        publisher._browser = browser  # 跳过 _ensure_browser

        page = await publisher._ensure_page()

        # CDP 模式：用已有 context（真实 Chrome profile 自带登录态）
        browser.new_context.assert_not_called()
        existing_context.new_page.assert_awaited_once()
        # 不注 cookie（profile 自带）、不注 stealth（真实 Chrome 里注反检测反而标红）
        existing_context.add_cookies.assert_not_called()
        existing_context.add_init_script.assert_not_called()
        assert page is not None
