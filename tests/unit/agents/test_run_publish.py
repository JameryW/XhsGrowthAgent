"""Tests for run_publish — the extracted real-publish core (used by publish-retry).

Locks that: (1) extraction from PublisherAgent.execute preserved behavior,
(2) run_publish NEVER honors dry_run (retry always means real publish),
(3) account cookie resolution, (4) no-cookie fast-fail with structured recovery,
(5) auth error classification, (6) history recording gated on post_id.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.agents.publisher import _resolve_cdp_endpoint, run_publish


def _state(**overrides):
    base = {
        "copy_content": {"selected_title": "t", "body_text": "b", "hashtags": []},
        "content_plan": {},
        "visual_plan": {"image_paths": ["/tmp/x.png"]},
        "account_id": "test_account",
        "session_id": "test_session",
        "publish_options": {"dry_run": False},
    }
    base.update(overrides)
    return base


@pytest.fixture
def _browser_settings(monkeypatch):
    """Force use_browser=True, dry_run=False so the real-publish branch runs."""
    fake = MagicMock()
    fake.platform.use_browser = True
    fake.platform.headless = True
    fake.platform.cookie = "GLOBAL_COOKIE"
    fake.platform.user_id = "GLOBAL_UID"
    monkeypatch.setattr("backend.agents.publisher.Settings", lambda: fake)
    return fake


def _mock_client(post_id="p1"):
    client = MagicMock()
    client.publish_post = AsyncMock(
        return_value={
            "post_id": post_id,
            "post_url": "u",
            "status": "published",
            "published_at": "now",
        }
    )
    client.close = AsyncMock()
    return client


def _patch_client(monkeypatch, client):
    ctor = MagicMock(side_effect=lambda **kw: client)
    monkeypatch.setattr("backend.services.xhs_client.XHSClient", ctor)
    return ctor


def test_resolve_cdp_endpoint_uses_env_when_settings_attr_missing(monkeypatch):
    class Platform:
        pass

    class RuntimeSettings:
        platform = Platform()

    monkeypatch.setenv("XHS_CDP_ENDPOINT", "http://cdp.example:9222")

    assert _resolve_cdp_endpoint(RuntimeSettings()) == "http://cdp.example:9222"


def _mock_history(monkeypatch):
    hist = MagicMock()
    hist.return_value.record = AsyncMock()
    monkeypatch.setattr("backend.memory.content_history.ContentHistory", hist)
    return hist


def _mock_account_active(monkeypatch, is_active=True):
    """Patch get_account so the is_active pre-publish check doesn't hit the DB pool."""
    from backend.db.accounts import AccountRow

    account = AccountRow(id="acc", name="acc", is_active=is_active)
    monkeypatch.setattr("backend.db.accounts.get_account", AsyncMock(return_value=account))
    return account


@pytest.mark.asyncio
async def test_uses_selected_account_cookie(_browser_settings, mock_store, monkeypatch):
    """account_id in publish_options → get_account_cookie called, its cookie used."""
    state = _state(publish_options={"dry_run": False, "account_id": "acc_1"})
    client = _mock_client("p1")
    m_cookie = AsyncMock(return_value=("ACC_COOKIE", "ACC_UID"))
    monkeypatch.setattr("backend.db.accounts.get_account_cookie", m_cookie)
    _mock_account_active(monkeypatch)
    m_client = _patch_client(monkeypatch, client)
    _mock_history(monkeypatch)

    result = await run_publish(state, store=mock_store)

    m_cookie.assert_awaited_once_with("acc_1")
    kwargs = m_client.call_args.kwargs
    assert kwargs["cookie"] == "ACC_COOKIE"
    assert kwargs["user_id"] == "ACC_UID"
    assert result["publish_result"]["post_id"] == "p1"


@pytest.mark.asyncio
async def test_falls_back_to_global_when_no_account(_browser_settings, mock_store, monkeypatch):
    """No account_id → use global settings.platform.cookie."""
    state = _state(publish_options={"dry_run": False})
    client = _mock_client("p2")
    m_cookie = AsyncMock()
    monkeypatch.setattr("backend.db.accounts.get_account_cookie", m_cookie)
    m_client = _patch_client(monkeypatch, client)
    _mock_history(monkeypatch)

    await run_publish(state, store=mock_store)

    m_cookie.assert_not_called()
    kwargs = m_client.call_args.kwargs
    assert kwargs["cookie"] == "GLOBAL_COOKIE"
    assert kwargs["user_id"] == "GLOBAL_UID"


@pytest.mark.asyncio
async def test_no_cookie_returns_failed_no_cookie(_browser_settings, mock_store, monkeypatch):
    """Selected account has no cookie → fail fast with no_cookie, no XHSClient built."""
    state = _state(publish_options={"dry_run": False, "account_id": "acc_empty"})
    m_cookie = AsyncMock(return_value=("", ""))
    monkeypatch.setattr("backend.db.accounts.get_account_cookie", m_cookie)
    m_client = MagicMock()
    monkeypatch.setattr("backend.services.xhs_client.XHSClient", m_client)

    result = await run_publish(state, store=mock_store)

    m_cookie.assert_awaited_once_with("acc_empty")
    m_client.assert_not_called()  # must not attempt to publish without a cookie
    pr = result["publish_result"]
    assert pr["status"] == "failed"
    assert pr["error_type"] == "no_cookie"
    rec = pr["recovery"]
    assert isinstance(rec, dict)
    assert rec["action"] == "reconfigure"


@pytest.mark.asyncio
async def test_classifies_auth_error(_browser_settings, mock_store, monkeypatch):
    """publish throws auth error → auth_expired error_type + structured recovery."""
    state = _state(publish_options={"dry_run": False, "account_id": "acc_x"})
    m_cookie = AsyncMock(return_value=("STALE_COOKIE", "ACC_UID"))
    monkeypatch.setattr("backend.db.accounts.get_account_cookie", m_cookie)
    _mock_account_active(monkeypatch)

    client = MagicMock()
    client.publish_post = AsyncMock(side_effect=RuntimeError("cookie expired, login required"))
    client.close = AsyncMock()
    monkeypatch.setattr("backend.services.xhs_client.XHSClient", lambda **kw: client)
    _mock_history(monkeypatch)

    result = await run_publish(state, store=mock_store)

    pr = result["publish_result"]
    assert pr["status"] == "failed"
    assert pr["error_type"] == "auth_expired"
    assert isinstance(pr["recovery"], dict)


@pytest.mark.asyncio
async def test_preserves_publish_service_error(_browser_settings, mock_store, monkeypatch):
    """publish_post returning a platform error keeps error/recovery in state."""

    state = _state(publish_options={"dry_run": False, "account_id": "acc_x"})
    m_cookie = AsyncMock(return_value=("COOKIE", "ACC_UID"))
    monkeypatch.setattr("backend.db.accounts.get_account_cookie", m_cookie)
    _mock_account_active(monkeypatch)

    client = MagicMock()
    client.publish_post = AsyncMock(
        return_value={"post_id": "", "status": "failed", "error": "未绑定手机号"}
    )
    client.close = AsyncMock()
    monkeypatch.setattr("backend.services.xhs_client.XHSClient", lambda **kw: client)
    _mock_history(monkeypatch)

    result = await run_publish(state, store=mock_store)

    pr = result["publish_result"]
    assert pr["status"] == "failed"
    assert pr["error"] == "未绑定手机号"
    assert pr["error_type"] == "account_unverified"
    assert pr["recovery"]["action"] == "verify_account"


@pytest.mark.asyncio
async def test_never_honors_dry_run(_browser_settings, mock_store, monkeypatch):
    """run_publish ignores dry_run=True — retry always means real publish.

    This is the contract that justifies the extraction: execute's mock branch
    must NOT be reachable from the retry path.
    """
    state = _state(publish_options={"dry_run": True, "account_id": "acc_1"})
    client = _mock_client("p_real")
    m_cookie = AsyncMock(return_value=("ACC_COOKIE", "ACC_UID"))
    monkeypatch.setattr("backend.db.accounts.get_account_cookie", m_cookie)
    _mock_account_active(monkeypatch)
    _patch_client(monkeypatch, client)
    _mock_history(monkeypatch)

    result = await run_publish(state, store=mock_store)

    # Real publish ran (publish_post awaited), not the mock path
    client.publish_post.assert_awaited_once()
    assert result["publish_result"]["post_id"] == "p_real"
    assert result["publish_result"]["status"] != "mock_published"


@pytest.mark.asyncio
async def test_records_history_on_success_only(_browser_settings, mock_store, monkeypatch):
    """ContentHistory.record called on success (post_id present), skipped on failure."""
    state = _state(publish_options={"dry_run": False, "account_id": "acc_1"})
    client = _mock_client("p_ok")
    m_cookie = AsyncMock(return_value=("ACC_COOKIE", "ACC_UID"))
    monkeypatch.setattr("backend.db.accounts.get_account_cookie", m_cookie)
    _mock_account_active(monkeypatch)
    _patch_client(monkeypatch, client)
    hist = _mock_history(monkeypatch)

    await run_publish(state, store=mock_store)

    hist.return_value.record.assert_awaited_once()
    data = hist.return_value.record.await_args.kwargs["data"]
    assert data["title"] == "t"

    # Now a failed publish (empty post_id) → record NOT called
    client_fail = MagicMock()
    client_fail.publish_post = AsyncMock(return_value={"post_id": "", "status": "failed"})
    client_fail.close = AsyncMock()
    _patch_client(monkeypatch, client_fail)
    hist.return_value.record.reset_mock()

    await run_publish(state, store=mock_store)

    hist.return_value.record.assert_not_awaited()


@pytest.mark.asyncio
async def test_ignores_past_suggested_timing(_browser_settings, mock_store, monkeypatch):
    """Historical plan suggestions must not turn a real retry into scheduled publish."""

    state = _state(content_plan={"suggested_timing": "2023-10-29T20:30:00Z"})
    client = _mock_client("p_sched")
    _patch_client(monkeypatch, client)
    _mock_history(monkeypatch)

    await run_publish(state, store=mock_store)

    post = client.publish_post.await_args.args[0]
    assert post.scheduled_time == ""
