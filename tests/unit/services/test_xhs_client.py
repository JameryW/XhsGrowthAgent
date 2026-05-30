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
        mock_notes = [
            {"note_id": "n1", "display_title": "美食探店", "like_count": 100, "tag_list": ["美食"]},
            {"note_id": "n2", "display_title": "咖啡推荐", "like_count": 50, "tag_list": ["咖啡"]},
        ]
        with patch.object(client._http, "get_homefeed", new_callable=AsyncMock, return_value=mock_notes):
            result = await client.get_trending()

        assert len(result) == 2
        assert result[0].topic_id == "n1"
        assert result[0].title == "美食探店"
        assert result[0].heat_score == 100

    @pytest.mark.asyncio
    async def test_get_trending_rate_limit(self, client):
        """get_trending returns empty list on rate limit (caught by internal handler)."""
        with patch.object(client._http, "get_homefeed", new_callable=AsyncMock, side_effect=XHSRateLimitError("rate limited")):
            result = await client.get_trending()

        assert result == []

    @pytest.mark.asyncio
    async def test_search_posts_success(self, client):
        """search_posts returns search results."""
        mock_notes = [
            {"id": "n1", "display_title": "Test Post", "user": {"nickname": "User", "user_id": "u1"},
             "like_count": 10, "comment_count": 2, "collect_count": 5,
             "cover": {"url": "http://img.jpg"}},
        ]
        with patch.object(client._http, "search_notes", new_callable=AsyncMock, return_value=mock_notes):
            result = await client.search_posts("美食")

        assert len(result) == 1
        assert result[0].note_id == "n1"
        assert result[0].title == "Test Post"
        assert result[0].user_name == "User"

    @pytest.mark.asyncio
    async def test_get_post_analytics_success(self, client):
        """get_post_analytics returns analytics data."""
        mock_detail = {
            "view_count": 1000,
            "like_count": 50,
            "collect_count": 10,
            "comment_count": 8,
            "share_count": 3,
            "engagement_rate": 0.071,
        }
        with patch.object(client._http, "get_note_detail", new_callable=AsyncMock, return_value=mock_detail):
            result = await client.get_post_analytics("post_123")

        assert result.post_id == "post_123"
        assert result.views == 1000
        assert result.likes == 50

    @pytest.mark.asyncio
    async def test_get_comments_success(self, client):
        """get_comments returns comments list."""
        mock_comments = [
            {"id": "c1", "content": "Nice!", "user": {"nickname": "User", "user_id": "u1"},
             "like_count": 5, "create_time": "2026-01-01", "target_comment": {}},
        ]
        with patch.object(client._http, "get_comments", new_callable=AsyncMock, return_value=mock_comments):
            result = await client.get_comments("post_123")

        assert len(result) == 1
        assert result[0].comment_id == "c1"
        assert result[0].content == "Nice!"

    @pytest.mark.asyncio
    async def test_auth_error_on_invalid_cookie(self, client):
        """Auth error when cookie invalid."""
        with patch.object(client._http, "get_note_detail", new_callable=AsyncMock, side_effect=XHSAuthError("认证失败")):
            result = await client.get_post_analytics("post_123")

        # Falls back to empty analytics on error
        assert result.post_id == "post_123"
        assert result.views == 0

    @pytest.mark.asyncio
    async def test_close_client(self, client):
        """Client can be closed."""
        with patch.object(client._http, "close", new_callable=AsyncMock) as mock_close:
            await client.close()

        mock_close.assert_called_once()