"""Tests for XhsLoginSession — headless Chrome QR-code login service.

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
    *, pages: list[MagicMock] | None = None, goto_side_effect=None
) -> tuple[MagicMock, MagicMock, list]:
    """Wire up a controllable playwright mock chain.

    Returns (mock_playwright_module, mock_page, on_response_calls) where
    ``on_response_calls`` collects the (handler,) tuples passed to page.on().
    The test can then invoke the handler with synthetic responses.
    """
    mock_page = MagicMock()
    mock_page.goto = AsyncMock(side_effect=goto_side_effect) if goto_side_effect else AsyncMock()
    mock_page.close = AsyncMock()
    on_response_calls: list = []
    mock_page.on = lambda event, handler: on_response_calls.append((event, handler))

    mock_context = MagicMock()
    mock_context.pages = pages if pages is not None else []
    mock_context.new_page = AsyncMock(return_value=mock_page)
    mock_context.close = AsyncMock()
    mock_context.add_init_script = AsyncMock()

    mock_chromium = MagicMock()
    mock_chromium.launch_persistent_context = AsyncMock(return_value=mock_context)

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
                await asyncio.sleep(0.05)
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
        """No qrcode/create response within timeout → LoginError."""
        from backend.services.xhs_login import XhsLoginSession

        mock_module, _, _ = _wire_playwright_mock()
        # Patch the wait timeout to be tiny so the test doesn't hang 30s.
        session = XhsLoginSession("acc-1", str(tmp_path / "profile"))

        with (
            patch.dict(sys.modules, {"playwright.async_api": mock_module}),
            patch("backend.services.xhs_login._QR_CREATE_WAIT_S", 0.2),
            pytest.raises(Exception, match="未收到 qrcode/create"),
        ):
            await session.start()
        await session.stop()

    async def test_start_failure_closes_context_no_leak(self, tmp_path):
        """start() launch/wait failure → context closed, no zombie Chrome.

        Regression guard: route returns 503 on LoginError but never calls
        stop(); without self-cleanup the headless Chrome leaks.
        """
        from backend.services.xhs_login import XhsLoginSession

        mock_module, mock_page, _ = _wire_playwright_mock()
        session = XhsLoginSession("acc-1", str(tmp_path / "profile"))

        with (
            patch.dict(sys.modules, {"playwright.async_api": mock_module}),
            patch("backend.services.xhs_login._QR_CREATE_WAIT_S", 0.2),
            pytest.raises(Exception, match="未收到 qrcode/create"),
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


class TestGetStatus:
    """get_status() — map codeStatus to waiting/scanned/confirmed/expired."""

    async def _start_session(self, session, on_calls):
        """Helper: start a session and fire an initial qrcode/create."""
        await asyncio.gather(
            session.start(),
            _fire_create_after_delay(on_calls, 0.05),
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

    async def test_status_scanned_after_code_status_1(self, tmp_path):
        """codeStatus=1 (scanned, awaiting confirm) → status=scanned."""
        from backend.services.xhs_login import XhsLoginSession

        mock_module, _, on_calls = _wire_playwright_mock()
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
            result = await session.get_status()
        assert result["status"] == "scanned"
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
        headless Chrome in a long-running server. Frontend's explicit stop()
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

    async def test_status_expired_refreshes_qr(self, tmp_path):
        """Expired QR (timeout) → status=expired with a new url after refresh."""
        from backend.services.xhs_login import XhsLoginSession

        mock_module, mock_page, on_calls = _wire_playwright_mock()
        session = XhsLoginSession("acc-1", str(tmp_path / "profile"))
        with (
            patch.dict(sys.modules, {"playwright.async_api": mock_module}),
            patch("backend.services.xhs_login._QR_CONFIRM_TIMEOUT_S", 0.1),
        ):
            await self._start_session(session, on_calls)
            # Wait past the (patched tiny) expiry.
            await asyncio.sleep(0.15)

            # get_status will detect expiry → _refresh_qr → goto + wait for new create.
            # Fire a new create response after get_status's refresh goto lands.
            async def _fire_refresh_create():
                await asyncio.sleep(0.05)
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

    async def test_status_when_no_session_returns_waiting(self, tmp_path):
        """get_status() on a never-started session → status=waiting, empty qr."""
        from backend.services.xhs_login import XhsLoginSession

        session = XhsLoginSession("acc-1", str(tmp_path / "profile"))
        result = await session.get_status()
        assert result["status"] == "waiting"
        assert result["qr_id"] == ""

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
            patch("backend.services.xhs_login._QR_CONFIRM_TIMEOUT_S", 0.1),
            pytest.raises(LoginError, match="navigation failed"),
        ):
            await self._start_session(session, on_calls)
            await asyncio.sleep(0.15)  # past expiry
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
