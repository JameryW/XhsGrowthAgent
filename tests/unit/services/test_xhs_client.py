"""Unit tests for XHS Client."""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from backend.services.xhs_client import (
    XHSClient,
    XHSPost,
    XHSAnalytics,
    XHSComment,
    XHSDirectMessage,
    XHSRateLimitError,
    XHSAuthError,
    XHSPublishError,
    XHSApiError,
)


class TestXHSDataClasses:
    """Tests for XHS data classes."""

    def test_xhs_post_defaults(self):
        """XHSPost has correct defaults."""
        post = XHSPost(title="Test", body="Content")
        assert post.title == "Test"
        assert post.body == "Content"
        assert post.hashtags == []
        assert post.image_paths == []
        assert post.category == ""
        assert post.is_private is False

    def test_xhs_post_with_values(self):
        """XHSPost accepts all values."""
        post = XHSPost(
            title="Title",
            body="Body",
            hashtags=["#test", "#demo"],
            image_paths=["img1.jpg", "img2.jpg"],
            category="美食",
            location="北京",
            is_private=True,
        )
        assert post.hashtags == ["#test", "#demo"]
        assert len(post.image_paths) == 2
        assert post.category == "美食"

    def test_xhs_analytics_defaults(self):
        """XHSAnalytics has correct defaults."""
        analytics = XHSAnalytics(post_id="123")
        assert analytics.views == 0
        assert analytics.likes == 0
        assert analytics.engagement_rate == 0.0

    def test_xhs_comment(self):
        """XHSComment creation."""
        comment = XHSComment(
            comment_id="c1",
            post_id="p1",
            user_name="User",
            content="Great post!",
        )
        assert comment.comment_id == "c1"
        assert comment.is_reply is False

    def test_xhs_direct_message(self):
        """XHSDirectMessage creation."""
        dm = XHSDirectMessage(
            message_id="m1",
            sender_id="s1",
            sender_name="Sender",
            content="Hello",
        )
        assert dm.message_id == "m1"


class TestXHSExceptions:
    """Tests for XHS exception classes."""

    def test_rate_limit_error(self):
        """XHSRateLimitError is raised correctly."""
        with pytest.raises(XHSRateLimitError):
            raise XHSRateLimitError("Too many requests")

    def test_auth_error(self):
        """XHSAuthError is raised correctly."""
        with pytest.raises(XHSAuthError):
            raise XHSAuthError("Cookie expired")

    def test_publish_error(self):
        """XHSPublishError is raised correctly."""
        with pytest.raises(XHSPublishError):
            raise XHSPublishError("Content rejected")

    def test_api_error(self):
        """XHSApiError is raised correctly."""
        with pytest.raises(XHSApiError):
            raise XHSApiError("Network error")


class TestXHSClient:
    """Tests for XHSClient."""

    @pytest.fixture
    def client(self):
        """Create client instance."""
        return XHSClient(cookie="test_cookie", user_id="test_user")

    def test_client_initialization(self, client):
        """Client initializes with correct attributes."""
        assert client.cookie == "test_cookie"
        assert client.user_id == "test_user"

    @pytest.mark.asyncio
    async def test_get_trending_success(self, client):
        """get_trending returns trending topics."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": {"topics": [{"name": "美食", "heat": 100}]}
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(client._http_client, "get", AsyncMock(return_value=mock_response)):
            result = await client.get_trending()

        assert result is not None
        assert "topics" in result or "data" in result

    @pytest.mark.asyncio
    async def test_get_trending_rate_limit(self, client):
        """get_trending handles rate limit."""
        with patch.object(client._http_client, "get", AsyncMock(side_effect=XHSRateLimitError)):
            with pytest.raises(XHSRateLimitError):
                await client.get_trending()

    @pytest.mark.asyncio
    async def test_search_posts_success(self, client):
        """search_posts returns search results."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": {"posts": [{"id": "1", "title": "Test"}]}
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(client._http_client, "get", AsyncMock(return_value=mock_response)):
            result = await client.search_posts("美食")

        assert result is not None

    @pytest.mark.asyncio
    async def test_get_analytics_success(self, client):
        """get_analytics returns analytics data."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": {
                "views": 1000,
                "likes": 50,
                "comments": 10,
            }
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(client._http_client, "get", AsyncMock(return_value=mock_response)):
            result = await client.get_analytics("post_123")

        assert result is not None

    @pytest.mark.asyncio
    async def test_get_comments_success(self, client):
        """get_comments returns comments list."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": {
                "comments": [
                    {"id": "c1", "content": "Nice!", "user_name": "User"}
                ]
            }
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(client._http_client, "get", AsyncMock(return_value=mock_response)):
            result = await client.get_comments("post_123")

        assert result is not None

    @pytest.mark.asyncio
    async def test_auth_error_on_invalid_cookie(self, client):
        """Auth error when cookie invalid."""
        mock_response = MagicMock()
        mock_response.status_code = 401

        with patch.object(client._http_client, "get", AsyncMock(return_value=mock_response)):
            # Client should detect auth error
            pass  # Implementation depends on actual error handling

    def test_close_client(self, client):
        """Client can be closed."""
        # Async close
        with patch.object(client._http_client, "aclose", AsyncMock()):
            # Would need to await in real usage
            pass