"""Tests for XHS trend tool credential resolution."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

import backend.tools.xhs.trending as trending_mod
from backend.agents.trend_scout import TrendScoutAgent
from backend.services.xhs_client import XHSTrendingTopic


def _settings(cookie: str = "ENV_COOKIE", user_id: str = "ENV_UID") -> MagicMock:
    settings = MagicMock()
    settings.platform.cookie = cookie
    settings.platform.user_id = user_id
    settings.platform.use_browser = False
    settings.platform.headless = True
    return settings


@pytest.mark.asyncio
async def test_get_client_prefers_requested_db_account(monkeypatch: pytest.MonkeyPatch) -> None:
    """Requested workflow account DB credentials override environment settings."""
    get_account_cookie = AsyncMock(return_value=("a=1;\n b=2", " user\nid "))
    get_active_account = AsyncMock()
    xhs_client = MagicMock()

    monkeypatch.setattr("backend.config.settings.Settings", lambda: _settings())
    monkeypatch.setattr("backend.db.pool.is_pool_ready", lambda: True)
    monkeypatch.setattr("backend.db.accounts.get_account_cookie", get_account_cookie)
    monkeypatch.setattr("backend.db.accounts.get_active_account", get_active_account)
    monkeypatch.setattr("backend.services.xhs_client.XHSClient", xhs_client)

    await trending_mod._get_client(account_id="acc-1")

    get_account_cookie.assert_awaited_once_with("acc-1")
    get_active_account.assert_not_called()
    kwargs = xhs_client.call_args.kwargs
    assert kwargs["cookie"] == "a=1; b=2"
    assert kwargs["user_id"] == "user id"


@pytest.mark.asyncio
async def test_get_client_falls_back_to_active_db_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing requested account cookie falls back to the active DB account."""
    active = MagicMock()
    active.id = "active-acc"
    get_account_cookie = AsyncMock(side_effect=[("", ""), ("ACTIVE_COOKIE", "ACTIVE_UID")])
    xhs_client = MagicMock()

    monkeypatch.setattr("backend.config.settings.Settings", lambda: _settings())
    monkeypatch.setattr("backend.db.pool.is_pool_ready", lambda: True)
    monkeypatch.setattr("backend.db.accounts.get_account_cookie", get_account_cookie)
    monkeypatch.setattr("backend.db.accounts.get_active_account", AsyncMock(return_value=active))
    monkeypatch.setattr("backend.services.xhs_client.XHSClient", xhs_client)

    await trending_mod._get_client(account_id="missing-acc")

    assert get_account_cookie.await_args_list[0].args == ("missing-acc",)
    assert get_account_cookie.await_args_list[1].args == ("active-acc",)
    kwargs = xhs_client.call_args.kwargs
    assert kwargs["cookie"] == "ACTIVE_COOKIE"
    assert kwargs["user_id"] == "ACTIVE_UID"


@pytest.mark.asyncio
async def test_get_client_falls_back_to_settings_when_db_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DB-unavailable environments keep the old env-backed behavior."""
    xhs_client = MagicMock()

    monkeypatch.setattr(
        "backend.config.settings.Settings", lambda: _settings("ENV\nCOOKIE", "ENV_UID")
    )
    monkeypatch.setattr("backend.db.pool.is_pool_ready", lambda: False)
    monkeypatch.setattr("backend.services.xhs_client.XHSClient", xhs_client)

    await trending_mod._get_client(account_id="acc-1")

    kwargs = xhs_client.call_args.kwargs
    assert kwargs["cookie"] == "ENV COOKIE"
    assert kwargs["user_id"] == "ENV_UID"


@pytest.mark.asyncio
async def test_xhs_trending_passes_account_id_to_client_resolver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tool schema accepts workflow account_id and passes it to _get_client."""
    client = MagicMock()
    client.get_trending = AsyncMock(
        return_value=[
            XHSTrendingTopic(
                topic_id="t1",
                title="知识管理",
                heat_score=42,
                related_keywords=["AI"],
                category="知识",
            )
        ]
    )
    client.close = AsyncMock()
    get_client = AsyncMock(return_value=client)
    monkeypatch.setattr(trending_mod, "_get_client", get_client)

    result = await trending_mod.xhs_trending.ainvoke({"category": "知识", "account_id": "acc-1"})

    get_client.assert_awaited_once_with(account_id="acc-1")
    assert result[0]["topic"] == "知识管理"
    client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_trend_scout_passes_workflow_account_id_to_xhs_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TrendScoutAgent threads state.account_id through all XHS data tools."""
    xhs_trending = MagicMock()
    xhs_trending.ainvoke = AsyncMock(return_value=[{"topic": "AI效率", "heat_score": 10}])
    keyword_monitor = MagicMock()
    keyword_monitor.ainvoke = AsyncMock(return_value=[])
    competitor_analyzer = MagicMock()
    competitor_analyzer.ainvoke = AsyncMock(return_value=[])

    monkeypatch.setattr(trending_mod, "xhs_trending", xhs_trending)
    monkeypatch.setattr(trending_mod, "keyword_monitor", keyword_monitor)
    monkeypatch.setattr(trending_mod, "competitor_analyzer", competitor_analyzer)

    result = await TrendScoutAgent()._fetch_real_data("知识", account_id="acc-1")

    assert result["hot_topics"] == [{"topic": "AI效率", "heat_score": 10}]
    xhs_trending.ainvoke.assert_awaited_once_with({"category": "知识", "account_id": "acc-1"})
    keyword_monitor.ainvoke.assert_awaited_once_with(
        {"keywords": ["知识", "AI效率"], "account_id": "acc-1"}
    )
    competitor_analyzer.ainvoke.assert_awaited_once_with(
        {
            "account_id": "知识",
            "niche": "知识",
            "credential_account_id": "acc-1",
        }
    )


@pytest.mark.asyncio
async def test_trend_scout_empty_tool_results_remain_no_real_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty XHS tool results should not make the agent label data as real."""
    xhs_trending = MagicMock()
    xhs_trending.ainvoke = AsyncMock(return_value=[])
    keyword_monitor = MagicMock()
    keyword_monitor.ainvoke = AsyncMock(return_value=[])
    competitor_analyzer = MagicMock()
    competitor_analyzer.ainvoke = AsyncMock(return_value=[])

    monkeypatch.setattr(trending_mod, "xhs_trending", xhs_trending)
    monkeypatch.setattr(trending_mod, "keyword_monitor", keyword_monitor)
    monkeypatch.setattr(trending_mod, "competitor_analyzer", competitor_analyzer)

    result = await TrendScoutAgent()._fetch_real_data("知识", account_id="acc-1")

    assert result == {}
