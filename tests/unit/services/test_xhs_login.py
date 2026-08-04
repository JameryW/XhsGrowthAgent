"""Tests for XhsLoginSession — QR-code login service (headed Chrome only).

Uses AsyncMock/MagicMock for the Playwright chain so tests run without the
[browser] extra. The response-interception logic (the heart of path B') is
exercised by capturing the ``page.on("response", handler)`` callback and
feeding it synthetic XHR responses.
"""

from __future__ import annotations

import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# conftest.py mocks sys.modules["playwright.async_api"] globally, so the lazy
# `from playwright.async_api import async_playwright` inside start() returns a
# MagicMock. We build a controllable mock chain on top of that per-test.


def _build_mock_response(url: str, method: str, body: dict) -> MagicMock:
    """Build a fake Playwright Response object for the interception handler."""
    resp = MagicMock()
    resp.url = url
    resp.request.method = method
    resp.json = AsyncMock(return_value=body)
    return resp


def _wire_playwright_mock(
    *,
    pages: list[MagicMock] | None = None,
    goto_side_effect=None,
    cookies: list[dict] | None = None,
    page_text: str = "",
    page_url: str = "https://www.xiaohongshu.com/explore",
    page_title: str = "",
) -> tuple[MagicMock, MagicMock, list]:
    """Wire up a controllable playwright mock chain.

    Returns (mock_playwright_module, mock_page, on_response_calls) where
    ``on_response_calls`` collects the (handler,) tuples passed to page.on().
    The test can then invoke the handler with synthetic responses.
    """
    mock_page = MagicMock()
    mock_page.url = page_url
    mock_page.title = AsyncMock(return_value=page_title)
    mock_page.goto = AsyncMock(side_effect=goto_side_effect) if goto_side_effect else AsyncMock()
    mock_page.evaluate = AsyncMock(return_value=page_text)
    mock_page.bring_to_front = AsyncMock()
    mock_page.close = AsyncMock()
    mock_page.frames = [mock_page]
    mock_page.main_frame = mock_page
    on_response_calls: list = []
    mock_page.on = lambda event, handler: on_response_calls.append((event, handler))

    mock_context = MagicMock()
    mock_context.pages = pages if pages is not None else []
    mock_context.new_page = AsyncMock(return_value=mock_page)
    mock_context.close = AsyncMock()
    mock_context.add_init_script = AsyncMock()
    mock_context.cookies = AsyncMock(return_value=cookies or [])

    mock_chromium = MagicMock()
    mock_chromium.launch_persistent_context = AsyncMock(return_value=mock_context)
    mock_browser = MagicMock()
    mock_browser.contexts = [mock_context]
    mock_chromium.connect_over_cdp = AsyncMock(return_value=mock_browser)

    mock_pw = MagicMock()
    mock_pw.chromium = mock_chromium
    mock_pw.stop = AsyncMock()

    mock_async_pw = MagicMock()
    mock_async_pw.start = AsyncMock(return_value=mock_pw)

    # Patch the lazy import target so `from playwright.async_api import async_playwright`
    # returns our mock. conftest already mocks the module; we override async_playwright.
    # MagicMock chains: async_playwright() → mock_async_pw; .start() → mock_pw;
    # mock_pw.chromium → mock_chromium (set explicitly so launch_persistent_context
    # assertions land on the real mock, not an auto-attribute).
    mock_module = MagicMock()
    mock_module.async_playwright = MagicMock(return_value=mock_async_pw)
    return mock_module, mock_page, on_response_calls


@pytest.fixture(autouse=True)
def _bypass_cdp_hold(monkeypatch: pytest.MonkeyPatch):
    """start() acquires the shared CDP lock via hold_cdp_session (#399).

    The real lock checks browser_action_cooldown + PG advisory lock; in a full
    pytest run earlier tests arm the cooldown, so login tests fail with
    CdpSessionBusyError before page.on('response') is registered. Neutralize
    hold_cdp_session with a no-op async context manager so start() proceeds.
    """
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _noop_hold(**_):
        yield

    monkeypatch.setattr(
        "backend.services.cdp_session_lock.hold_cdp_session",
        _noop_hold,
    )
    # Shrink the real-browser settle/poll constants — under the playwright mock
    # these only add wall-clock (no rendering to settle, no real polls to space).
    # start() AND the qrcode/status confirmed-handler both hit _warm_creator_session
    # (1.5s) and the QR/explore poll loops, so patching here covers every path.
    for _c in (
        "_ALREADY_LOGIN_CHECK_S",
        "_SECURITY_REDIRECT_SETTLE_S",
        "_LOGIN_MODAL_CLICK_SETTLE_S",
        "_LOGIN_MODAL_FINAL_SETTLE_S",
        "_CREATOR_WARMUP_SETTLE_S",
        "_EXISTING_LOGIN_POLL_S",
        "_QR_READY_POLL_S",
        "_EXPLORE_POLL_S",
        "_QR_CONFIRM_TIMEOUT_S",
    ):
        monkeypatch.setattr("backend.services.xhs_login." + _c, 0.01)
    # QR create wait: success-path tests fire the create handler at 0.02s, so
    # the deadline needs headroom past that. 0.05s gives one poll tick (0.01s)
    # after the 0.02s fire for detection. Failure-path tests just time out here
    # (the www_only recovery path waits this TWICE, so halving it halves that cost).
    monkeypatch.setattr("backend.services.xhs_login._QR_CREATE_WAIT_S", 0.05)


class TestStart:
    """start() — launch Chrome, intercept qrcode/create, return qr_id+url."""

    async def test_start_returns_qr_id_and_url(self, tmp_path):
        """Happy path: start() returns {qr_id, url, account_id} from intercepted response."""
        from backend.services.xhs_login import XhsLoginSession

        mock_module, mock_page, on_calls = _wire_playwright_mock()
        session = XhsLoginSession("acc-1", str(tmp_path / "profile"))

        with patch.dict(sys.modules, {"playwright.async_api": mock_module}):
            # Drive start() and the response handler concurrently: start() waits
            # in _wait_for_qr_create polling loop; we fire the handler mid-flight.
            async def _fire_qr_create():
                # Give start() a moment to register the listener + call goto.
                # 0.02s is enough under the mock (page.on registers on first await);
                # _QR_CREATE_WAIT_S=0.05 (autouse) leaves a poll tick to detect it.
                await asyncio.sleep(0.02)
                assert on_calls, "page.on('response', ...) was not registered"
                handler = on_calls[0][1]
                resp = _build_mock_response(
                    "https://edith.xiaohongshu.com/api/sns/web/v1/login/qrcode/create",
                    "POST",
                    {
                        "success": True,
                        "code": 0,
                        "data": {"qr_id": "qr123", "code": "c1", "url": "https://x/qr?qrId=qr123"},
                    },
                )
                await handler(resp)

            await asyncio.gather(session.start(), _fire_qr_create())

        assert session.qr_id == "qr123"
        assert session.qr_url == "https://x/qr?qrId=qr123"
        await session.stop()

    async def test_start_raises_login_error_when_no_qr_create_response(self, tmp_path):
        """No network response or DOM QR within timeout → LoginError."""
        from backend.services.xhs_login import XhsLoginSession

        mock_module, _, _ = _wire_playwright_mock()
        # QR create wait timeout is shrunk by the autouse _bypass_cdp_hold fixture.
        session = XhsLoginSession("acc-1", str(tmp_path / "profile"))

        with (
            patch.dict(sys.modules, {"playwright.async_api": mock_module}),
            patch("backend.services.xhs_login._ALREADY_LOGIN_CHECK_S", 0.01),
            patch("backend.services.xhs_login._SECURITY_REDIRECT_SETTLE_S", 0.01),
            patch("backend.services.xhs_login._LOGIN_MODAL_CLICK_SETTLE_S", 0.01),
            patch("backend.services.xhs_login._LOGIN_MODAL_FINAL_SETTLE_S", 0.01),
            pytest.raises(Exception, match="未找到登录二维码"),
        ):
            await session.start()
        await session.stop()

    async def test_start_returns_rendered_dom_qr_when_create_response_missing(self, tmp_path):
        """XHS may render img.qrcode-img without exposing qrcode/create to our listener."""
        from backend.services.xhs_login import XhsLoginSession

        data_url = "data:image/png;base64,qr-image"
        mock_module, mock_page, _ = _wire_playwright_mock()
        mock_page.evaluate = AsyncMock(return_value=data_url)
        session = XhsLoginSession("acc-1", str(tmp_path / "profile"))

        with (
            patch.dict(sys.modules, {"playwright.async_api": mock_module}),
            patch("backend.services.xhs_login._ALREADY_LOGIN_CHECK_S", 0.01),
        ):
            result = await session.start()

        assert result["qr_id"].startswith("dom-")
        assert result["url"] == data_url
        assert session.qr_url == data_url
        await session.stop()

    async def test_start_raises_immediately_on_xhs_security_restriction(self, tmp_path):
        """XHS safety block page → actionable LoginError, no QR wait loop."""
        from backend.services.xhs_login import LoginError, XhsLoginSession

        mock_module, mock_page, _ = _wire_playwright_mock(
            page_url=(
                "https://www.xiaohongshu.com/website-login/error?"
                "redirectPath=https://www.xiaohongshu.com/explore"
                "&error_code=300012"
                "&error_msg=IP%20at%20risk.%20Switch%20to%20a%20secure%20network%20and%20retry."
            ),
            page_title="安全限制",
        )
        session = XhsLoginSession("acc-1", str(tmp_path / "profile"))

        with (
            patch.dict(sys.modules, {"playwright.async_api": mock_module}),
            pytest.raises(LoginError, match="当前网络/IP"),
        ):
            await session.start()

        mock_page.close.assert_awaited()
        assert session._context is None

    async def test_start_returns_confirmed_when_profile_already_logged_in(self, tmp_path):
        """Existing creator access token → no QR is needed and no 30s wait."""
        from backend.services.xhs_login import XhsLoginSession

        mock_module, mock_page, on_calls = _wire_playwright_mock(
            cookies=[{"name": "access-token-creator.xiaohongshu.com", "value": "tok"}],
            page_text="首页 发布 通知 消息 我",
        )
        session = XhsLoginSession("acc-1", str(tmp_path / "profile"))

        with (
            patch.object(XhsLoginSession, "_warm_creator_session", new=AsyncMock()) as warm,
            patch.dict(sys.modules, {"playwright.async_api": mock_module}),
        ):
            result = await session.start()

        assert result == {
            "status": "confirmed",
            "qr_id": "",
            "url": "",
            "account_id": "acc-1",
        }
        assert on_calls, "page.on('response', ...) was not registered"
        warm.assert_awaited_once()
        mock_page.close.assert_awaited()
        assert session._confirmed is True
        assert session._context is None

    async def test_strict_mode_refuses_persistent_fallback(self, tmp_path):
        """Service strict mode must not create a second persistent browser."""
        from backend.services.xhs_login import LoginError, XhsLoginSession

        mock_module, _, _ = _wire_playwright_mock()
        session = XhsLoginSession(
            "acc-strict",
            str(tmp_path / "profile"),
            allow_persistent_fallback=False,
        )

        with (
            patch.dict(sys.modules, {"playwright.async_api": mock_module}),
            pytest.raises(LoginError, match="第二个浏览器"),
        ):
            await session.start()

        launch = mock_module.async_playwright.return_value.start.return_value.chromium
        launch.launch_persistent_context.assert_not_awaited()
        await session.stop()

    async def test_cdp_without_browser_context_fails_closed(self, tmp_path):
        """CDP login must not create an isolated context when Chrome has none."""
        from backend.services.xhs_login import LoginError, XhsLoginSession

        mock_module, _, _ = _wire_playwright_mock()
        chromium = mock_module.async_playwright.return_value.start.return_value.chromium
        browser = chromium.connect_over_cdp.return_value
        browser.contexts = []
        browser.new_context = AsyncMock()
        session = XhsLoginSession(
            "acc-cdp",
            str(tmp_path / "profile"),
            cdp_endpoint="http://127.0.0.1:9222",
        )

        with (
            patch.dict(sys.modules, {"playwright.async_api": mock_module}),
            pytest.raises(LoginError, match="没有可用 browser context.*启动账号 Chrome"),
        ):
            await session.start()

        browser.new_context.assert_not_called()
        assert session._browser is None
        assert session._context is None
        assert session._page is None
        assert session._playwright is None

    async def test_start_www_only_feed_does_not_skip_qr(self, tmp_path):
        """www cookies + feed chrome must not short-circuit as 'already logged in'.

        Regression: partial sessions previously skipped QR (no creator token) then
        raw CDP timed out with '5s 内未找到登录二维码'.
        """
        from backend.services.xhs_login import XhsLoginSession

        mock_module, mock_page, on_calls = _wire_playwright_mock(
            cookies=[
                {"name": "web_session", "value": "sess"},
                {"name": "id_token", "value": "tok"},
            ],
            page_text="首页 发布 通知 消息 我",
        )
        # clear_cookies used when forcing QR after detecting www_only.
        chromium = mock_module.async_playwright.return_value.start.return_value.chromium
        mock_context = chromium.launch_persistent_context.return_value
        # When connect_over_cdp is not used (no cdp_endpoint), launch_persistent is used.
        # Default session has no cdp → launch_persistent_context.
        mock_context.clear_cookies = AsyncMock()
        session = XhsLoginSession("acc-1", str(tmp_path / "profile"))

        with (
            patch.dict(sys.modules, {"playwright.async_api": mock_module}),
            patch("backend.services.xhs_login._ALREADY_LOGIN_CHECK_S", 0.01),
            patch("backend.services.xhs_login._SECURITY_REDIRECT_SETTLE_S", 0.01),
            patch("backend.services.xhs_login._LOGIN_MODAL_CLICK_SETTLE_S", 0.01),
            patch("backend.services.xhs_login._LOGIN_MODAL_FINAL_SETTLE_S", 0.01),
            pytest.raises(Exception, match="未找到登录二维码"),
        ):
            await session.start()

        # Must have attempted to clear partial www cookies (not skip-confirmed).
        assert mock_context.clear_cookies.await_count >= 1
        assert session._confirmed is False

    async def test_start_failure_closes_context_no_leak(self, tmp_path):
        """start() launch/wait failure → context closed, no zombie Chrome.

        Regression guard: route returns 503 on LoginError but never calls
        stop(); without self-cleanup the Chrome leaks.
        """
        from backend.services.xhs_login import XhsLoginSession

        mock_module, mock_page, _ = _wire_playwright_mock()
        session = XhsLoginSession("acc-1", str(tmp_path / "profile"))

        with (
            patch.dict(sys.modules, {"playwright.async_api": mock_module}),
            patch("backend.services.xhs_login._ALREADY_LOGIN_CHECK_S", 0.01),
            patch("backend.services.xhs_login._SECURITY_REDIRECT_SETTLE_S", 0.01),
            patch("backend.services.xhs_login._LOGIN_MODAL_CLICK_SETTLE_S", 0.01),
            patch("backend.services.xhs_login._LOGIN_MODAL_FINAL_SETTLE_S", 0.01),
            pytest.raises(Exception, match="未找到登录二维码"),
        ):
            await session.start()
        # start() failure path called stop() internally → context/page released.
        mock_page.close.assert_awaited()
        assert session._context is None
        assert session._playwright is None

    async def test_start_raises_login_error_when_playwright_missing(self, tmp_path):
        """playwright not installed → LoginError with install hint."""
        from backend.services.xhs_login import LoginError, XhsLoginSession

        session = XhsLoginSession("acc-1", str(tmp_path / "profile"))

        # Force the lazy import to raise ImportError.
        with (
            patch.dict(sys.modules, {"playwright.async_api": None}),
            pytest.raises(LoginError, match="playwright 未安装"),
        ):
            await session.start()

    async def test_start_creates_profile_dir(self, tmp_path):
        """start() mkdir -p the profile_path before launching Chrome."""
        from backend.services.xhs_login import XhsLoginSession

        mock_module, _, on_calls = _wire_playwright_mock()
        profile_path = tmp_path / "nested" / "profile"
        session = XhsLoginSession("acc-1", str(profile_path))

        with patch.dict(sys.modules, {"playwright.async_api": mock_module}):
            await asyncio.gather(
                session.start(),
                _fire_create_after_delay(on_calls, 0.05),
            )
        assert profile_path.exists()
        await session.stop()

    async def test_start_reuses_existing_session(self, tmp_path):
        """Calling start() twice on the same session returns existing qr_id+url."""
        from backend.services.xhs_login import XhsLoginSession

        mock_module, _, on_calls = _wire_playwright_mock()
        session = XhsLoginSession("acc-1", str(tmp_path / "profile"))

        with patch.dict(sys.modules, {"playwright.async_api": mock_module}):
            await asyncio.gather(
                session.start(),
                _fire_create_after_delay(on_calls, 0.05),
            )
            # Second start() should reuse, not re-launch.
            result = await session.start()
        assert result["qr_id"] == "qr123"
        # launch_persistent_context called only once (reuse path).
        # Chain: async_playwright() → .start() → .chromium.launch_persistent_context
        pw_handle = mock_module.async_playwright.return_value.start.return_value
        launch_mock = pw_handle.chromium.launch_persistent_context
        assert launch_mock.await_count == 1
        await session.stop()

    async def test_start_reuses_existing_raw_cdp_session(self, tmp_path):
        """Raw-CDP sessions are active even though they do not populate _context."""
        from backend.services.xhs_login import XhsLoginSession

        session = XhsLoginSession(
            "acc-1",
            str(tmp_path / "profile"),
            cdp_endpoint="http://host.containers.internal:9224",
        )
        raw_ws = MagicMock()
        raw_ws.close = AsyncMock()
        session._raw_ws = raw_ws
        session._raw_target_id = "target-1"
        session._raw_session_id = "session-1"
        session._qr_id = "dom-1"
        session._qr_url = "data:image/png;base64,abc"

        result = await session.start()

        assert result == {
            "qr_id": "dom-1",
            "url": "data:image/png;base64,abc",
            "account_id": "acc-1",
        }
        raw_ws.close.assert_not_awaited()
        session._raw_ws = None

    async def test_raw_cdp_create_target_ignores_stale_session_id(self, tmp_path):
        """Target.createTarget is browser-scoped and must not carry an old sessionId."""
        from backend.services.xhs_login import XhsLoginSession

        session = XhsLoginSession(
            "acc-1",
            str(tmp_path / "profile"),
            cdp_endpoint="http://host.containers.internal:9224",
        )
        session._raw_session_id = "stale-session"
        calls = []

        async def _fake_raw_send(method, params=None, *, session_id=""):
            calls.append((method, session_id))
            if method == "Target.createTarget":
                return {"targetId": "target-1"}
            if method == "Target.attachToTarget":
                return {"sessionId": "session-1"}
            return {}

        session._raw_connect = AsyncMock()
        session._raw_send = _fake_raw_send
        session._raw_wait_for_qr = AsyncMock(
            return_value={"qr_id": "dom-1", "url": "data:image/png;base64,abc"}
        )

        result = await session._start_raw_cdp()

        assert result["qr_id"] == "dom-1"
        assert calls[:2] == [
            ("Target.createTarget", None),
            ("Target.attachToTarget", None),
        ]
        assert session._raw_session_id == "session-1"

    async def test_raw_cdp_clears_partial_cookies_before_explore(self, tmp_path):
        """www_only: warm creator first; if no token, clear then explore for QR."""
        from backend.services.xhs_login import XhsLoginSession

        session = XhsLoginSession(
            "acc-1",
            str(tmp_path / "profile"),
            cdp_endpoint="http://host.containers.internal:9224",
        )
        methods: list[str] = []
        navigate_urls: list[str] = []

        async def _fake_raw_send(method, params=None, *, session_id=""):
            methods.append(method)
            if method == "Target.createTarget":
                return {"targetId": "t1"}
            if method == "Target.attachToTarget":
                return {"sessionId": "s1"}
            if method == "Page.navigate":
                navigate_urls.append(str((params or {}).get("url") or ""))
                return {}
            if method == "Storage.getCookies":
                return {
                    "cookies": [
                        {
                            "name": "web_session",
                            "value": "s",
                            "domain": ".xiaohongshu.com",
                            "path": "/",
                        },
                        {
                            "name": "id_token",
                            "value": "t",
                            "domain": ".xiaohongshu.com",
                            "path": "/",
                        },
                    ]
                }
            if method == "Network.getCookies":
                # No creator token after warm-up
                return {
                    "cookies": [
                        {"name": "web_session", "value": "s"},
                        {"name": "id_token", "value": "t"},
                    ]
                }
            return {}

        session._raw_connect = AsyncMock()
        session._raw_send = _fake_raw_send
        session._raw_wait_for_qr = AsyncMock(
            return_value={"qr_id": "dom-1", "url": "data:image/png;base64,abc"}
        )

        result = await session._start_raw_cdp()
        assert result["qr_id"] == "dom-1"
        assert "Network.deleteCookies" in methods
        # Creator home first, then explore after clear
        assert any("creator.xiaohongshu.com" in u for u in navigate_urls)
        assert any("explore" in u for u in navigate_urls)
        assert "Network.deleteCookies" in methods


class TestGetStatus:
    """get_status() — map codeStatus to waiting/scanned/confirmed/expired."""

    async def _start_session(self, session, on_calls):
        """Helper: start a session and fire an initial qrcode/create."""
        # Settle/poll constants are shrunk by the autouse _bypass_cdp_hold fixture.
        # Fire at 0.02s: start() registers page.on('response') on its first awaits
        # (mock playwright yields fast); _QR_CREATE_WAIT_S=0.05 (autouse) leaves
        # headroom for one _QR_READY_POLL_S tick to detect the fired _qr_id.
        await asyncio.gather(
            session.start(),
            _fire_create_after_delay(on_calls, 0.02),
        )

    async def test_status_waiting_initially(self, tmp_path):
        """Freshly started session → status=waiting (codeStatus=0)."""
        from backend.services.xhs_login import XhsLoginSession

        mock_module, _, on_calls = _wire_playwright_mock()
        session = XhsLoginSession("acc-1", str(tmp_path / "profile"))
        with patch.dict(sys.modules, {"playwright.async_api": mock_module}):
            await self._start_session(session, on_calls)
            result = await session.get_status()
        assert result["status"] == "waiting"
        assert result["qr_id"] == "qr123"
        await session.stop()

    async def test_status_confirmed_when_creator_cookie_is_present(self, tmp_path):
        """Creator access token wins when qrcode/status still says waiting."""
        from backend.services.xhs_login import XhsLoginSession

        mock_module, _, on_calls = _wire_playwright_mock(
            cookies=[
                {"name": "access-token-creator.xiaohongshu.com", "value": "tok"},
            ],
            page_text="首页 发布 通知 消息 我",
        )
        session = XhsLoginSession("acc-1", str(tmp_path / "profile"))
        with (
            patch.object(XhsLoginSession, "_warm_creator_session", new=AsyncMock()),
            patch.dict(sys.modules, {"playwright.async_api": mock_module}),
        ):
            await self._start_session(session, on_calls)
            result = await session.get_status()

        assert result["status"] == "confirmed"
        assert result["url"] == ""
        await session.stop()

    async def test_status_scanned_after_code_status_1(self, tmp_path):
        """codeStatus=1 without a fillable control reports verification=false."""
        from backend.services.xhs_login import XhsLoginSession

        mock_module, mock_page, on_calls = _wire_playwright_mock()
        session = XhsLoginSession("acc-1", str(tmp_path / "profile"))
        with patch.dict(sys.modules, {"playwright.async_api": mock_module}):
            await self._start_session(session, on_calls)
            handler = on_calls[0][1]
            status_resp = _build_mock_response(
                "https://edith.xiaohongshu.com/api/sns/web/v1/login/qrcode/status",
                "GET",
                {"data": {"codeStatus": 1}},
            )
            await handler(status_resp)
            mock_page.evaluate = AsyncMock(
                return_value={"scanned": True, "verification_required": False}
            )
            result = await session.get_status()
        assert result["status"] == "scanned"
        assert result["verification_required"] is False
        await session.stop()

    async def test_status_scanned_reports_verification_from_visible_control(self, tmp_path):
        """Normal Playwright-CDP status uses the shared page-state probe."""
        from backend.services.xhs_login import _LOGIN_PAGE_STATE_SCRIPT, XhsLoginSession

        mock_module, mock_page, on_calls = _wire_playwright_mock()
        session = XhsLoginSession("acc-1", str(tmp_path / "profile"))
        with patch.dict(sys.modules, {"playwright.async_api": mock_module}):
            await self._start_session(session, on_calls)
            handler = on_calls[0][1]
            await handler(
                _build_mock_response(
                    "https://edith.xiaohongshu.com/api/sns/web/v1/login/qrcode/status",
                    "GET",
                    {"data": {"codeStatus": 1}},
                )
            )
            mock_page.evaluate = AsyncMock(
                side_effect=[
                    {"status": 200, "body": {"data": {"code_status": 1}}},
                    {"scanned": True, "verification_required": True},
                ]
            )
            result = await session.get_status()

        assert result["status"] == "scanned"
        assert result["verification_required"] is True
        assert mock_page.evaluate.await_args_list[1].args == (_LOGIN_PAGE_STATE_SCRIPT,)
        await session.stop()

    async def test_status_confirmed_after_code_status_2(self, tmp_path):
        """codeStatus=2 (confirmed) → status=confirmed, url cleared."""
        from backend.services.xhs_login import XhsLoginSession

        mock_module, _, on_calls = _wire_playwright_mock()
        session = XhsLoginSession("acc-1", str(tmp_path / "profile"))
        with patch.dict(sys.modules, {"playwright.async_api": mock_module}):
            await self._start_session(session, on_calls)
            handler = on_calls[0][1]
            status_resp = _build_mock_response(
                "https://edith.xiaohongshu.com/api/sns/web/v1/login/qrcode/status",
                "GET",
                {"data": {"codeStatus": 2, "login_info": {"session": "s1", "user_id": "u1"}}},
            )
            await handler(status_resp)
            result = await session.get_status()
        assert result["status"] == "confirmed"
        assert result["url"] == ""  # url cleared on confirm
        assert "verification_required" not in result
        await session.stop()

    async def test_status_confirmed_is_idempotent(self, tmp_path):
        """get_status() after confirm returns confirmed without re-firing handler."""
        from backend.services.xhs_login import XhsLoginSession

        mock_module, _, on_calls = _wire_playwright_mock()
        session = XhsLoginSession("acc-1", str(tmp_path / "profile"))
        with patch.dict(sys.modules, {"playwright.async_api": mock_module}):
            await self._start_session(session, on_calls)
            handler = on_calls[0][1]
            await handler(
                _build_mock_response(
                    "https://x/api/sns/web/v1/login/qrcode/status",
                    "GET",
                    {"data": {"codeStatus": 2}},
                )
            )
            r1 = await session.get_status()
            r2 = await session.get_status()
        assert r1["status"] == "confirmed"
        assert r2["status"] == "confirmed"
        await session.stop()

    async def test_confirmed_clears_url_on_every_poll(self, tmp_path):
        """confirmed → url=='' on BOTH first and subsequent polls (cross-layer guard).

        Regression: early-return _confirmed path returned stale self._qr_url,
        so frontend's second status poll re-rendered the QR. Both polls must
        return url=="" so frontend stops showing the QR after confirm.
        """
        from backend.services.xhs_login import XhsLoginSession

        mock_module, _, on_calls = _wire_playwright_mock()
        session = XhsLoginSession("acc-1", str(tmp_path / "profile"))
        with patch.dict(sys.modules, {"playwright.async_api": mock_module}):
            await self._start_session(session, on_calls)
            handler = on_calls[0][1]
            await handler(
                _build_mock_response(
                    "https://x/api/sns/web/v1/login/qrcode/status",
                    "GET",
                    {"data": {"codeStatus": 2}},
                )
            )
            r1 = await session.get_status()
            r2 = await session.get_status()
        assert r1["url"] == ""
        assert r2["url"] == ""

    async def test_confirmed_auto_closes_context(self, tmp_path):
        """confirmed → stop() auto-called (resource guard); profile already persisted.

        Without this, every confirmed-but-not-explicitly-stopped session leaks a
        headless-free login Chrome in a long-running server. Frontend's explicit stop()
        call becomes a safe no-op.
        """
        from backend.services.xhs_login import XhsLoginSession

        mock_module, mock_page, on_calls = _wire_playwright_mock()
        session = XhsLoginSession("acc-1", str(tmp_path / "profile"))
        with patch.dict(sys.modules, {"playwright.async_api": mock_module}):
            await self._start_session(session, on_calls)
            handler = on_calls[0][1]
            await handler(
                _build_mock_response(
                    "https://x/api/sns/web/v1/login/qrcode/status",
                    "GET",
                    {"data": {"codeStatus": 2}},
                )
            )
            await session.get_status()  # triggers auto-stop
        # context closed by the confirm path
        mock_page.close.assert_awaited()
        assert session._context is None
        # subsequent stop() is a no-op (idempotent)
        await session.stop()

    async def test_confirmed_keeps_tab_open_in_cdp_mode(self, tmp_path):
        """CDP 模式 confirmed → 保留 host Chrome 里的已登录 tab.

        旧行为是 confirmed 即 close page，操作员看不到登录结果（"页面没跳转"）。
        新行为：page 不 close（tab 留在常驻 host Chrome 停在 creator home），
        仅断连接 + 会话自摘出注册表，同账号下次 start() 可新建会话。
        """
        from backend.services import xhs_login
        from backend.services.xhs_login import XhsLoginSession

        mock_module, mock_page, on_calls = _wire_playwright_mock()
        session = XhsLoginSession(
            "acc-cdp", str(tmp_path / "profile"), cdp_endpoint="http://127.0.0.1:9222"
        )
        xhs_login._sessions["acc-cdp"] = session
        try:
            with (
                patch.object(XhsLoginSession, "_warm_creator_session", new=AsyncMock()),
                patch.dict(sys.modules, {"playwright.async_api": mock_module}),
            ):
                await self._start_session(session, on_calls)
                handler = on_calls[0][1]
                await handler(
                    _build_mock_response(
                        "https://x/api/sns/web/v1/login/qrcode/status",
                        "GET",
                        {"data": {"codeStatus": 2}},
                    )
                )
                result = await session.get_status()

            assert result["status"] == "confirmed"
            assert result["url"] == ""
            mock_page.close.assert_not_awaited()  # tab 保留在 host Chrome
            assert session._page is None  # 引用已丢，playwright 断连不影响 tab
            assert session._context is None  # 连接已断
            assert "acc-cdp" not in xhs_login._sessions  # 会话自摘
            # 后续 stop() 幂等 no-op
            await session.stop()
        finally:
            xhs_login._sessions.pop("acc-cdp", None)

    async def test_status_expired_refreshes_qr(self, tmp_path):
        """Expired QR (timeout) → status=expired with a new url after refresh."""
        from backend.services.xhs_login import XhsLoginSession

        mock_module, mock_page, on_calls = _wire_playwright_mock()
        session = XhsLoginSession("acc-1", str(tmp_path / "profile"))
        with (
            patch.dict(sys.modules, {"playwright.async_api": mock_module}),
        ):
            await self._start_session(session, on_calls)
            # Wait past the (autouse-shrunk tiny) expiry (_QR_CONFIRM_TIMEOUT_S=0.01).
            await asyncio.sleep(0.02)

            # get_status will detect expiry → _refresh_qr → goto + wait for new create.
            # Fire a new create response after get_status's refresh goto lands.
            # 0.02s: refresh's _wait_for_qr_ready deadline is _QR_CREATE_WAIT_S=0.05
            # (autouse), so firing at 0.02s leaves a poll tick to detect the new id.
            async def _fire_refresh_create():
                await asyncio.sleep(0.02)
                handler = on_calls[0][1]
                await handler(
                    _build_mock_response(
                        "https://x/api/sns/web/v1/login/qrcode/create",
                        "POST",
                        {"data": {"qr_id": "qr456", "url": "https://x/qr?qrId=qr456"}},
                    )
                )

            result = await asyncio.gather(session.get_status(), _fire_refresh_create())
        result = result[0]
        assert result["status"] == "expired"
        assert result["qr_id"] == "qr456"
        assert result["url"] == "https://x/qr?qrId=qr456"
        await session.stop()

    async def test_status_471_keeps_current_qr(self, tmp_path):
        """XHS security 471 while confirming → keep QR instead of racing phone confirm."""
        from backend.services.xhs_login import XhsLoginSession

        mock_module, mock_page, on_calls = _wire_playwright_mock()
        session = XhsLoginSession("acc-1", str(tmp_path / "profile"))
        with patch.dict(sys.modules, {"playwright.async_api": mock_module}):
            await self._start_session(session, on_calls)
            session._code_status = 1
            mock_page.evaluate = AsyncMock(return_value={"status": 471, "body": {"data": {}}})

            result = await session.get_status()

        assert result["status"] == "scanned"
        assert result["qr_id"] == "qr123"
        assert result["url"] == "https://x/qr?qrId=qr123"
        assert result["verification_required"] is False
        await session.stop()

    async def test_status_code_status_3_refreshes_qr(self, tmp_path):
        """XHS code_status=3 → refresh QR instead of staying waiting."""
        from backend.services.xhs_login import XhsLoginSession

        mock_module, mock_page, on_calls = _wire_playwright_mock()
        session = XhsLoginSession("acc-1", str(tmp_path / "profile"))
        with patch.dict(sys.modules, {"playwright.async_api": mock_module}):
            await self._start_session(session, on_calls)
            mock_page.evaluate = AsyncMock(
                return_value={"status": 200, "body": {"data": {"code_status": 3}}}
            )

            async def _fire_refresh_create():
                await asyncio.sleep(0.02)
                handler = on_calls[0][1]
                await handler(
                    _build_mock_response(
                        "https://x/api/sns/web/v1/login/qrcode/create",
                        "POST",
                        {
                            "data": {
                                "qr_id": "qr3",
                                "code": "c3",
                                "url": "https://x/qr?qrId=qr3",
                            }
                        },
                    )
                )

            result = await asyncio.gather(session.get_status(), _fire_refresh_create())

        result = result[0]
        assert result["status"] == "expired"
        assert result["qr_id"] == "qr3"
        assert result["url"] == "https://x/qr?qrId=qr3"
        await session.stop()

    async def test_status_when_no_session_returns_waiting(self, tmp_path):
        """get_status() on a never-started session → status=waiting, empty qr."""
        from backend.services.xhs_login import XhsLoginSession

        session = XhsLoginSession("acc-1", str(tmp_path / "profile"))
        result = await session.get_status()
        assert result["status"] == "waiting"
        assert result["qr_id"] == ""

    async def test_raw_status_reports_scanned_when_page_needs_verification(self, tmp_path):
        from backend.services.xhs_login import XhsLoginSession

        session = XhsLoginSession("acc-1", str(tmp_path / "profile"))
        session._raw_ws = MagicMock()
        session._qr_id = "dom-1"
        session._qr_url = "data:image/png;base64,abc"
        session._raw_has_strong_cookie = AsyncMock(return_value=False)
        session._raw_login_page_state = AsyncMock(
            return_value={"scanned": True, "verification_required": True}
        )

        result = await session.get_status()

        assert result["status"] == "scanned"
        assert result["url"] == ""
        assert result["verification_required"] is True
        session._raw_ws = None

    async def test_raw_status_reports_false_without_a_fillable_control(self, tmp_path):
        """Unrelated page copy must not turn raw-CDP status into a prompt."""
        from backend.services.xhs_login import XhsLoginSession

        session = XhsLoginSession("acc-1", str(tmp_path / "profile"))
        session._raw_ws = MagicMock()
        session._qr_id = "dom-1"
        session._qr_url = "data:image/png;base64,abc"
        session._raw_has_strong_cookie = AsyncMock(return_value=False)
        session._raw_login_page_state = AsyncMock(
            return_value={
                "scanned": True,
                "verification_required": False,
                "text": "帮助页面提到验证码，但没有可填写控件",
            }
        )

        result = await session.get_status()

        assert result["status"] == "scanned"
        assert result["verification_required"] is False
        session._raw_ws = None

    async def test_raw_page_state_uses_shared_probe_script(self, tmp_path):
        """Raw CDP evaluates the same page-state script as Playwright-CDP."""
        from backend.services.xhs_login import _LOGIN_PAGE_STATE_SCRIPT, XhsLoginSession

        session = XhsLoginSession("acc-1", str(tmp_path / "profile"))
        session._raw_ws = MagicMock()
        session._raw_eval = AsyncMock(
            return_value={"scanned": True, "verification_required": False}
        )

        result = await session._raw_login_page_state()

        assert result["verification_required"] is False
        session._raw_eval.assert_awaited_once_with(_LOGIN_PAGE_STATE_SCRIPT)
        session._raw_ws = None

    async def test_raw_status_disconnect_raises_login_error_and_cleans_up(self, tmp_path):
        from backend.services.xhs_login import LoginError, XhsLoginSession

        session = XhsLoginSession("acc-1", str(tmp_path / "profile"))
        raw_ws = MagicMock()
        raw_ws.close = AsyncMock()
        session._raw_ws = raw_ws
        session._get_raw_status = AsyncMock(side_effect=RuntimeError("keepalive ping timeout"))

        with pytest.raises(LoginError, match="会话已断开"):
            await session.get_status()

        raw_ws.close.assert_awaited()
        assert session._raw_ws is None

    async def test_refresh_failure_closes_context_no_zombie(self, tmp_path):
        """Expired refresh that fails → context closed, session not stuck.

        Regression guard: _refresh_qr raising left context open with empty
        qr_id → get_status stuck returning "waiting" forever (zombie). Now
        refresh-failure self-stops so next start() relaunches cleanly.
        """
        from backend.services.xhs_login import LoginError, XhsLoginSession

        # First goto (initial start) succeeds; second goto (refresh) raises.
        mock_module, mock_page, on_calls = _wire_playwright_mock(
            goto_side_effect=[None, Exception("navigation failed")]
        )
        session = XhsLoginSession("acc-1", str(tmp_path / "profile"))
        with (
            patch.dict(sys.modules, {"playwright.async_api": mock_module}),
            pytest.raises(LoginError, match="navigation failed"),
        ):
            await self._start_session(session, on_calls)
            await asyncio.sleep(0.02)  # past expiry (_QR_CONFIRM_TIMEOUT_S=0.01)
            await session.get_status()  # expired → refresh → goto raises
        # refresh-failure path closed context (no zombie)
        assert session._context is None
        assert session._page is None


class TestStop:
    """stop() — close context + page, release playwright."""

    async def test_stop_closes_context_and_page(self, tmp_path):
        """stop() closes page, context, and stops playwright."""
        from backend.services.xhs_login import XhsLoginSession

        mock_module, mock_page, on_calls = _wire_playwright_mock()
        session = XhsLoginSession("acc-1", str(tmp_path / "profile"))
        with patch.dict(sys.modules, {"playwright.async_api": mock_module}):
            await asyncio.gather(
                session.start(),
                _fire_create_after_delay(on_calls, 0.05),
            )
            await session.stop()
        # page.close and context.close were awaited
        mock_page.close.assert_awaited()
        assert session._context is None
        assert session._page is None

    async def test_stop_idempotent(self, tmp_path):
        """stop() called twice doesn't error."""
        from backend.services.xhs_login import XhsLoginSession

        mock_module, _, on_calls = _wire_playwright_mock()
        session = XhsLoginSession("acc-1", str(tmp_path / "profile"))
        with patch.dict(sys.modules, {"playwright.async_api": mock_module}):
            await asyncio.gather(
                session.start(),
                _fire_create_after_delay(on_calls, 0.05),
            )
            await session.stop()
            await session.stop()  # no error


class TestSessionRegistry:
    """Module-level session registry — multi-account concurrency."""

    async def test_get_or_create_reuses_same_session(self, tmp_path):
        """Same account_id → same session instance (no duplicate Chrome)."""
        from backend.services import xhs_login
        from backend.services.xhs_login import get_or_create_session

        # Clean slate (other tests may have left sessions).
        xhs_login._sessions.clear()
        s1 = get_or_create_session("acc-1", str(tmp_path / "p1"))
        s2 = get_or_create_session("acc-1", str(tmp_path / "p2-different"))
        assert s1 is s2
        await xhs_login.stop_all_sessions()

    async def test_different_accounts_get_different_sessions(self, tmp_path):
        """Different account_id → different session instances."""
        from backend.services import xhs_login
        from backend.services.xhs_login import get_or_create_session

        xhs_login._sessions.clear()
        s1 = get_or_create_session("acc-1", str(tmp_path / "p1"))
        s2 = get_or_create_session("acc-2", str(tmp_path / "p2"))
        assert s1 is not s2
        await xhs_login.stop_all_sessions()

    async def test_stop_session_removes_from_registry(self, tmp_path):
        """stop_session closes and removes the session."""
        from backend.services import xhs_login
        from backend.services.xhs_login import get_or_create_session, get_session, stop_session

        xhs_login._sessions.clear()
        get_or_create_session("acc-1", str(tmp_path / "p1"))
        # start it so stop has something to close (without playwright, start fails;
        # just verify registry removal — stop handles None context gracefully).
        stopped = await stop_session("acc-1")
        assert stopped is True
        assert get_session("acc-1") is None

    async def test_stop_session_returns_false_when_not_found(self):
        """stop_session on unknown account → False (no error)."""
        from backend.services import xhs_login
        from backend.services.xhs_login import stop_session

        xhs_login._sessions.clear()
        stopped = await stop_session("nonexistent")
        assert stopped is False


class TestResponseInterception:
    """_on_response / _handle_qr_create / _handle_qr_status — envelope parsing."""

    async def test_handler_ignores_non_qr_responses(self, tmp_path):
        """Responses to unrelated URLs are silently ignored (no crash)."""
        from backend.services.xhs_login import XhsLoginSession

        mock_module, _, on_calls = _wire_playwright_mock()
        session = XhsLoginSession("acc-1", str(tmp_path / "p"))
        with patch.dict(sys.modules, {"playwright.async_api": mock_module}):
            await asyncio.gather(session.start(), _fire_create_after_delay(on_calls, 0.05))
            handler = on_calls[0][1]
            # Unrelated response — should not raise.
            await handler(_build_mock_response("https://x/api/other", "GET", {"foo": "bar"}))
            await handler(
                _build_mock_response("https://x/api/sns/web/v1/login/qrcode/create", "GET", {})
            )
        assert session.qr_id == "qr123"  # unchanged
        await session.stop()

    async def test_handler_ignores_malformed_create_response(self, tmp_path):
        """qrcode/create with missing data/qr_id/url → no crash, no state change."""
        from backend.services.xhs_login import XhsLoginSession

        mock_module, _, on_calls = _wire_playwright_mock()
        session = XhsLoginSession("acc-1", str(tmp_path / "p"))
        with patch.dict(sys.modules, {"playwright.async_api": mock_module}):
            await asyncio.gather(session.start(), _fire_create_after_delay(on_calls, 0.05))
            handler = on_calls[0][1]
            await handler(
                _build_mock_response("https://x/api/sns/web/v1/login/qrcode/create", "POST", {})
            )
            await handler(
                _build_mock_response(
                    "https://x/api/sns/web/v1/login/qrcode/create", "POST", {"data": {}}
                )
            )
            await handler(
                _build_mock_response(
                    "https://x/api/sns/web/v1/login/qrcode/create",
                    "POST",
                    {"data": {"qr_id": "only_id"}},  # missing url
                )
            )
        await session.stop()

    async def test_handler_ignores_non_int_code_status(self, tmp_path):
        """qrcode/status with non-integer codeStatus → ignored, no crash."""
        from backend.services.xhs_login import XhsLoginSession

        mock_module, _, on_calls = _wire_playwright_mock()
        session = XhsLoginSession("acc-1", str(tmp_path / "p"))
        with patch.dict(sys.modules, {"playwright.async_api": mock_module}):
            await asyncio.gather(session.start(), _fire_create_after_delay(on_calls, 0.05))
            handler = on_calls[0][1]
            await handler(
                _build_mock_response(
                    "https://x/api/sns/web/v1/login/qrcode/status",
                    "GET",
                    {"data": {"codeStatus": "not-a-number"}},
                )
            )
            result = await session.get_status()
        assert result["status"] == "waiting"  # unchanged
        await session.stop()


class TestStealthFallback:
    """_apply_stealth — graceful degradation when playwright-stealth missing."""

    async def test_stealth_falls_back_to_webdriver_hide(self, tmp_path):
        """playwright-stealth import fails → manual webdriver hiding init script."""
        from backend.services.xhs_login import XhsLoginSession

        mock_module, _, on_calls = _wire_playwright_mock()
        session = XhsLoginSession("acc-1", str(tmp_path / "p"))

        # Make playwright_stealth import raise inside _apply_stealth.
        with (
            patch.dict(sys.modules, {"playwright.async_api": mock_module}),
            patch.dict(sys.modules, {"playwright_stealth": None}),
        ):
            await asyncio.gather(session.start(), _fire_create_after_delay(on_calls, 0.05))

        # add_init_script should have been called with the webdriver hide script.
        # _apply_stealth is called on the context; check it was invoked.
        assert session._context is not None
        await session.stop()


class TestInspectProfileLoginStatus:
    """inspect_profile_login_status() — read-only durable profile status."""

    async def test_logged_in_when_strong_cookie_present(self):
        from backend.services.xhs_login import inspect_profile_login_status

        mock_module, _, _ = _wire_playwright_mock(
            cookies=[{"name": "access-token-creator.xiaohongshu.com", "value": "tok"}]
        )

        with patch.dict(sys.modules, {"playwright.async_api": mock_module}):
            result = await inspect_profile_login_status("acc-1", "http://127.0.0.1:9223")

        assert result["status"] == "logged_in"
        assert result["is_logged_in"] is True
        assert result["signals"] == ["access-token-creator.xiaohongshu.com"]

    async def test_www_session_pair_is_not_creator_logged_in(self):
        """web_session + id_token without creator token is a partial www session.

        Live profiles often keep this pair after creator SSO expires while
        creator APIs return 401 — must not show green "已登录".
        """
        from backend.services.xhs_login import inspect_profile_login_status

        mock_module, _, _ = _wire_playwright_mock(
            cookies=[
                {"name": "id_token", "value": "token-1"},
                {"name": "web_session", "value": "session-1"},
            ]
        )

        with patch.dict(sys.modules, {"playwright.async_api": mock_module}):
            result = await inspect_profile_login_status("acc-1", "http://127.0.0.1:9223")

        assert result["status"] == "logged_out"
        assert result["is_logged_in"] is False
        assert result["reason"] == "www_only"
        assert set(result["signals"]) == {"id_token", "web_session"}

    async def test_logged_out_when_only_stale_id_token_present(self):
        """Lone id_token is a common false-positive after creator session expiry."""
        from backend.services.xhs_login import inspect_profile_login_status

        mock_module, _, _ = _wire_playwright_mock(
            cookies=[{"name": "id_token", "value": "token-1"}]
        )

        with patch.dict(sys.modules, {"playwright.async_api": mock_module}):
            result = await inspect_profile_login_status("acc-1", "http://127.0.0.1:9223")

        assert result["status"] == "logged_out"
        assert result["is_logged_in"] is False
        assert result["reason"] == "stale_id_token"
        assert result["signals"] == ["id_token"]

    async def test_logged_out_when_only_anonymous_cookie_present(self):
        from backend.services.xhs_login import inspect_profile_login_status

        mock_module, _, _ = _wire_playwright_mock(
            cookies=[{"name": "web_session", "value": "anonymous"}]
        )

        with patch.dict(sys.modules, {"playwright.async_api": mock_module}):
            result = await inspect_profile_login_status("acc-1", "http://127.0.0.1:9223")

        assert result["status"] == "logged_out"
        assert result["is_logged_in"] is False
        assert result["reason"] == "missing_strong_cookie"

    async def test_container_endpoint_uses_raw_cdp_storage_cookies(self):
        from backend.services.xhs_login import XhsLoginSession, inspect_profile_login_status

        raw_ws = MagicMock()
        raw_ws.close = AsyncMock()
        calls = []

        async def _fake_raw_connect(session):
            session._raw_ws = raw_ws

        async def _fake_raw_send(session, method, params=None, *, session_id=""):
            calls.append((method, session_id))
            return {
                "cookies": [
                    {
                        "name": "access-token-creator.xiaohongshu.com",
                        "value": "tok",
                        "domain": ".xiaohongshu.com",
                    }
                ]
            }

        with (
            patch.object(XhsLoginSession, "_raw_connect", _fake_raw_connect),
            patch.object(XhsLoginSession, "_raw_send", _fake_raw_send),
        ):
            result = await inspect_profile_login_status(
                "acc-1", "http://host.containers.internal:9224"
            )

        assert result["status"] == "logged_in"
        assert result["is_logged_in"] is True
        assert result["signals"] == ["access-token-creator.xiaohongshu.com"]
        assert calls == [("Storage.getCookies", None)]
        raw_ws.close.assert_awaited_once()

    async def test_container_endpoint_accepts_ready_creator_page_without_creator_cookie(self):
        """A live Creator Center page can prove login when its token cookie is absent."""
        from backend.services.xhs_login import XhsLoginSession, inspect_profile_login_status

        raw_ws = MagicMock()
        raw_ws.close = AsyncMock()
        calls = []

        async def _fake_raw_connect(session):
            session._raw_ws = raw_ws

        async def _fake_raw_send(session, method, params=None, *, session_id=""):
            calls.append((method, session_id))
            if method == "Storage.getCookies":
                return {
                    "cookies": [
                        {"name": "id_token", "value": "token", "domain": ".xiaohongshu.com"},
                        {
                            "name": "web_session",
                            "value": "session",
                            "domain": ".xiaohongshu.com",
                        },
                    ]
                }
            if method == "Target.getTargets":
                return {
                    "targetInfos": [
                        {
                            "targetId": "creator-page",
                            "type": "page",
                            "url": "https://creator.xiaohongshu.com/new/home",
                        }
                    ]
                }
            if method == "Target.attachToTarget":
                return {"sessionId": "creator-session"}
            if method == "Runtime.evaluate":
                assert session_id == "creator-session"
                assert params is not None and params["expression"].rstrip().endswith(")()")
                return {"result": {"value": {"ready": True}}}
            if method == "Target.detachFromTarget":
                return {}
            return {}

        with (
            patch.object(XhsLoginSession, "_raw_connect", _fake_raw_connect),
            patch.object(XhsLoginSession, "_raw_send", _fake_raw_send),
        ):
            result = await inspect_profile_login_status(
                "acc-1", "http://host.containers.internal:9224"
            )

        assert result["status"] == "logged_in"
        assert result["is_logged_in"] is True
        assert result["reason"] == "creator_page_ready"
        assert result["signals"] == ["creator_page_ready"]
        assert ("Target.detachFromTarget", None) in calls
        raw_ws.close.assert_awaited_once()

    async def test_container_endpoint_keeps_www_only_when_creator_page_is_login_shell(self):
        """A Creator Center login shell must not turn a partial www session green."""
        from backend.services.xhs_login import XhsLoginSession, inspect_profile_login_status

        raw_ws = MagicMock()
        raw_ws.close = AsyncMock()

        async def _fake_raw_connect(session):
            session._raw_ws = raw_ws

        async def _fake_raw_send(session, method, params=None, *, session_id=""):
            if method == "Storage.getCookies":
                return {
                    "cookies": [
                        {"name": "id_token", "value": "token", "domain": ".xiaohongshu.com"},
                        {
                            "name": "web_session",
                            "value": "session",
                            "domain": ".xiaohongshu.com",
                        },
                    ]
                }
            if method == "Target.getTargets":
                return {
                    "targetInfos": [
                        {
                            "targetId": "creator-login",
                            "type": "page",
                            "url": "https://creator.xiaohongshu.com/login",
                        }
                    ]
                }
            if method == "Target.attachToTarget":
                return {"sessionId": "creator-login-session"}
            if method == "Runtime.evaluate":
                assert session_id == "creator-login-session"
                return {"result": {"value": {"ready": False, "signals": []}}}
            return {}

        with (
            patch.object(XhsLoginSession, "_raw_connect", _fake_raw_connect),
            patch.object(XhsLoginSession, "_raw_send", _fake_raw_send),
        ):
            result = await inspect_profile_login_status(
                "acc-1", "http://host.containers.internal:9224"
            )

        assert result["status"] == "logged_out"
        assert result["is_logged_in"] is False
        assert result["reason"] == "www_only"
        assert set(result["signals"]) == {"id_token", "web_session"}
        raw_ws.close.assert_awaited_once()

    async def test_playwright_endpoint_accepts_ready_creator_page_without_creator_cookie(self):
        """The Playwright fallback uses existing Creator Center pages too."""
        from backend.services.xhs_login import inspect_profile_login_status

        mock_module, mock_page, _ = _wire_playwright_mock(
            pages=[],
            cookies=[
                {"name": "id_token", "value": "token"},
                {"name": "web_session", "value": "session"},
            ],
        )
        mock_page.evaluate = AsyncMock(return_value={"ready": True})
        mock_connect = (
            mock_module.async_playwright.return_value.start.return_value.chromium.connect_over_cdp
        )
        mock_browser = mock_connect.return_value
        mock_context = mock_browser.contexts[0]
        mock_context.pages = [mock_page]

        with patch.dict(sys.modules, {"playwright.async_api": mock_module}):
            result = await inspect_profile_login_status("acc-1", "http://127.0.0.1:9223")

        assert result["status"] == "logged_in"
        assert result["is_logged_in"] is True
        assert result["reason"] == "creator_page_ready"
        mock_page.evaluate.assert_awaited_once()

    async def test_unavailable_when_cdp_connection_fails(self):
        from backend.services.xhs_login import inspect_profile_login_status

        mock_module, _, _ = _wire_playwright_mock()
        mock_pw = mock_module.async_playwright.return_value.start.return_value
        mock_pw.chromium.connect_over_cdp.side_effect = TimeoutError("cdp timeout")

        with patch.dict(sys.modules, {"playwright.async_api": mock_module}):
            result = await inspect_profile_login_status("acc-1", "http://127.0.0.1:9223")

        assert result["status"] == "unavailable"
        assert result["is_logged_in"] is False
        assert result["reason"] == "cdp_unreachable"

    async def test_unavailable_port_down_when_cdp_refuses_connection(self):
        from backend.services.xhs_login import inspect_profile_login_status

        mock_module, _, _ = _wire_playwright_mock()
        mock_pw = mock_module.async_playwright.return_value.start.return_value
        mock_pw.chromium.connect_over_cdp.side_effect = RuntimeError("connect ECONNREFUSED")

        with patch.dict(sys.modules, {"playwright.async_api": mock_module}):
            result = await inspect_profile_login_status("acc-1", "http://127.0.0.1:9225")

        assert result["status"] == "unavailable"
        assert result["reason"] == "cdp_port_down"


class TestSubmitVerificationCode:
    """submit_verification_code() — fill numeric code into active CDP page."""

    async def test_fills_verification_code_in_page_frame(self, tmp_path):
        from backend.services.xhs_login import XhsLoginSession

        frame = MagicMock()
        frame.evaluate = AsyncMock(
            return_value={
                "filled": True,
                "clicked": True,
                "target_count": 1,
                "frame_url": "https://www.xiaohongshu.com/explore",
            }
        )
        page = MagicMock()
        page.frames = [frame]
        page.bring_to_front = AsyncMock()

        session = XhsLoginSession("acc-1", str(tmp_path / "profile"))
        session._page = page
        session._qr_id = "qr123"
        session._qr_url = "https://x/qr"

        result = await session.submit_verification_code("123456")

        assert result["submitted"] is True
        assert result["clicked"] is True
        assert result["status"] == "waiting"
        frame.evaluate.assert_awaited_once()
        assert frame.evaluate.await_args.args[1] == "123456"

    async def test_returns_not_submitted_when_input_missing(self, tmp_path):
        from backend.services.xhs_login import XhsLoginSession

        frame = MagicMock()
        frame.evaluate = AsyncMock(
            return_value={
                "filled": False,
                "reason": "verification_input_not_found",
                "frame_url": "https://www.xiaohongshu.com/explore",
            }
        )
        page = MagicMock()
        page.frames = [frame]
        page.bring_to_front = AsyncMock()

        session = XhsLoginSession("acc-1", str(tmp_path / "profile"))
        session._page = page
        session._qr_id = "qr123"
        session._qr_url = "https://x/qr"

        result = await session.submit_verification_code("123456")

        assert result["submitted"] is False
        assert result["reason"] == "verification_input_not_found"

    async def test_fills_verification_code_in_raw_cdp_session(self, tmp_path):
        from backend.services.xhs_login import XhsLoginSession

        session = XhsLoginSession("acc-1", str(tmp_path / "profile"))
        session._raw_ws = MagicMock()
        session._qr_id = "dom-1"
        session._raw_fill_verification_code = AsyncMock(
            return_value={
                "filled": True,
                "clicked": True,
                "target_count": 1,
                "frame_url": "https://www.xiaohongshu.com/explore",
            }
        )
        session._get_raw_status = AsyncMock(
            return_value={
                "status": "scanned",
                "qr_id": "dom-1",
                "url": "",
                "account_id": "acc-1",
            }
        )

        result = await session.submit_verification_code("123456")

        assert result["submitted"] is True
        assert result["clicked"] is True
        assert result["status"] == "scanned"
        session._raw_fill_verification_code.assert_awaited_once_with("123456")
        session._raw_ws = None


# ── Helpers ──


async def _fire_create_after_delay(on_calls: list, delay: float) -> None:
    """Wait for the response listener to register, then fire a qrcode/create."""
    await asyncio.sleep(delay)
    assert on_calls, "page.on('response', ...) was not registered"
    handler = on_calls[0][1]
    resp = _build_mock_response(
        "https://edith.xiaohongshu.com/api/sns/web/v1/login/qrcode/create",
        "POST",
        {
            "success": True,
            "code": 0,
            "data": {"qr_id": "qr123", "code": "c1", "url": "https://x/qr?qrId=qr123"},
        },
    )
    await handler(resp)
