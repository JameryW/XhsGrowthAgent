"""Tests for XHS credential resolution in the system health check."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock

import pytest


def _env(cookie: str = "", user_id: str = "") -> None:
    if cookie:
        os.environ["XHS_COOKIE"] = cookie
    else:
        os.environ.pop("XHS_COOKIE", None)
    if user_id:
        os.environ["XHS_USER_ID"] = user_id
    else:
        os.environ.pop("XHS_USER_ID", None)


@pytest.mark.asyncio
async def test_resolve_prefers_db_active_account(monkeypatch: pytest.MonkeyPatch) -> None:
    """DB active account credentials win over env fallback."""
    _env("ENV_COOKIE", "ENV_UID")
    active = MagicMock()
    active.id = "acc-1"
    monkeypatch.setattr("backend.db.pool.is_pool_ready", lambda: True)
    monkeypatch.setattr(
        "backend.db.accounts.get_active_account", AsyncMock(return_value=active)
    )
    monkeypatch.setattr(
        "backend.db.accounts.get_account_cookie",
        AsyncMock(return_value=("DB_COOKIE", "DB_UID")),
    )

    from backend.api.routes.system import _resolve_xhs_credentials

    cookie, user_id = await _resolve_xhs_credentials()
    assert cookie == "DB_COOKIE"
    assert user_id == "DB_UID"


@pytest.mark.asyncio
async def test_resolve_falls_back_to_env_when_no_active_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No active DB account → env-backed credentials."""
    _env("ENV_COOKIE", "ENV_UID")
    monkeypatch.setattr("backend.db.pool.is_pool_ready", lambda: True)
    monkeypatch.setattr(
        "backend.db.accounts.get_active_account", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        "backend.db.accounts.get_account_cookie", AsyncMock(return_value=("", ""))
    )

    from backend.api.routes.system import _resolve_xhs_credentials

    cookie, user_id = await _resolve_xhs_credentials()
    assert cookie == "ENV_COOKIE"
    assert user_id == "ENV_UID"


@pytest.mark.asyncio
async def test_resolve_falls_back_to_env_when_db_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pool not ready → env fallback, no DB calls made."""
    _env("ENV_COOKIE", "ENV_UID")
    monkeypatch.setattr("backend.db.pool.is_pool_ready", lambda: False)

    from backend.api.routes.system import _resolve_xhs_credentials

    cookie, user_id = await _resolve_xhs_credentials()
    assert cookie == "ENV_COOKIE"
    assert user_id == "ENV_UID"


@pytest.mark.asyncio
async def test_check_xhs_ok_when_db_account_has_cookie(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_check_xhs reports ok when the DB active account has credentials."""
    _env()  # no env credentials
    active = MagicMock()
    active.id = "acc-1"
    monkeypatch.setattr("backend.db.pool.is_pool_ready", lambda: True)
    monkeypatch.setattr(
        "backend.db.accounts.get_active_account", AsyncMock(return_value=active)
    )
    monkeypatch.setattr(
        "backend.db.accounts.get_account_cookie",
        AsyncMock(return_value=("DB_COOKIE", "DB_UID")),
    )

    from backend.api.routes.system import _check_xhs

    result = await _check_xhs()
    assert result["status"] == "ok"
    assert result["configured"] is True
    assert result["cookie_set"] is True
    assert result["user_id_set"] is True


@pytest.mark.asyncio
async def test_check_xhs_warning_when_no_credentials_anywhere(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No DB account and no env credentials → warning."""
    _env()
    monkeypatch.setattr("backend.db.pool.is_pool_ready", lambda: True)
    monkeypatch.setattr(
        "backend.db.accounts.get_active_account", AsyncMock(return_value=None)
    )

    from backend.api.routes.system import _check_xhs

    result = await _check_xhs()
    assert result["status"] == "warning"
    assert result["configured"] is False
