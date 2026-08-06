"""Unit tests for backend/services/xhs_api.py — endpoint/header/param builders."""

from __future__ import annotations

from backend.services.xhs_api import XHSApiEndpoints, XHSApiHeaders, XHSApiParams


class TestXHSApiEndpoints:
    """Tests for XHSApiEndpoints constants + full_url."""

    def test_full_url_uses_default_base(self):
        """full_url prepends BASE_URL when no base given."""
        url = XHSApiEndpoints.full_url(XHSApiEndpoints.HOMEFEED)
        assert url == f"{XHSApiEndpoints.BASE_URL}{XHSApiEndpoints.HOMEFEED}"

    def test_full_url_with_custom_base(self):
        """full_url honors explicit base (creator URL)."""
        url = XHSApiEndpoints.full_url("/some/path", base=XHSApiEndpoints.CREATOR_URL)
        assert url == f"{XHSApiEndpoints.CREATOR_URL}/some/path"

    def test_core_endpoint_constants_defined(self):
        """Core endpoint paths exist and are non-empty strings."""
        for attr in (
            "HOMEFEED",
            "CATEGORY_FEED",
            "HOT_TOPIC",
            "SEARCH_NOTE",
            "SEARCH_USER",
            "NOTE_DETAIL",
            "NOTE_STATISTICS",
            "COMMENTS_LIST",
            "COMMENTS_SUB",
            "USER_INFO",
            "USER_NOTES",
            "DM_LIST",
        ):
            value = getattr(XHSApiEndpoints, attr)
            assert isinstance(value, str)
            assert value.startswith("/"), f"{attr} should be a path starting with /"

    def test_base_urls_are_https(self):
        """BASE_URL + CREATOR_URL are https xiaohongshu hosts."""
        assert XHSApiEndpoints.BASE_URL == "https://edith.xiaohongshu.com"
        assert XHSApiEndpoints.CREATOR_URL == "https://creator.xiaohongshu.com"


class TestXHSApiHeaders:
    """Tests for XHSApiHeaders.build."""

    def test_build_without_cookie_has_no_cookie_header(self):
        """build() with no cookie omits Cookie header."""
        headers = XHSApiHeaders.build()
        assert "Cookie" not in headers

    def test_build_with_cookie_sets_cookie(self):
        """build(cookie=...) adds Cookie header."""
        headers = XHSApiHeaders.build(cookie="a1=abc; web_session=xyz")
        assert headers["Cookie"] == "a1=abc; web_session=xyz"

    def test_build_extra_overrides_default(self):
        """extra dict overrides existing headers."""
        custom_ua = "TestAgent/1.0"
        headers = XHSApiHeaders.build(extra={"User-Agent": custom_ua})
        assert headers["User-Agent"] == custom_ua

    def test_build_extra_adds_new_header(self):
        """extra adds headers not in DEFAULT_HEADERS."""
        headers = XHSApiHeaders.build(extra={"X-Custom": "v"})
        assert headers["X-Custom"] == "v"

    def test_build_does_not_mutate_default_headers(self):
        """build returns a copy; DEFAULT_HEADERS unchanged across calls."""
        before = dict(XHSApiHeaders.DEFAULT_HEADERS)
        XHSApiHeaders.build(cookie="a1=x", extra={"X-Custom": "v"})
        after = dict(XHSApiHeaders.DEFAULT_HEADERS)
        assert before == after
        assert "Cookie" not in XHSApiHeaders.DEFAULT_HEADERS
        assert "X-Custom" not in XHSApiHeaders.DEFAULT_HEADERS

    def test_default_headers_has_browser_fingerprint(self):
        """DEFAULT_HEADERS includes UA + sec-ch-ua for browser-like requests."""
        assert "User-Agent" in XHSApiHeaders.DEFAULT_HEADERS
        assert "Chrome" in XHSApiHeaders.DEFAULT_HEADERS["User-Agent"]
        assert "Referer" in XHSApiHeaders.DEFAULT_HEADERS


class TestXHSApiParams:
    """Tests for XHSApiParams static builders."""

    def test_homefeed_params_without_category(self):
        """No category → sort_type=1, search_channel_id empty."""
        params = XHSApiParams.homefeed_params()
        assert params["sort_type"] == 1
        assert params["search_channel_id"] == ""
        assert params["num"] == 40
        assert params["refresh_type"] == 1
        assert params["cursor"] == ""

    def test_homefeed_params_with_category(self):
        """Category present → sort_type=0, channel id set."""
        params = XHSApiParams.homefeed_params(category="母婴")
        assert params["sort_type"] == 0
        assert params["search_channel_id"] == "母婴"

    def test_homefeed_params_cursor_passthrough(self):
        """cursor passed through."""
        params = XHSApiParams.homefeed_params(cursor="abc")
        assert params["cursor"] == "abc"

    def test_search_params_defaults(self):
        """search_params default page=1, page_size=20, sort=general, note_type=0."""
        params = XHSApiParams.search_params(keyword="测试")
        assert params["keyword"] == "测试"
        assert params["page"] == 1
        assert params["page_size"] == 20
        assert params["sort"] == "general"
        assert params["note_type"] == 0

    def test_search_params_sort_override(self):
        """sort_type override propagated to sort field."""
        for sort in ("general", "time_descending", "hot_descending"):
            params = XHSApiParams.search_params(keyword="k", sort_type=sort)
            assert params["sort"] == sort

    def test_search_params_page_passthrough(self):
        """page passed through."""
        params = XHSApiParams.search_params(keyword="k", page=3)
        assert params["page"] == 3

    def test_comments_params(self):
        """comments_params has note_id, cursor, num=20, image_scenes."""
        params = XHSApiParams.comments_params(note_id="note123")
        assert params["note_id"] == "note123"
        assert params["cursor"] == ""
        assert params["num"] == 20
        assert params["image_scenes"] == "CRD,CRD_DT"

    def test_comments_params_cursor_passthrough(self):
        params = XHSApiParams.comments_params(note_id="n", cursor="c1")
        assert params["cursor"] == "c1"

    def test_search_users_params(self):
        """search_users_params has keyword, page, page_size=20."""
        params = XHSApiParams.search_users_params(keyword="用户")
        assert params["keyword"] == "用户"
        assert params["page"] == 1
        assert params["page_size"] == 20

    def test_user_info_params(self):
        """user_info_params is single-field."""
        params = XHSApiParams.user_info_params(user_id="u123")
        assert params == {"user_id": "u123"}

    def test_user_notes_params_defaults(self):
        """user_notes_params default num=30, cursor empty."""
        params = XHSApiParams.user_notes_params(user_id="u1")
        assert params["user_id"] == "u1"
        assert params["cursor"] == ""
        assert params["num"] == 30

    def test_user_notes_params_num_passthrough(self):
        """num override propagated."""
        params = XHSApiParams.user_notes_params(user_id="u1", num=50, cursor="c")
        assert params["num"] == 50
        assert params["cursor"] == "c"
