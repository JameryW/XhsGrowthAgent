"""Unit tests for XHSClient blogger methods."""

from unittest.mock import AsyncMock, patch

import pytest

from backend.services.xhs_client import XHSClient, _HTTPClient


class TestHTTPClientBlogger:
    """Tests for _HTTPClient blogger API methods."""

    @pytest.fixture
    def http_client(self):
        """Create _HTTPClient instance."""
        return _HTTPClient(cookie="test_cookie")

    @pytest.mark.asyncio
    async def test_search_users_success(self, http_client):
        """search_users returns user list."""
        mock_data = {"users": [{"user_id": "u1", "nickname": "博主A"}]}
        with patch.object(http_client, "_request", new_callable=AsyncMock, return_value=mock_data):
            result = await http_client.search_users(keyword="美食")

        assert len(result) == 1
        assert result[0]["user_id"] == "u1"

    @pytest.mark.asyncio
    async def test_get_user_info_success(self, http_client):
        """get_user_info returns user info dict."""
        mock_data = {"user_id": "u1", "nickname": "博主A", "follows": 1000, "notes_count": 50}
        with patch.object(http_client, "_request", new_callable=AsyncMock, return_value=mock_data):
            result = await http_client.get_user_info(user_id="u1")

        assert result["user_id"] == "u1"
        assert result["follows"] == 1000

    @pytest.mark.asyncio
    async def test_get_user_notes_success(self, http_client):
        """get_user_notes returns paginated note list."""
        mock_data = {
            "notes": [{"note_id": "n1", "like_count": 10}],
            "cursor": "next_page",
            "has_more": False,
        }
        with patch.object(http_client, "_request", new_callable=AsyncMock, return_value=mock_data):
            result = await http_client.get_user_notes(user_id="u1")

        assert "notes" in result
        assert len(result["notes"]) == 1

    @pytest.mark.asyncio
    async def test_search_users_retries_on_rate_limit(self, http_client):
        """search_users retries on rate limit then succeeds."""
        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                from backend.services.xhs_client import XHSRateLimitError
                raise XHSRateLimitError("rate limited")
            return {"users": [{"user_id": "u1"}]}

        with patch.object(http_client, "_request", new_callable=AsyncMock, side_effect=side_effect):
            result = await http_client.search_users(keyword="美食")

        assert len(result) == 1
        assert call_count == 2


class TestXHSClientBlogger:
    """Tests for XHSClient blogger methods."""

    @pytest.fixture
    def client(self):
        """Create client instance."""
        return XHSClient(cookie="test_cookie", user_id="test_user")

    @pytest.mark.asyncio
    async def test_search_users_success(self, client):
        """search_users returns user list from _HTTPClient."""
        mock_users = [{"user_id": "u1", "nickname": "博主A"}, {"user_id": "u2", "nickname": "博主B"}]
        with patch.object(client._http, "search_users", new_callable=AsyncMock, return_value=mock_users):
            result = await client.search_users(keyword="美食")

        assert len(result) == 2
        assert result[0]["user_id"] == "u1"

    @pytest.mark.asyncio
    async def test_search_users_respects_limit(self, client):
        """search_users respects limit parameter."""
        mock_users = [{"user_id": f"u{i}"} for i in range(20)]
        with patch.object(client._http, "search_users", new_callable=AsyncMock, return_value=mock_users):
            result = await client.search_users(keyword="美食", limit=5)

        assert len(result) == 5

    @pytest.mark.asyncio
    async def test_search_users_no_cookie(self):
        """search_users returns empty list without cookie."""
        client = XHSClient(cookie="", user_id="test")
        result = await client.search_users(keyword="美食")
        assert result == []

    @pytest.mark.asyncio
    async def test_get_user_info_success(self, client):
        """get_user_info returns user info dict."""
        mock_info = {"user_id": "u1", "nickname": "博主A", "follows": 5000}
        with patch.object(client._http, "get_user_info", new_callable=AsyncMock, return_value=mock_info):
            result = await client.get_user_info(user_id="u1")

        assert result["nickname"] == "博主A"
        assert result["follows"] == 5000

    @pytest.mark.asyncio
    async def test_get_user_info_no_cookie(self):
        """get_user_info returns empty dict without cookie."""
        client = XHSClient(cookie="", user_id="test")
        result = await client.get_user_info(user_id="u1")
        assert result == {}

    @pytest.mark.asyncio
    async def test_get_user_notes_success(self, client):
        """get_user_notes returns notes with auto-pagination."""
        mock_data = {
            "notes": [{"note_id": "n1"}, {"note_id": "n2"}],
            "cursor": "",
            "has_more": False,
        }
        with patch.object(client._http, "get_user_notes", new_callable=AsyncMock, return_value=mock_data):
            result = await client.get_user_notes(user_id="u1", limit=20)

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_get_user_notes_auto_paginates(self, client):
        """get_user_notes fetches multiple pages until limit reached."""
        page1 = {
            "notes": [{"note_id": f"n{i}"} for i in range(30)],
            "cursor": "page2",
            "has_more": True,
        }
        page2 = {
            "notes": [{"note_id": f"n{i+30}"} for i in range(10)],
            "cursor": "",
            "has_more": False,
        }

        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return page1
            return page2

        with patch.object(client._http, "get_user_notes", new_callable=AsyncMock, side_effect=side_effect):
            result = await client.get_user_notes(user_id="u1", limit=35)

        assert len(result) == 35
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_get_user_notes_stops_when_no_more(self, client):
        """get_user_notes stops when has_more is False."""
        mock_data = {
            "notes": [{"note_id": "n1"}],
            "cursor": "",
            "has_more": False,
        }
        with patch.object(client._http, "get_user_notes", new_callable=AsyncMock, return_value=mock_data):
            result = await client.get_user_notes(user_id="u1", limit=50)

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_get_user_notes_no_cookie(self):
        """get_user_notes returns empty list without cookie."""
        client = XHSClient(cookie="", user_id="test")
        result = await client.get_user_notes(user_id="u1")
        assert result == []

    @pytest.mark.asyncio
    async def test_search_users_error_returns_empty(self, client):
        """search_users returns empty list on API error."""
        from backend.services.xhs_client import XHSApiError
        with patch.object(client._http, "search_users", new_callable=AsyncMock, side_effect=XHSApiError("fail")):
            result = await client.search_users(keyword="美食")

        assert result == []

    @pytest.mark.asyncio
    async def test_get_user_info_error_returns_empty(self, client):
        """get_user_info returns empty dict on API error."""
        from backend.services.xhs_client import XHSApiError
        with patch.object(client._http, "get_user_info", new_callable=AsyncMock, side_effect=XHSApiError("fail")):
            result = await client.get_user_info(user_id="u1")

        assert result == {}

    @pytest.mark.asyncio
    async def test_get_user_notes_error_returns_empty(self, client):
        """get_user_notes returns empty list on API error."""
        from backend.services.xhs_client import XHSApiError
        with patch.object(client._http, "get_user_notes", new_callable=AsyncMock, side_effect=XHSApiError("fail")):
            result = await client.get_user_notes(user_id="u1")

        assert result == []
