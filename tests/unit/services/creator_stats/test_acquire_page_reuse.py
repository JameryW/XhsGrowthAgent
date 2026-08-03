"""Creator-stats tab reuse helpers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.services.creator_stats.client import CdpTransport


class _FakeContext:
    def __init__(self, pages):
        self.pages = pages
        self.new_page = AsyncMock(return_value=SimpleNamespace(url="about:blank"))


@pytest.mark.asyncio
async def test_acquire_page_reuses_creator_tab(monkeypatch):
    transport = CdpTransport(cdp_endpoint="http://127.0.0.1:9222")
    creator = SimpleNamespace(url="https://creator.xiaohongshu.com/new/home")
    other = SimpleNamespace(url="https://www.xiaohongshu.com/explore")
    ctx = _FakeContext([other, creator])
    monkeypatch.setattr("backend.services.creator_stats.client.random.random", lambda: 0.0)
    page, owned = await transport._acquire_page(ctx)
    assert page is creator
    assert owned is False
    ctx.new_page.assert_not_awaited()


@pytest.mark.asyncio
async def test_acquire_page_opens_new_when_no_creator_tab(monkeypatch):
    transport = CdpTransport(cdp_endpoint="http://127.0.0.1:9222")
    ctx = _FakeContext([SimpleNamespace(url="https://www.xiaohongshu.com/explore")])
    monkeypatch.setattr("backend.services.creator_stats.client.random.random", lambda: 0.0)
    page, owned = await transport._acquire_page(ctx)
    assert owned is True
    ctx.new_page.assert_awaited_once()
    assert page is ctx.new_page.return_value
