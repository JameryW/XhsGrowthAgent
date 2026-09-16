"""Failure-contract tests for the three xhs read tools (P1c-S3d).

These tools stopped normalising their own failures. They used to answer every
exception with ``[]``, which made three different situations the same value —
the platform had nothing, the request failed, and we could not ask at all — and
left the Gateway recording a *successful* call. Normalisation belongs to the
Gateway (which turns a raised exception into ``ToolResult(ok=False)``), so the
only thing these tests pin is: an unreadable platform raises, and a readable one
reports what it saw.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.xhs_client import (
    XHSAuthError,
    XHSSearchResult,
    XHSTrendingTopic,
)
from backend.tools.xhs.trending import competitor_analyzer, keyword_monitor, xhs_trending


def _client(*, can_read: bool) -> MagicMock:
    """A client double whose read surface matches ``XHSClient``'s.

    ``can_read`` is set explicitly rather than derived, because it *is* the
    precondition under test — the real property reads ``self._http``, and a
    ``MagicMock`` has no such plumbing to read.
    """
    client = MagicMock()
    client.can_read = can_read
    client.close = AsyncMock()
    client.get_trending = AsyncMock(return_value=[])
    client.search_posts = AsyncMock(return_value=[])
    client.monitor_keywords = AsyncMock(return_value=[])
    return client


def _patch_client(client: MagicMock):
    return patch("backend.tools.xhs.trending._get_client", new=AsyncMock(return_value=client))


class TestUnreadablePlatform:
    """A missing credential is a failure, not an empty platform."""

    @pytest.mark.asyncio
    async def test_trending_refuses_to_report_an_empty_platform(self):
        with _patch_client(_client(can_read=False)), pytest.raises(XHSAuthError, match="未配置"):
            await xhs_trending.ainvoke({"category": "母婴", "account_id": "acc"})

    @pytest.mark.asyncio
    async def test_competitor_analysis_refuses_too(self):
        with _patch_client(_client(can_read=False)), pytest.raises(XHSAuthError):
            await competitor_analyzer.ainvoke(
                {"account_id": "母婴", "niche": "母婴", "credential_account_id": "acc"}
            )

    @pytest.mark.asyncio
    async def test_keyword_monitor_no_longer_fabricates_zero_rows(self):
        """The worst of the three: ``XHSClient.monitor_keywords`` builds one row
        per keyword out of zero counts, so an unauthenticated workflow was handed
        "N rows" and reported ``data_source="real"`` to the model. It must raise
        instead of inventing evidence."""
        client = _client(can_read=False)
        with _patch_client(client), pytest.raises(XHSAuthError):
            await keyword_monitor.ainvoke({"keywords": ["母婴", "露营"], "account_id": "acc"})
        client.monitor_keywords.assert_not_awaited()


class TestReadablePlatform:
    """With a credential, the tools report what they saw — including nothing."""

    @pytest.mark.asyncio
    async def test_trending_maps_topics(self):
        client = _client(can_read=True)
        client.get_trending = AsyncMock(
            return_value=[
                XHSTrendingTopic(
                    topic_id="t1",
                    title="露营亲子",
                    heat_score=88,
                    related_keywords=["露营", "亲子", "户外", "帐篷", "周末"],
                )
            ]
        )
        with _patch_client(client):
            rows = await xhs_trending.ainvoke({"category": "母婴", "account_id": "acc"})

        assert rows == [
            {
                "topic_id": "t1",
                "topic": "露营亲子",
                "heat_score": 88,
                "growth_rate": 0.0,
                "related_keywords": ["露营", "亲子", "户外", "帐篷", "周末"],
                # carried by the topic itself, not copied from the request
                "category": "",
            }
        ]

    @pytest.mark.asyncio
    async def test_an_empty_platform_is_still_empty(self):
        """The distinction the credential guard buys: this ``[]`` means the
        platform was asked and had nothing, not that we never reached it."""
        with _patch_client(_client(can_read=True)):
            assert await xhs_trending.ainvoke({"category": "母婴", "account_id": "acc"}) == []

    @pytest.mark.asyncio
    async def test_competitor_analysis_summarises_posts(self):
        client = _client(can_read=True)
        client.search_posts = AsyncMock(
            return_value=[
                XHSSearchResult(
                    note_id="n1",
                    title="标题",
                    user_name="u",
                    user_id="u1",
                    likes=10,
                    comments=2,
                    collects=3,
                    note_url="https://www.xiaohongshu.com/explore/n1",
                )
            ]
        )
        with _patch_client(client):
            rows = await competitor_analyzer.ainvoke(
                {"account_id": "母婴", "niche": "母婴", "credential_account_id": "acc"}
            )

        assert rows[0]["post_count"] == 1
        assert rows[0]["avg_likes"] == 10.0
        assert rows[0]["top_posts"][0]["note_id"] == "n1"

    @pytest.mark.asyncio
    async def test_a_transport_failure_is_no_longer_swallowed(self):
        """The Gateway classifies what it is handed. If the tool kept catching
        this, the Gateway would see ``ok=True, value=[]`` and the trace would
        call an unreachable platform a successful empty read."""
        client = _client(can_read=True)
        client.get_trending = AsyncMock(side_effect=ConnectionError("Connection refused"))
        with _patch_client(client), pytest.raises(ConnectionError, match="Connection refused"):
            await xhs_trending.ainvoke({"category": "母婴", "account_id": "acc"})

    @pytest.mark.asyncio
    async def test_the_client_is_closed_even_when_the_read_fails(self):
        client = _client(can_read=True)
        client.get_trending = AsyncMock(side_effect=ConnectionError("boom"))
        with _patch_client(client), pytest.raises(ConnectionError):
            await xhs_trending.ainvoke({"category": "母婴", "account_id": "acc"})
        client.close.assert_awaited_once()


class TestTheFactoryHandsTheCredentialOver:
    """P2a-S5a: every other test in this file replaces ``_get_client`` wholesale.

    That makes this class load-bearing.  A function whose every caller is a
    stand-in has no test of its own — the P2a-S4a lesson — and the thing that
    had no test is exactly the hole P1c left open: *which account's cookie,
    sourced from where*.  These tests call the real factory and read what it
    hands the client, so the resolution cannot be quietly unwired.
    """

    COOKIE = "a1=" + "0" * 20 + "; web_session=session"

    @pytest.mark.asyncio
    async def test_a_resolved_credential_reaches_the_client(self, monkeypatch):
        from backend.services.xhs_credentials import XhsCredential
        from backend.tools.xhs import trending

        seen: dict[str, object] = {}

        class _Client:
            def __init__(self, **kwargs: object) -> None:
                seen.update(kwargs)

        async def _credential(account_id: str) -> XhsCredential:
            return XhsCredential(
                account_id=account_id, cookie=self.COOKIE, user_id="u1", source="account"
            )

        monkeypatch.setattr("backend.services.xhs_client.XHSClient", _Client)
        monkeypatch.setattr("backend.services.xhs_credentials.load_credential", _credential)

        await trending._get_client("acc-1")  # noqa: SLF001

        assert seen["cookie"] == self.COOKIE
        assert seen["user_id"] == "u1"

    @pytest.mark.asyncio
    async def test_an_uncredentialed_account_gets_a_client_that_cannot_read(self, monkeypatch):
        """The guard below is only honest if the factory really passes nothing.

        Real ``XHSClient``, real guard: no credential in, ``can_read`` false out,
        and the read refuses.  An empty cookie that still looked readable would
        put the platform back in the state this whole path exists to avoid —
        "asked and had nothing" reported for "never reached it".
        """
        from backend.services.xhs_credentials import XhsCredential
        from backend.tools.xhs import trending

        async def _none(account_id: str) -> XhsCredential:
            return XhsCredential(account_id=account_id)

        monkeypatch.setattr("backend.services.xhs_credentials.load_credential", _none)

        client = await trending._get_client("acc-1")  # noqa: SLF001

        assert client.can_read is False
        with pytest.raises(XHSAuthError, match="未配置"):
            trending._require_readable(client, "xhs_trending")  # noqa: SLF001
