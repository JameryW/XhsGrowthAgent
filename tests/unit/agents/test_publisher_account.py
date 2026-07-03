"""Tests for PublisherAgent account-aware cookie resolution."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.agents.publisher import PublisherAgent


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
    """Mock XHSClient with async publish_post/close."""
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
    """Patch XHSClient to return `client`; returns a mock capturing call kwargs."""
    ctor = MagicMock(side_effect=lambda **kw: client)
    monkeypatch.setattr("backend.services.xhs_client.XHSClient", ctor)
    return ctor


def _mock_history(monkeypatch):
    """Patch ContentHistory with an async record."""
    hist = MagicMock()
    hist.return_value.record = AsyncMock()
    monkeypatch.setattr("backend.memory.content_history.ContentHistory", hist)


def _mock_account_active(monkeypatch, is_active=True):
    """Patch get_account to return an AccountRow with the given is_active."""
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
    _mock_account_active(monkeypatch, is_active=True)
    m_client = _patch_client(monkeypatch, client)
    _mock_history(monkeypatch)

    result = await PublisherAgent().execute(state, store=mock_store)

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

    await PublisherAgent().execute(state, store=mock_store)

    m_cookie.assert_not_called()
    kwargs = m_client.call_args.kwargs
    assert kwargs["cookie"] == "GLOBAL_COOKIE"
    assert kwargs["user_id"] == "GLOBAL_UID"


@pytest.mark.asyncio
async def test_generates_text_cover_when_no_images(_browser_settings, mock_store, monkeypatch):
    """No material image paths → generate a text cover and publish with it."""
    state = _state(
        content_plan={"key_points": ["p1", "p2", "p3"]},
        visual_plan={"color_palette": ["#FFE4E1", "#FFDAB9", "#FFFACD"]},
    )
    client = _mock_client("p_cover")
    _patch_client(monkeypatch, client)
    _mock_history(monkeypatch)
    cover = MagicMock(return_value="/tmp/generated-cover.png")
    monkeypatch.setattr("backend.agents.publisher.generate_text_cover_image", cover)

    await PublisherAgent().execute(state, store=mock_store)

    cover.assert_called_once()
    kwargs = cover.call_args.kwargs
    assert kwargs["title"] == "t"
    assert kwargs["key_points"] == ["p1", "p2", "p3"]
    assert kwargs["color_palette"] == ["#FFE4E1", "#FFDAB9", "#FFFACD"]
    post = client.publish_post.await_args.args[0]
    assert post.image_paths == ["/tmp/generated-cover.png"]


@pytest.mark.asyncio
async def test_no_cookie_when_account_unconfigured(_browser_settings, mock_store, monkeypatch):
    """Selected account has no cookie → fail fast with no_cookie, no XHSClient built."""
    state = _state(publish_options={"dry_run": False, "account_id": "acc_empty"})
    m_cookie = AsyncMock(return_value=("", ""))
    monkeypatch.setattr("backend.db.accounts.get_account_cookie", m_cookie)
    m_client = MagicMock()
    monkeypatch.setattr("backend.services.xhs_client.XHSClient", m_client)

    result = await PublisherAgent().execute(state, store=mock_store)

    m_cookie.assert_awaited_once_with("acc_empty")
    m_client.assert_not_called()  # must not attempt to publish without a cookie
    pr = result["publish_result"]
    assert pr["status"] == "failed"
    assert pr["error_type"] == "no_cookie"
    assert "acc_empty" in pr["error"]
    # recovery must be a structured dict (not a plain string) so Dashboard.vue's
    # publishError.recovery.{hint,action,action_label} renders a recovery button.
    rec = pr["recovery"]
    assert isinstance(rec, dict)
    assert rec["action"] == "reconfigure"
    assert rec["hint"]
    assert rec["action_label"]


@pytest.mark.asyncio
async def test_inactive_account_fails_fast(_browser_settings, mock_store, monkeypatch):
    """Selected account is_active=False → fail fast, no XHSClient built."""
    state = _state(publish_options={"dry_run": False, "account_id": "acc_off"})
    m_cookie = AsyncMock(return_value=("COOKIE", "UID"))  # cookie present, but account inactive
    monkeypatch.setattr("backend.db.accounts.get_account_cookie", m_cookie)
    _mock_account_active(monkeypatch, is_active=False)
    m_client = MagicMock()
    monkeypatch.setattr("backend.services.xhs_client.XHSClient", m_client)

    result = await PublisherAgent().execute(state, store=mock_store)

    m_client.assert_not_called()  # must not attempt to publish with a deactivated account
    pr = result["publish_result"]
    assert pr["status"] == "failed"
    assert pr["error_type"] == "account_inactive"
    assert "acc_off" in pr["error"]
    # recovery must be a structured dict — same regression guard as no_cookie path.
    rec = pr["recovery"]
    assert isinstance(rec, dict)
    assert rec["action"] == "reconfigure"
    assert rec["hint"]
    assert rec["action_label"]


@pytest.mark.asyncio
async def test_dry_run_records_account_id(mock_store, monkeypatch):
    """dry_run → mock result carries the selected account_id."""
    state = _state(publish_options={"dry_run": True, "account_id": "acc_dry"})
    _mock_history(monkeypatch)

    result = await PublisherAgent().execute(state, store=mock_store)

    assert result["publish_result"]["status"] == "mock_published"
    assert result["publish_result"]["account_id"] == "acc_dry"


@pytest.mark.asyncio
async def test_selected_account_expired_cookie_classified(
    _browser_settings, mock_store, monkeypatch
):
    """Selected account cookie present but publish throws auth error → auth_expired."""
    state = _state(publish_options={"dry_run": False, "account_id": "acc_x"})
    m_cookie = AsyncMock(return_value=("STALE_COOKIE", "ACC_UID"))
    monkeypatch.setattr("backend.db.accounts.get_account_cookie", m_cookie)
    _mock_account_active(monkeypatch, is_active=True)

    client = MagicMock()
    client.publish_post = AsyncMock(side_effect=RuntimeError("cookie expired, login required"))
    client.close = AsyncMock()
    monkeypatch.setattr("backend.services.xhs_client.XHSClient", lambda **kw: client)
    _mock_history(monkeypatch)

    result = await PublisherAgent().execute(state, store=mock_store)
    pr = result["publish_result"]
    assert pr["status"] == "failed"
    assert pr["error_type"] == "auth_expired"
    assert isinstance(pr["recovery"], dict)
    assert pr["recovery"]["action"] == "reconfigure"
