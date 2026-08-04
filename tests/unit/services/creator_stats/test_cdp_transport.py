"""CDP browser-page transport tests for creator stats.

Creator Center signs requests in its own page JavaScript.  These tests stub
the native-page capture boundary so they never need a real Chrome, while
covering the production contract: no copied Cookie/signature headers and the
actual Note Manager response shape is normalized into note stats.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.creator_stats import client as client_module
from backend.services.creator_stats.client import (
    ACCOUNT_OVERVIEW_PATH,
    CREATOR_HOME_PAGE,
    CREATOR_NOTE_MANAGER_PAGE,
    CREATOR_PROFILE_PATH,
    CREATOR_STATS_PAGE,
    NOTE_AUDIENCE_PROFILE_PATH,
    NOTE_AUDIENCE_SOURCE_PATH,
    NOTE_AUDIENCE_TREND_PATH,
    NOTE_BASE_PATH,
    NOTE_DETAIL_PAGE,
    NOTE_LIST_PATH,
    CdpTransport,
    CreatorStatsClient,
)

pytestmark = pytest.mark.asyncio


def _native_account() -> dict:
    return {
        "code": 0,
        "success": True,
        "data": {
            "seven": {"view_count": 7, "like_count": 2, "publish_note_num": 1},
            "thirty": {"view_count": 30, "like_count": 8, "publish_note_num": 2},
        },
    }


def _native_note() -> dict:
    return {
        "id": "note-1",
        "display_title": "真实笔记",
        "view_count": 100,
        "likes": 11,
        "comments_count": 2,
        "collected_count": 3,
        "shared_count": 4,
        "time": "2026-07-13 10:00",
        "type": "normal",
        "images_list": [{"url": "https://img.example/cover.jpg"}],
    }


def _native_profile() -> dict:
    return {
        "code": 0,
        "success": True,
        "data": {
            "userId": "creator-1",
            "userName": "真实创作者",
            "redId": "creator_red",
            "userAvatar": "https://img.example/avatar.jpg",
            "userDesc": "真实创作者简介",
            "role": "creator",
            "zone": "上海",
            "phone": "must-not-be-persisted",
        },
    }


async def test_cdp_fetch_all_uses_native_creator_page_data():
    """CDP uses the page-captured payload, not a copied Cookie header/API call."""
    transport = CdpTransport("http://127.0.0.1:9222")
    transport.fetch_creator_center = AsyncMock(
        return_value=(_native_account(), _native_profile(), [_native_note()])
    )
    client = CreatorStatsClient(cookie="must-not-be-used", transport=transport)

    bundle = await client.fetch_all("acct", period="30d", max_pages=3)

    transport.fetch_creator_center.assert_awaited_once_with(max_pages=3, period="30d")
    assert bundle.account.views == 30
    assert bundle.account.likes == 8
    # note_count is deliberately overridden to len(notes) — the overview's
    # publish_note_num is known to be inflated vs the Note Manager list.
    assert bundle.account.note_count == 1
    assert bundle.account.creator_user_id == "creator-1"
    assert bundle.account.creator_name == "真实创作者"
    assert bundle.account.red_id == "creator_red"
    assert bundle.account.avatar_url == "https://img.example/avatar.jpg"
    assert bundle.account.bio == "真实创作者简介"
    assert bundle.account.creator_role == "creator"
    assert bundle.account.zone == "上海"
    assert "phone" not in bundle.account.to_dict()
    assert len(bundle.notes) == 1
    note = bundle.notes[0]
    assert (note.comments, note.collects, note.shares) == (2, 3, 4)
    assert note.cover_url == "https://img.example/cover.jpg"


async def test_cdp_fetch_all_forwards_requested_period():
    transport = CdpTransport("http://127.0.0.1:9222")
    transport.fetch_creator_center = AsyncMock(
        return_value=(_native_account(), _native_profile(), [_native_note()])
    )
    client = CreatorStatsClient(transport=transport)

    await client.fetch_all("acct", period="7d", max_pages=2)

    transport.fetch_creator_center.assert_awaited_once_with(max_pages=2, period="7d")


async def test_cdp_capture_associates_camel_case_note_id_with_profile_responses():
    """Detail API requests using noteId must enrich the matching note."""

    class FakePage:
        def __init__(self) -> None:
            self._response_handler = None

        def on(self, event: str, handler) -> None:
            assert event == "response"
            self._response_handler = handler

        def remove_listener(self, event: str, handler) -> None:
            assert event == "response"
            assert handler is self._response_handler

        async def _emit(self, path: str, body: dict, *, query: str = "") -> None:
            response = SimpleNamespace(
                url=f"https://creator.xiaohongshu.com{path}{query}",
                status=200,
                json=AsyncMock(return_value=body),
            )
            assert self._response_handler is not None
            self._response_handler(response)
            await asyncio.sleep(0)

        async def goto(self, url: str, **_kwargs) -> None:
            if url == CREATOR_STATS_PAGE:
                await self._emit(ACCOUNT_OVERVIEW_PATH, _native_account())
                await self._emit(CREATOR_PROFILE_PATH, _native_profile())
            elif url == CREATOR_NOTE_MANAGER_PAGE:
                await self._emit(NOTE_LIST_PATH, {"data": {"notes": [_native_note()]}})
            else:
                query = "?noteId=note-1"
                await self._emit(NOTE_BASE_PATH, {"data": {"view_count": 100}}, query=query)
                await self._emit(
                    NOTE_AUDIENCE_SOURCE_PATH,
                    {"data": {"source": [{"title": "首页推荐", "value": 48}]}},
                    query=query,
                )
                await self._emit(
                    NOTE_AUDIENCE_PROFILE_PATH,
                    {"data": {"gender": [{"title": "女性", "value": 48}]}},
                    query=query,
                )
                await self._emit(
                    NOTE_AUDIENCE_TREND_PATH,
                    {"data": {"trend_list": [{"title": "10-11点", "value": 22}]}},
                    query=query,
                )

        def get_by_text(self, _text: str, **_kwargs):
            return self

        async def click(self, **_kwargs) -> None:
            await self.goto(CREATOR_NOTE_MANAGER_PAGE)

        def locator(self, _selector: str):
            return self

        async def evaluate(self, _script: str) -> str:
            return ""

        async def wait_for_timeout(self, _ms: int) -> None:
            return None

        async def close(self) -> None:
            return None

    class FakeContext:
        async def new_page(self) -> FakePage:
            return FakePage()

    class FakeBrowser:
        contexts = [FakeContext()]

    transport = CdpTransport("http://127.0.0.1:9222", timeout=0.05, request_delay=(0, 0))
    transport._ensure_browser = AsyncMock(return_value=FakeBrowser())
    transport._session_wind_down = (0.0, 0.0)
    account, _profile, notes = await transport.fetch_creator_center(max_pages=1)

    assert account["_creator_insights"]["audience_source"] == {}
    assert len(notes) == 1
    assert notes[0]["audience_profile"] == [{"dimension": "gender", "title": "女性", "value": 48}]
    assert notes[0]["view_sources"] == [{"title": "首页推荐", "value": 48}]


async def test_cdp_get_adapts_native_data_without_forwarding_headers():
    transport = CdpTransport("http://127.0.0.1:9222")
    transport.fetch_creator_center = AsyncMock(
        return_value=(_native_account(), _native_profile(), [_native_note()])
    )

    status, account = await transport.get(
        f"https://creator.xiaohongshu.com{ACCOUNT_OVERVIEW_PATH}",
        headers={"Cookie": "must-not-be-forwarded", "x-s": "stale"},
        params={"date_type": 2},
    )
    assert status == 200
    assert account == _native_account()

    status, profile = await transport.get(
        f"https://creator.xiaohongshu.com{CREATOR_PROFILE_PATH}",
        headers={"Cookie": "must-not-be-forwarded"},
    )
    assert status == 200
    assert profile == _native_profile()

    status, notes = await transport.get(
        f"https://creator.xiaohongshu.com{NOTE_LIST_PATH}",
        headers={"Cookie": "must-not-be-forwarded"},
        params={"page": 0},
    )
    assert status == 200
    assert notes == {"data": {"notes": [_native_note()]}}
    assert transport.fetch_creator_center.await_count == 3


async def test_cdp_transport_aclose_clears_state():
    transport = CdpTransport("http://127.0.0.1:9222")
    browser = MagicMock()
    browser.close = AsyncMock()
    playwright = MagicMock()
    playwright.stop = AsyncMock()
    transport._browser = browser
    transport._playwright = playwright

    await transport.aclose()

    browser.close.assert_awaited_once()
    playwright.stop.assert_awaited_once()
    assert transport._browser is None
    assert transport._playwright is None
    # Idempotent — safe to call when nothing is connected.
    await transport.aclose()


async def test_cdp_fetch_fails_fast_on_login_page():
    """Expired creator sessions must not wait the full capture timeout."""
    from backend.services.creator_stats.client import CreatorStatsFetchError

    class LoginPage:
        url = "https://creator.xiaohongshu.com/login"

        def on(self, event: str, handler) -> None:
            return None

        def remove_listener(self, event: str, handler) -> None:
            return None

        async def goto(self, url: str, **_kwargs) -> None:
            self.url = "https://creator.xiaohongshu.com/login"

        def get_by_text(self, _text: str, **_kwargs):
            return self

        async def click(self, **_kwargs) -> None:
            raise TimeoutError("no menu on login shell")

        async def evaluate(self, _script: str) -> str:
            return "短信登录\n发送验证码\n登录即同意\n用户协议"

        async def wait_for_timeout(self, _ms: int) -> None:
            return None

        async def close(self) -> None:
            return None

    class FakeContext:
        async def new_page(self) -> LoginPage:
            return LoginPage()

    class FakeBrowser:
        contexts = [FakeContext()]

    transport = CdpTransport("http://127.0.0.1:9222", timeout=30)
    transport._ensure_browser = AsyncMock(return_value=FakeBrowser())

    with pytest.raises(CreatorStatsFetchError) as exc:
        await transport.fetch_creator_center(max_pages=1)

    assert exc.value.status_code == 401
    assert "login" in str(exc.value).lower()


async def test_cdp_fetch_fails_on_profile_401_instead_of_generic_timeout():
    from backend.services.creator_stats.client import CreatorStatsFetchError

    class AuthFailPage:
        url = CREATOR_STATS_PAGE

        def __init__(self) -> None:
            self._response_handler = None

        def on(self, event: str, handler) -> None:
            self._response_handler = handler

        def remove_listener(self, event: str, handler) -> None:
            return None

        async def _emit(self, path: str, *, status: int = 200, body: dict | None = None) -> None:
            response = SimpleNamespace(
                url=f"https://creator.xiaohongshu.com{path}",
                status=status,
                json=AsyncMock(return_value=body or {}),
            )
            assert self._response_handler is not None
            self._response_handler(response)
            await asyncio.sleep(0)

        async def goto(self, url: str, **_kwargs) -> None:
            self.url = url
            if "statistics" in url:
                await self._emit(CREATOR_PROFILE_PATH, status=401, body={"success": False})
            else:
                await self._emit(CREATOR_PROFILE_PATH, status=401, body={"success": False})

        def get_by_text(self, _text: str, **_kwargs):
            return self

        async def click(self, **_kwargs) -> None:
            await self.goto(CREATOR_NOTE_MANAGER_PAGE)

        async def evaluate(self, _script: str) -> str:
            return "创作服务平台"

        async def wait_for_timeout(self, _ms: int) -> None:
            return None

        async def close(self) -> None:
            return None

    class FakeContext:
        async def new_page(self) -> AuthFailPage:
            return AuthFailPage()

    class FakeBrowser:
        contexts = [FakeContext()]

    transport = CdpTransport("http://127.0.0.1:9222", timeout=0.5)
    transport._ensure_browser = AsyncMock(return_value=FakeBrowser())

    with pytest.raises(CreatorStatsFetchError) as exc:
        await transport.fetch_creator_center(max_pages=1)

    assert exc.value.status_code == 401
    assert "auth failed" in str(exc.value).lower() or "login" in str(exc.value).lower()


async def test_client_aclose_safe_for_transport_without_aclose():
    """Back-compat: test-only transports may predate ``aclose``."""

    class _NoCloseTransport:
        async def get(self, url, *, headers, params=None):
            return 200, {}

    client = CreatorStatsClient(transport=_NoCloseTransport())
    await client.aclose()


# ── Incremental sync: filters, pacing, circuit breakers ─────────────────────


def _numbered_note(index: int) -> dict:
    return {**_native_note(), "id": f"note-{index}", "display_title": f"笔记{index}"}


class _FakeNotesPage:
    """Native-page stub serving ``note_count`` posted notes plus detail APIs."""

    def __init__(self, note_count: int = 2) -> None:
        self._response_handler = None
        self._notes = [_numbered_note(i + 1) for i in range(note_count)]
        self.detail_urls: list[str] = []
        self.body_urls: list[str] = []
        self.visited: list[str] = []
        self.requested_texts: list[str] = []

    def on(self, event: str, handler) -> None:
        assert event == "response"
        self._response_handler = handler

    def remove_listener(self, event: str, handler) -> None:
        assert event == "response"
        assert handler is self._response_handler

    async def _emit(self, path: str, body: dict, *, query: str = "") -> None:
        response = SimpleNamespace(
            url=f"https://creator.xiaohongshu.com{path}{query}",
            status=200,
            json=AsyncMock(return_value=body),
        )
        assert self._response_handler is not None
        self._response_handler(response)
        await asyncio.sleep(0)

    async def goto(self, url: str, **_kwargs) -> None:
        self.visited.append(url)
        if url == CREATOR_STATS_PAGE:
            await self._emit(ACCOUNT_OVERVIEW_PATH, _native_account())
            await self._emit(CREATOR_PROFILE_PATH, _native_profile())
        elif url == CREATOR_NOTE_MANAGER_PAGE:
            await self._emit(NOTE_LIST_PATH, {"data": {"notes": self._notes}})
        elif url.startswith(NOTE_DETAIL_PAGE):
            self.detail_urls.append(url)
            note_id = url.rsplit("noteId=", 1)[1]
            query = f"?noteId={note_id}"
            await self._emit(NOTE_BASE_PATH, {"data": {"view_count": 100}}, query=query)
            await self._emit(
                NOTE_AUDIENCE_SOURCE_PATH,
                {"data": {"source": [{"title": "首页推荐", "value": 48}]}},
                query=query,
            )
        elif "www.xiaohongshu.com/explore/" in url:
            self.body_urls.append(url)

    def get_by_text(self, text: str, **_kwargs):
        self.requested_texts.append(text)
        return self

    async def click(self, **_kwargs) -> None:
        await self.goto(CREATOR_NOTE_MANAGER_PAGE)

    def locator(self, _selector: str):
        return self

    async def evaluate(self, _script: str) -> str:
        return "公开正文内容"

    async def wait_for_timeout(self, _ms: int) -> None:
        return None

    async def close(self) -> None:
        return None


def _transport_with_page(page: _FakeNotesPage) -> CdpTransport:
    class FakeContext:
        async def new_page(self) -> _FakeNotesPage:
            return page

    class FakeBrowser:
        contexts = [FakeContext()]

    # timeout=0.05 bounds _wait_for's end-of-list poll (caught as the normal
    # no-next-page exit) to a few ms instead of the full 1s window — 20+ tests
    # hit this path, so the saved ~0.95s each adds up across the suite.
    transport = CdpTransport("http://127.0.0.1:9222", timeout=0.05, request_delay=(0, 0))
    transport._ensure_browser = AsyncMock(return_value=FakeBrowser())
    # Deliberately mutate the legacy cap: it must not enable public-page visits.
    transport._max_body_visits = 10
    transport._max_detail_visits = 20
    transport._session_wind_down = (0.0, 0.0)
    return transport


async def test_cdp_incremental_filters_skip_unselected_notes():
    """Detail filters still work while the legacy body filter is ignored."""
    page = _FakeNotesPage(note_count=2)
    transport = _transport_with_page(page)

    _account, _profile, notes = await transport.fetch_creator_center(
        max_pages=1,
        detail_filter=lambda note: str(note.get("id")) == "note-1",
        body_filter=lambda note: str(note.get("id")) == "note-2",
    )

    assert [url.rsplit("noteId=", 1)[1] for url in page.detail_urls] == ["note-1"]
    assert page.body_urls == []
    assert len(notes) == 2


async def test_cdp_paces_between_note_visits_but_not_before_first():
    page = _FakeNotesPage(note_count=2)
    transport = _transport_with_page(page)
    transport._light_run_chance = 0.0
    transport._enrich_skip_chance = 0.0
    transport._pace = AsyncMock()

    await transport.fetch_creator_center(max_pages=1)

    # Two Creator Center detail visits; the first visit is unpaced.
    assert transport._pace.await_count == 1


async def test_cdp_detail_circuit_breaks_after_three_consecutive_failures():
    class FailingDetailPage(_FakeNotesPage):
        async def goto(self, url: str, **kwargs) -> None:
            if url.startswith(NOTE_DETAIL_PAGE):
                self.detail_urls.append(url)
                raise RuntimeError("risk control interstitial")
            await super().goto(url, **kwargs)

    page = FailingDetailPage(note_count=5)
    transport = _transport_with_page(page)
    transport._light_run_chance = 0.0
    transport._enrich_skip_chance = 0.0

    await transport.fetch_creator_center(max_pages=1, body_filter=lambda _note: False)

    # Default detail circuit is 2 consecutive failures under risk-safe defaults.
    assert len(page.detail_urls) == transport._detail_circuit_failures


async def test_cdp_fetch_all_forwards_optional_filters():
    transport = CdpTransport("http://127.0.0.1:9222")
    transport.fetch_creator_center = AsyncMock(
        return_value=(_native_account(), _native_profile(), [_native_note()])
    )
    client = CreatorStatsClient(transport=transport)

    def detail_filter(_note: dict) -> bool:
        return True

    def body_filter(_note: dict) -> bool:
        return False

    await client.fetch_all("acct", detail_filter=detail_filter, body_filter=body_filter)

    transport.fetch_creator_center.assert_awaited_once_with(
        max_pages=transport._max_list_pages,
        period="30d",
        detail_filter=detail_filter,
        body_filter=body_filter,
    )


async def test_cdp_fetch_all_forwards_force_light():
    transport = CdpTransport("http://127.0.0.1:9222")
    transport.fetch_creator_center = AsyncMock(
        return_value=(_native_account(), _native_profile(), [_native_note()])
    )
    client = CreatorStatsClient(transport=transport)

    await client.fetch_all("acct", force_light=True)

    transport.fetch_creator_center.assert_awaited_once_with(
        max_pages=transport._max_list_pages,
        period="30d",
        force_light=True,
    )


async def test_cdp_legacy_body_cap_cannot_enable_public_page_browsing(monkeypatch):
    """Positive legacy caps and filters never navigate to public note pages."""
    monkeypatch.setenv("CREATOR_STATS_LIGHT_RUN_CHANCE", "0")
    monkeypatch.setenv("CREATOR_STATS_ENRICH_SKIP_CHANCE", "0")
    monkeypatch.setenv("CREATOR_STATS_MAX_DETAIL_VISITS", "2")
    monkeypatch.setenv("CREATOR_STATS_MAX_BODY_VISITS", "20")
    page = _FakeNotesPage(note_count=8)
    transport = _transport_with_page(page)
    transport._max_detail_visits = 2
    transport._max_body_visits = 50

    await transport.fetch_creator_center(max_pages=1, body_filter=lambda _note: True)

    assert len(page.detail_urls) <= 2
    assert page.body_urls == []
    assert all("www.xiaohongshu.com/explore/" not in url for url in page.visited)
    assert not hasattr(transport, "_scrape_public_note_body")


async def test_cdp_preserves_body_text_from_creator_center_payload():
    """A caption supplied by Creator Center is kept without public navigation."""
    page = _FakeNotesPage(note_count=1)
    page._notes[0]["body_text"] = "创作者中心已有正文"
    transport = _transport_with_page(page)

    _account, _profile, notes = await transport.fetch_creator_center(
        max_pages=1,
        force_light=True,
    )

    assert notes[0]["body_text"] == "创作者中心已有正文"
    assert page.body_urls == []


async def test_cdp_nonfinite_env_values_fall_back_to_safe_defaults(monkeypatch):
    monkeypatch.setenv("CREATOR_STATS_LIGHT_RUN_CHANCE", "nan")
    monkeypatch.setenv("CREATOR_STATS_REQUEST_DELAY_MIN_S", "inf")
    monkeypatch.setenv("CREATOR_STATS_MAX_LIST_PAGES", "nan")
    monkeypatch.setenv("CREATOR_STATS_MAX_DETAIL_VISITS", "inf")
    monkeypatch.setenv("CREATOR_STATS_MAX_BODY_VISITS", "nan")

    transport = CdpTransport("http://127.0.0.1:9222")

    assert transport._light_run_chance == 0.35
    assert transport._request_delay == (3.5, 10.0)
    assert transport._max_list_pages == 5
    assert transport._max_detail_visits == 4
    assert transport._max_body_visits == 0


async def test_cdp_safe_mode_clamps_public_body_and_crawl_budgets(monkeypatch):
    """Production safe mode tightens Creator Center crawl caps."""
    monkeypatch.setenv("CREATOR_STATS_SAFE_MODE", "1")
    monkeypatch.setenv("CREATOR_STATS_LIGHT_RUN_CHANCE", "0")
    monkeypatch.setenv("CREATOR_STATS_ENRICH_SKIP_CHANCE", "0")
    monkeypatch.setenv("CREATOR_STATS_MAX_LIST_PAGES", "20")
    monkeypatch.setenv("CREATOR_STATS_MAX_DETAIL_VISITS", "20")
    monkeypatch.setenv("CREATOR_STATS_MAX_BODY_VISITS", "20")

    transport = CdpTransport("http://127.0.0.1:9222")

    assert transport._max_list_pages == 3
    assert transport._max_detail_visits == 2
    assert transport._max_body_visits == 0
    assert transport._light_run_chance >= 0.75
    assert transport._enrich_skip_chance >= 0.55


# ── 反风控节奏：乱序访问 / 翻页节奏 / 偶发长停顿 ──


async def test_pace_inserts_long_pause_when_chance_hits(monkeypatch):
    """长停顿概率命中时，_pace 睡长停顿区间而不是短停顿区间。"""
    transport = CdpTransport("http://127.0.0.1:9222", request_delay=(1.0, 2.0))
    monkeypatch.setattr(transport, "_long_pause_chance", 1.0)
    monkeypatch.setattr(transport, "_long_pause", (15.0, 45.0))
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(client_module.asyncio, "sleep", fake_sleep)

    await transport._pace()

    assert len(sleeps) == 1
    assert 15.0 <= sleeps[0] <= 45.0


async def test_pace_short_pause_when_chance_misses(monkeypatch):
    """长停顿概率未命中时，_pace 保持常规短停顿。"""
    transport = CdpTransport("http://127.0.0.1:9222", request_delay=(1.0, 2.0))
    monkeypatch.setattr(transport, "_long_pause_chance", 0.0)
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(client_module.asyncio, "sleep", fake_sleep)

    await transport._pace()

    assert len(sleeps) == 1
    assert 1.0 <= sleeps[0] <= 2.0


async def test_cdp_detail_visits_follow_shuffled_order(monkeypatch):
    """详情页访问顺序由 shuffle 决定，不再是固定的列表顺序。"""
    page = _FakeNotesPage(note_count=4)
    transport = _transport_with_page(page)
    # 确定性 shuffle：反转，便于断言顺序确实来自 shuffle。
    monkeypatch.setattr(client_module.random, "shuffle", lambda items: items.reverse())

    await transport.fetch_creator_center(max_pages=1, body_filter=lambda _note: False)

    ids = [url.rsplit("noteId=", 1)[1] for url in page.detail_urls]
    assert ids == ["note-4", "note-3", "note-2", "note-1"]


async def test_cdp_paces_between_list_page_turns(monkeypatch):
    """列表翻页也经过 _pace——连续秒翻是机器特征。"""
    # Disable per-run list-depth jitter (random.randint(1, max_pages)) so the
    # pagination count is deterministic; this test is about _pace wiring, not
    # the anti-fingerprint jitter.
    monkeypatch.setattr(client_module.random, "randint", lambda a, b: b)
    page = _FakeNotesPage(note_count=2)
    transport = _transport_with_page(page)
    transport._pace = AsyncMock()

    await transport.fetch_creator_center(max_pages=2)

    # 1 次翻页（第 2 页不存在，等待超时后正常结束）+ 1 次详情。
    assert transport._pace.await_count == 2


async def test_new_run_pace_scales_delay_per_run():
    """每轮抓取的节奏基准在配置区间的 0.7-1.6 倍间随机缩放。"""
    transport = CdpTransport("http://127.0.0.1:9222", request_delay=(2.0, 6.0))

    transport._new_run_pace()

    assert transport._run_delay is not None
    lo, hi = transport._run_delay
    assert 2.0 * 0.7 <= lo <= 2.0 * 1.6
    assert 6.0 * 0.7 <= hi <= 6.0 * 1.6
    assert lo <= hi


async def test_pace_uses_run_delay_baseline(monkeypatch):
    """_pace 使用本轮节奏基准（_run_delay）而不是全局配置区间。"""
    transport = CdpTransport("http://127.0.0.1:9222", request_delay=(2.0, 6.0))
    transport._run_delay = (5.0, 5.0)
    monkeypatch.setattr(transport, "_long_pause_chance", 0.0)
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(client_module.asyncio, "sleep", fake_sleep)

    await transport._pace()

    assert sleeps == [5.0]


async def test_cdp_light_run_skips_per_note_enrichment(monkeypatch):
    """轻量轮（light run）：只看概览+列表，不访问笔记详情页。"""
    monkeypatch.setenv("CREATOR_STATS_LIGHT_RUN_CHANCE", "1")
    page = _FakeNotesPage(note_count=3)
    transport = _transport_with_page(page)

    _account, _profile, notes = await transport.fetch_creator_center(max_pages=1)

    assert page.detail_urls == []
    assert page.body_urls == []
    assert len(notes) == 3
    assert all("audience_source" not in note for note in notes)


async def test_cdp_enrich_skip_chance_one_visits_no_note_pages(monkeypatch):
    """逐篇跳过概率为 1 时，深入轮也不访问任何详情页。"""
    monkeypatch.setenv("CREATOR_STATS_ENRICH_SKIP_CHANCE", "1")
    page = _FakeNotesPage(note_count=3)
    transport = _transport_with_page(page)

    _account, _profile, notes = await transport.fetch_creator_center(max_pages=1)

    assert page.detail_urls == []
    assert page.body_urls == []
    assert len(notes) == 3


async def test_cdp_force_light_skips_enrichment_even_when_run_is_configured_deep():
    """Scheduled force-light mode wins over random/deep enrichment settings."""
    page = _FakeNotesPage(note_count=3)
    transport = _transport_with_page(page)
    transport._light_run_chance = 0.0
    transport._enrich_skip_chance = 0.0

    _account, _profile, notes = await transport.fetch_creator_center(
        max_pages=1,
        force_light=True,
    )

    assert page.detail_urls == []
    assert page.body_urls == []
    assert len(notes) == 3


async def test_cdp_human_touch_moves_mouse_when_available():
    """页面带鼠标能力时，抓取过程会产生随机鼠标轨迹（避免幽灵浏览特征）。"""
    page = _FakeNotesPage(note_count=1)
    page.mouse = SimpleNamespace(move=AsyncMock())
    transport = _transport_with_page(page)

    await transport.fetch_creator_center(max_pages=1, body_filter=lambda _note: False)

    assert page.mouse.move.await_count >= 1


async def test_cdp_human_touch_tolerates_pages_without_mouse():
    """无鼠标能力的页面（测试替身）不应导致抓取失败。"""
    page = _FakeNotesPage(note_count=1)
    transport = _transport_with_page(page)

    _account, _profile, notes = await transport.fetch_creator_center(
        max_pages=1, body_filter=lambda _note: False
    )

    assert len(notes) == 1


async def test_cdp_home_entry_visits_creator_home_before_stats(monkeypatch):
    """入口随机化命中时，会话从创作者主页开始，而不是直接深链数据页。"""
    monkeypatch.setenv("CREATOR_STATS_HOME_ENTRY_CHANCE", "1")
    page = _FakeNotesPage(note_count=1)
    transport = _transport_with_page(page)

    await transport.fetch_creator_center(max_pages=1, body_filter=lambda _note: False)

    assert page.visited[0] == CREATOR_HOME_PAGE
    assert CREATOR_STATS_PAGE in page.visited


async def test_cdp_home_entry_disabled_goes_straight_to_stats(monkeypatch):
    """入口随机化关闭时，仍直接打开数据统计页（原行为）。"""
    monkeypatch.setenv("CREATOR_STATS_HOME_ENTRY_CHANCE", "0")
    page = _FakeNotesPage(note_count=1)
    transport = _transport_with_page(page)

    await transport.fetch_creator_center(max_pages=1, body_filter=lambda _note: False)

    assert page.visited[0] == CREATOR_STATS_PAGE


async def test_cdp_page_stop_chance_one_skips_pagination(monkeypatch):
    """翻页提前停止概率为 1 时，不再翻页（_pace 不会因翻页被调用）。"""
    monkeypatch.setenv("CREATOR_STATS_PAGE_STOP_CHANCE", "1")
    page = _FakeNotesPage(note_count=2)
    transport = _transport_with_page(page)
    transport._pace = AsyncMock()

    _account, _profile, notes = await transport.fetch_creator_center(
        max_pages=3,
        detail_filter=lambda _note: False,
        body_filter=lambda _note: False,
    )

    transport._pace.assert_not_awaited()
    assert len(notes) == 2


async def test_cdp_pagination_still_works_when_stop_disabled(monkeypatch):
    """翻页提前停止关闭时，保持原有翻页行为（回归保护）。"""
    monkeypatch.setenv("CREATOR_STATS_PAGE_STOP_CHANCE", "0")
    # Disable per-run list-depth jitter so pagination actually runs (jitter
    # rolls 1..max_pages and would skip the page turn half the time).
    monkeypatch.setattr(client_module.random, "randint", lambda a, b: b)
    page = _FakeNotesPage(note_count=2)
    transport = _transport_with_page(page)
    transport._pace = AsyncMock()

    await transport.fetch_creator_center(
        max_pages=2,
        detail_filter=lambda _note: False,
        body_filter=lambda _note: False,
    )

    # 1 次翻页尝试（第 2 页不存在，等待超时后正常结束）。
    assert transport._pace.await_count == 1


async def test_cdp_dashboard_browse_clicks_date_tab_when_enabled(monkeypatch):
    """数据页浏览噪声命中时，进笔记管理前会先点一个日期范围 Tab。"""
    monkeypatch.setenv("CREATOR_STATS_DASHBOARD_BROWSE_CHANCE", "1")
    page = _FakeNotesPage(note_count=1)
    transport = _transport_with_page(page)

    await transport.fetch_creator_center(max_pages=1, body_filter=lambda _note: False)

    assert page.requested_texts[0] == "近7天"
    assert "笔记管理" in page.requested_texts


async def test_cdp_dashboard_browse_disabled_by_default(monkeypatch):
    """浏览噪声关闭时，只点"笔记管理"，不碰日期 Tab（原行为）。"""
    page = _FakeNotesPage(note_count=1)
    transport = _transport_with_page(page)

    await transport.fetch_creator_center(max_pages=1, body_filter=lambda _note: False)

    assert page.requested_texts == ["笔记管理"]
