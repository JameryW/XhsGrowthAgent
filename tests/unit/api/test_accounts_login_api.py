"""Tests for the scan-login (QR code) endpoints on the accounts router.

POST /accounts/{id}/login/qr        — start headless Chrome, return qr_id+url
GET  /accounts/{id}/login/qr/status — poll codeStatus → waiting/scanned/confirmed/expired
POST /accounts/{id}/login/qr/stop   — close the login session

The endpoints delegate to ``backend.services.xhs_login``; we mock the session
object so these tests run without playwright/the [browser] extra.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def setup_crypto():
    """Ensure ENCRYPTION_KEY is set for tests."""
    from backend.db.crypto import generate_key

    os.environ["ENCRYPTION_KEY"] = generate_key()
    import backend.db.crypto as crypto_mod

    crypto_mod._fernet = None
    yield
    os.environ.pop("ENCRYPTION_KEY", None)
    crypto_mod._fernet = None


@pytest.fixture
def client():
    """Create a test client with the accounts router mounted."""
    from fastapi import FastAPI

    from backend.api.routes.accounts import router

    app = FastAPI()
    app.include_router(router, prefix="/api/accounts")
    return TestClient(app)


def _mock_account(account_id: str = "acc-1", profile_path: str = "/tmp/profile-acc-1"):
    """Build a mock AccountRow with a chrome_profile_path binding."""
    from backend.db.accounts import AccountRow

    return AccountRow(
        id=account_id,
        name="Test Account",
        is_active=False,
        created_at="2026-01-01T00:00:00",
        chrome_profile_path=profile_path,
        cdp_port=9223,
    )


# ── POST /login/qr ──


def test_start_qr_login_returns_qr_id_and_url(client):
    """POST /accounts/{id}/login/qr → {qr_id, url, account_id}."""
    account = _mock_account()
    mock_session = MagicMock()
    mock_session.start = AsyncMock(
        return_value={"qr_id": "qr123", "url": "https://x/qr?qrId=qr123", "account_id": "acc-1"}
    )

    with (
        patch("backend.db.accounts.get_account", new_callable=AsyncMock, return_value=account),
        patch(
            "backend.db.accounts.get_account_cdp_endpoint",
            new_callable=AsyncMock,
            return_value="http://172.19.0.1:9224",
        ),
        patch(
            "backend.services.xhs_login.get_or_create_session",
            return_value=mock_session,
        ),
    ):
        resp = client.post("/api/accounts/acc-1/login/qr")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["qr_id"] == "qr123"
    assert data["url"] == "https://x/qr?qrId=qr123"
    assert data["account_id"] == "acc-1"
    mock_session.start.assert_awaited_once()


def test_start_qr_login_can_return_already_confirmed(client):
    """Already logged-in profile → start returns confirmed instead of a QR URL."""
    account = _mock_account()
    mock_session = MagicMock()
    mock_session.start = AsyncMock(
        return_value={"status": "confirmed", "qr_id": "", "url": "", "account_id": "acc-1"}
    )

    with (
        patch("backend.db.accounts.get_account", new_callable=AsyncMock, return_value=account),
        patch(
            "backend.db.accounts.get_account_cdp_endpoint",
            new_callable=AsyncMock,
            return_value="http://172.19.0.1:9224",
        ),
        patch(
            "backend.services.xhs_login.get_or_create_session",
            return_value=mock_session,
        ),
    ):
        resp = client.post("/api/accounts/acc-1/login/qr")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "confirmed"
    assert data["url"] == ""
    mock_session.start.assert_awaited_once()


def test_start_qr_login_404_when_account_not_found(client):
    """Account doesn't exist → 404 AccountNotFoundError."""
    with (
        patch("backend.db.accounts.get_account", new_callable=AsyncMock, return_value=None),
        pytest.raises(Exception, match="not found"),
    ):
        client.post("/api/accounts/acc-1/login/qr")


def test_start_qr_login_400_when_no_profile_path(client):
    """Account has no chrome_profile_path → ValidationError (400)."""
    from backend.db.accounts import AccountRow

    account = AccountRow(id="acc-1", name="No Profile", chrome_profile_path="", cdp_port=0)

    with (
        patch("backend.db.accounts.get_account", new_callable=AsyncMock, return_value=account),
        pytest.raises(Exception, match="chrome_profile_path"),
    ):
        client.post("/api/accounts/acc-1/login/qr")


def test_start_qr_login_503_on_login_error(client):
    """LoginError (playwright missing / shield block) → 503 SERVICE_UNAVAILABLE."""
    from backend.services.xhs_login import LoginError

    account = _mock_account()
    mock_session = MagicMock()
    mock_session.start = AsyncMock(side_effect=LoginError("playwright 未安装"))

    # Without the error-handler middleware, APIError(503) propagates as a raw
    # exception. We assert the raised exception carries the right code/status.
    from backend.api.errors import ErrorCode

    with (
        patch("backend.db.accounts.get_account", new_callable=AsyncMock, return_value=account),
        patch(
            "backend.db.accounts.get_account_cdp_endpoint",
            new_callable=AsyncMock,
            return_value="http://172.19.0.1:9224",
        ),
        patch(
            "backend.services.xhs_login.get_or_create_session",
            return_value=mock_session,
        ),
        pytest.raises(Exception) as exc_info,
    ):
        client.post("/api/accounts/acc-1/login/qr")

    err = exc_info.value
    # APIError carries code + status_code attributes.
    assert hasattr(err, "code")
    assert err.code == ErrorCode.SERVICE_UNAVAILABLE
    assert err.status_code == 503


def test_start_qr_login_503_on_start_timeout(client):
    """Hung Playwright/CDP start → 503 and session cleanup instead of endless loading."""
    from backend.api.errors import ErrorCode

    account = _mock_account()
    mock_session = MagicMock()
    mock_session.start = AsyncMock(side_effect=TimeoutError())

    with (
        patch("backend.db.accounts.get_account", new_callable=AsyncMock, return_value=account),
        patch(
            "backend.db.accounts.get_account_cdp_endpoint",
            new_callable=AsyncMock,
            return_value="http://172.19.0.1:9224",
        ),
        patch(
            "backend.services.xhs_login.get_or_create_session",
            return_value=mock_session,
        ),
        patch("backend.services.xhs_login.stop_session", new_callable=AsyncMock) as mock_stop,
        pytest.raises(Exception) as exc_info,
    ):
        client.post("/api/accounts/acc-1/login/qr")

    err = exc_info.value
    assert hasattr(err, "code")
    assert err.code == ErrorCode.SERVICE_UNAVAILABLE
    assert err.status_code == 503
    assert "启动扫码登录超时" in err.message
    mock_stop.assert_awaited_once_with("acc-1")


# ── GET /login/qr/status ──


def test_get_login_status_returns_profile_state(client):
    """GET /accounts/{id}/login/status → durable profile login status."""
    account = _mock_account()
    with (
        patch("backend.db.accounts.get_account", new_callable=AsyncMock, return_value=account),
        patch(
            "backend.db.accounts.get_account_cdp_endpoint",
            new_callable=AsyncMock,
            return_value="http://172.19.0.1:9224",
        ),
        patch(
            "backend.services.chrome_launcher.probe_port",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_probe,
        patch(
            "backend.services.xhs_login.inspect_profile_login_status",
            new_callable=AsyncMock,
            return_value={
                "account_id": "acc-1",
                "status": "logged_in",
                "is_logged_in": True,
                "reason": "strong_cookie",
                "signals": ["access-token-creator.xiaohongshu.com"],
            },
        ) as mock_status,
    ):
        resp = client.get("/api/accounts/acc-1/login/status")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "logged_in"
    assert data["is_logged_in"] is True
    mock_probe.assert_awaited_once_with(9224, host="172.19.0.1")
    mock_status.assert_awaited_once_with("acc-1", "http://172.19.0.1:9224")


def test_get_login_status_unavailable_when_no_profile(client):
    """Missing profile binding → unavailable status, not a QR/session error."""
    from backend.db.accounts import AccountRow

    account = AccountRow(id="acc-1", name="No Profile", chrome_profile_path="", cdp_port=0)
    with patch("backend.db.accounts.get_account", new_callable=AsyncMock, return_value=account):
        resp = client.get("/api/accounts/acc-1/login/status")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "unavailable"
    assert data["reason"] == "missing_profile"


def test_get_login_status_browser_down_when_cdp_endpoint_not_answering(client):
    """CDP port not answering → browser-not-running status for the settings UI."""
    account = _mock_account()
    with (
        patch("backend.db.accounts.get_account", new_callable=AsyncMock, return_value=account),
        patch(
            "backend.db.accounts.get_account_cdp_endpoint",
            new_callable=AsyncMock,
            return_value="http://172.19.0.1:9224",
        ),
        patch(
            "backend.services.chrome_launcher.probe_port",
            new_callable=AsyncMock,
            return_value=False,
        ) as mock_probe,
        patch(
            "backend.services.xhs_login.inspect_profile_login_status",
            new_callable=AsyncMock,
        ) as mock_status,
    ):
        resp = client.get("/api/accounts/acc-1/login/status")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "unavailable"
    assert data["is_logged_in"] is False
    assert data["reason"] == "cdp_port_down"
    mock_probe.assert_awaited_once_with(9224, host="172.19.0.1")
    mock_status.assert_not_awaited()


def test_get_qr_status_returns_current_status(client):
    """GET /accounts/{id}/login/qr/status → {status, qr_id, url, account_id}."""
    account = _mock_account()
    mock_session = MagicMock()
    mock_session.get_status = AsyncMock(
        return_value={
            "status": "scanned",
            "qr_id": "qr123",
            "url": "https://x/qr",
            "account_id": "acc-1",
        }
    )

    with (
        patch("backend.db.accounts.get_account", new_callable=AsyncMock, return_value=account),
        patch("backend.services.xhs_login.get_session", return_value=mock_session),
    ):
        resp = client.get("/api/accounts/acc-1/login/qr/status")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "scanned"
    assert data["qr_id"] == "qr123"
    mock_session.get_status.assert_awaited_once()


def test_get_qr_status_404_when_account_not_found(client):
    """Account doesn't exist → 404."""
    with (
        patch("backend.db.accounts.get_account", new_callable=AsyncMock, return_value=None),
        pytest.raises(Exception, match="not found"),
    ):
        client.get("/api/accounts/acc-1/login/qr/status")


def test_get_qr_status_400_when_no_session(client):
    """No active login session → ValidationError."""
    account = _mock_account()
    with (
        patch("backend.db.accounts.get_account", new_callable=AsyncMock, return_value=account),
        patch("backend.services.xhs_login.get_session", return_value=None),
        pytest.raises(Exception, match="没有进行中的扫码登录会话"),
    ):
        client.get("/api/accounts/acc-1/login/qr/status")


def test_get_qr_status_confirmed_clears_url(client):
    """Confirmed status → url is empty (no need to keep showing QR)."""
    account = _mock_account()
    mock_session = MagicMock()
    mock_session.get_status = AsyncMock(
        return_value={"status": "confirmed", "qr_id": "qr123", "url": "", "account_id": "acc-1"}
    )

    with (
        patch("backend.db.accounts.get_account", new_callable=AsyncMock, return_value=account),
        patch("backend.services.xhs_login.get_session", return_value=mock_session),
    ):
        resp = client.get("/api/accounts/acc-1/login/qr/status")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "confirmed"
    assert data["url"] == ""


# ── POST /login/qr/verification-code ──


def test_submit_verification_code_forwards_to_session(client):
    """POST /accounts/{id}/login/qr/verification-code → session submit result."""
    account = _mock_account()
    mock_session = MagicMock()
    mock_session.submit_verification_code = AsyncMock(
        return_value={
            "submitted": True,
            "status": "scanned",
            "qr_id": "qr123",
            "url": "https://x/qr",
            "account_id": "acc-1",
            "clicked": True,
        }
    )

    with (
        patch("backend.db.accounts.get_account", new_callable=AsyncMock, return_value=account),
        patch("backend.services.xhs_login.get_session", return_value=mock_session),
    ):
        resp = client.post(
            "/api/accounts/acc-1/login/qr/verification-code",
            json={"code": "123456"},
        )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["submitted"] is True
    assert data["clicked"] is True
    mock_session.submit_verification_code.assert_awaited_once_with("123456")


def test_submit_verification_code_rejects_non_numeric_code(client):
    """Non-numeric verification code → ValidationError."""
    account = _mock_account()
    with (
        patch("backend.db.accounts.get_account", new_callable=AsyncMock, return_value=account),
        pytest.raises(Exception, match="验证码必须"),
    ):
        client.post(
            "/api/accounts/acc-1/login/qr/verification-code",
            json={"code": "12ab"},
        )


def test_submit_verification_code_400_when_no_session(client):
    """No active login session → ValidationError."""
    account = _mock_account()
    with (
        patch("backend.db.accounts.get_account", new_callable=AsyncMock, return_value=account),
        patch("backend.services.xhs_login.get_session", return_value=None),
        pytest.raises(Exception, match="没有进行中的扫码登录会话"),
    ):
        client.post(
            "/api/accounts/acc-1/login/qr/verification-code",
            json={"code": "123456"},
        )


# ── POST /login/qr/stop ──


def test_stop_qr_login_closes_session(client):
    """POST /accounts/{id}/login/qr/stop → {stopped: true, account_id}."""
    account = _mock_account()
    with (
        patch("backend.db.accounts.get_account", new_callable=AsyncMock, return_value=account),
        patch("backend.services.xhs_login.stop_session", new_callable=AsyncMock, return_value=True),
    ):
        resp = client.post("/api/accounts/acc-1/login/qr/stop")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["stopped"] is True
    assert data["account_id"] == "acc-1"


def test_stop_qr_login_returns_false_when_no_session(client):
    """Stop on account with no active session → {stopped: false} (not an error)."""
    account = _mock_account()
    with (
        patch("backend.db.accounts.get_account", new_callable=AsyncMock, return_value=account),
        patch(
            "backend.services.xhs_login.stop_session",
            new_callable=AsyncMock,
            return_value=False,
        ),
    ):
        resp = client.post("/api/accounts/acc-1/login/qr/stop")

    assert resp.status_code == 200
    assert resp.json()["data"]["stopped"] is False


def test_stop_qr_login_404_when_account_not_found(client):
    """Account doesn't exist → 404."""
    with (
        patch("backend.db.accounts.get_account", new_callable=AsyncMock, return_value=None),
        pytest.raises(Exception, match="not found"),
    ):
        client.post("/api/accounts/acc-1/login/qr/stop")
