"""Unit tests for Memory Manager."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.memory.store import MemoryManager, _keyword_filter


class TestKeywordFilter:
    """Tests for _keyword_filter helper."""

    def test_no_keywords_returns_all(self):
        """Empty keywords list returns all items unchanged."""
        items = [MagicMock(value={"title": "a"}), MagicMock(value={"title": "b"})]
        assert _keyword_filter(items, []) == items

    def test_none_keywords_returns_all(self):
        """None keywords returns all items unchanged."""
        items = [MagicMock(value={"title": "a"})]
        assert _keyword_filter(items, None) == items

    def test_single_keyword_match(self):
        """Single keyword filters to matching items."""
        i1 = MagicMock(value={"title": "护肤指南", "tone": "治愈"})
        i2 = MagicMock(value={"title": "穿搭分享", "tone": "活泼"})
        result = _keyword_filter([i1, i2], ["护肤"])
        assert len(result) == 1
        assert result[0].value["title"] == "护肤指南"

    def test_multiple_keywords_all_must_match(self):
        """All keywords must appear in item text."""
        i1 = MagicMock(value={"title": "宝宝护肤指南", "category": "母婴"})
        i2 = MagicMock(value={"title": "成人护肤技巧", "category": "美妆"})
        i3 = MagicMock(value={"title": "宝宝穿搭", "category": "母婴"})
        result = _keyword_filter([i1, i2, i3], ["宝宝", "护肤"])
        assert len(result) == 1
        assert result[0].value["title"] == "宝宝护肤指南"

    def test_keyword_matching_is_case_insensitive(self):
        """Keyword matching ignores case."""
        i1 = MagicMock(value={"title": "SKINCARE guide"})
        result = _keyword_filter([i1], ["skincare"])
        assert len(result) == 1

    def test_keyword_matches_numeric_values(self):
        """Keyword matching includes numeric/bool values converted to strings."""
        i1 = MagicMock(value={"title": "test", "count": 42, "active": True})
        result = _keyword_filter([i1], ["42"])
        assert len(result) == 1


class TestMemoryManager:
    """Tests for MemoryManager namespace and storage."""

    @pytest.fixture
    def manager(self):
        """Create manager instance."""
        return MemoryManager(account_id="test_account")

    @pytest.fixture
    def mock_store(self):
        """Mock LangGraph BaseStore."""
        store = AsyncMock()
        store.aput = AsyncMock()
        store.asearch = AsyncMock(return_value=[])
        return store

    def test_account_id(self, manager):
        """Manager has correct account_id."""
        assert manager.account_id == "test_account"

    def test_account_ns(self, manager):
        """account_ns returns correct tuple."""
        ns = manager.account_ns
        assert ns == ("accounts", "test_account")

    def test_content_history_ns(self, manager):
        """content_history_ns returns correct tuple."""
        ns = manager.content_history_ns
        assert ns == ("accounts", "test_account", "content_history")

    def test_audience_ns(self, manager):
        """audience_ns returns correct tuple."""
        ns = manager.audience_ns
        assert ns == ("accounts", "test_account", "audience_preferences")

    def test_insights_ns(self, manager):
        """insights_ns returns correct tuple."""
        ns = manager.insights_ns
        assert ns == ("accounts", "test_account", "performance_insights")

    def test_strategy_ns(self, manager):
        """strategy_ns returns correct tuple."""
        ns = manager.strategy_ns
        assert ns == ("accounts", "test_account", "strategy_notes")

    @pytest.mark.asyncio
    async def test_store_content_record(self, manager, mock_store):
        """store_content_record calls store.aput."""
        record = {"title": "Test Post", "engagement": 100}
        await manager.store_content_record(mock_store, "post_123", record)

        mock_store.aput.assert_called_once()
        # Check namespace, key, value - aput uses kwargs
        call_args = mock_store.aput.call_args
        assert call_args.args[0] == manager.content_history_ns  # namespace
        assert call_args.kwargs.get("key") == "post_123"
        assert call_args.kwargs.get("value") == record

    @pytest.mark.asyncio
    async def test_store_insight(self, manager, mock_store):
        """store_insight calls store.aput."""
        await manager.store_insight(mock_store, "美食话题互动率高", {"post_id": "123"})

        mock_store.aput.assert_called_once()
        call_args = mock_store.aput.call_args
        assert call_args.args[0] == manager.insights_ns

    @pytest.mark.asyncio
    async def test_store_audience_preference(self, manager, mock_store):
        """store_audience_preference calls store.aput."""
        await manager.store_audience_preference(mock_store, "偏好美食内容", {"category": "food"})

        mock_store.aput.assert_called_once()
        call_args = mock_store.aput.call_args
        assert call_args.args[0] == manager.audience_ns

    @pytest.mark.asyncio
    async def test_store_strategy_note(self, manager, mock_store):
        """store_strategy_note calls store.aput."""
        await manager.store_strategy_note(mock_store, "发布时段优化", {"time": "18:00"})

        mock_store.aput.assert_called_once()
        call_args = mock_store.aput.call_args
        assert call_args.args[0] == manager.strategy_ns

    @pytest.mark.asyncio
    async def test_recall_similar_content_empty(self, manager, mock_store):
        """recall_similar_content returns empty list when no results."""
        mock_store.asearch = AsyncMock(return_value=[])
        result = await manager.recall_similar_content(mock_store, "美食")
        assert result == []

    @pytest.mark.asyncio
    async def test_recall_similar_content_with_results(self, manager, mock_store):
        """recall_similar_content returns matching items."""
        mock_item = MagicMock()
        mock_item.value = {"title": "美食探店", "engagement": 100}
        mock_store.asearch = AsyncMock(return_value=[mock_item])

        result = await manager.recall_similar_content(mock_store, "美食", limit=5)

        assert len(result) == 1
        assert result[0]["title"] == "美食探店"
        mock_store.asearch.assert_called_once_with(
            manager.content_history_ns, query="美食", limit=5, filter=None
        )

    @pytest.mark.asyncio
    async def test_recall_audience_preferences(self, manager, mock_store):
        """recall_audience_preferences returns preferences."""
        mock_item = MagicMock()
        mock_item.value = {"preference": "喜欢视频内容"}
        mock_store.asearch = AsyncMock(return_value=[mock_item])

        result = await manager.recall_audience_preferences(mock_store, "视频")

        assert len(result) == 1
        mock_store.asearch.assert_called_once()

    @pytest.mark.asyncio
    async def test_recall_insights(self, manager, mock_store):
        """recall_insights returns insights."""
        mock_item = MagicMock()
        mock_item.value = {"insight": "周末发布效果好"}
        mock_store.asearch = AsyncMock(return_value=[mock_item])

        result = await manager.recall_insights(mock_store, "发布", limit=3)

        assert len(result) == 1
        mock_store.asearch.assert_called_once_with(
            manager.insights_ns, query="发布", limit=3, filter=None
        )

    @pytest.mark.asyncio
    async def test_recall_with_keywords_overfetches(self, manager, mock_store):
        """recall with keywords over-fetches then filters."""
        i1 = MagicMock(value={"insight": "护肤效果好", "category": "美妆"})
        i2 = MagicMock(value={"insight": "穿搭推荐多", "category": "时尚"})
        mock_store.asearch = AsyncMock(return_value=[i1, i2])

        result = await manager.recall_insights(mock_store, "效果", limit=3, keywords=["护肤"])
        # Only the "护肤" item should survive keyword filter
        assert len(result) == 1
        assert result[0]["insight"] == "护肤效果好"
        # Should have over-fetched (limit*2=6)
        call = mock_store.asearch.call_args
        assert call.kwargs.get("limit") == 6

    @pytest.mark.asyncio
    async def test_recall_with_filter_passthrough(self, manager, mock_store):
        """recall passes filter dict to asearch."""
        mock_item = MagicMock()
        mock_item.value = {"insight": "test"}
        mock_store.asearch = AsyncMock(return_value=[mock_item])

        await manager.recall_insights(mock_store, "效果", limit=5, filter={"category": "美妆"})
        mock_store.asearch.assert_called_once_with(
            manager.insights_ns, query="效果", limit=5, filter={"category": "美妆"}
        )

    @pytest.mark.asyncio
    async def test_recall_strategy_notes(self, manager, mock_store):
        """recall_strategy_notes returns notes."""
        mock_item = MagicMock()
        mock_item.value = {"note": "增加美食内容比例"}
        mock_store.asearch = AsyncMock(return_value=[mock_item])

        result = await manager.recall_strategy_notes(mock_store, "策略")

        assert len(result) == 1

    def test_different_accounts_have_different_ns(self):
        """Different accounts have different namespaces."""
        manager1 = MemoryManager("account_1")
        manager2 = MemoryManager("account_2")

        assert manager1.content_history_ns != manager2.content_history_ns
        assert manager1.account_ns != manager2.account_ns

    def test_ns_are_tuples(self, manager):
        """All namespace properties are tuples."""
        assert isinstance(manager.account_ns, tuple)
        assert isinstance(manager.content_history_ns, tuple)
        assert isinstance(manager.audience_ns, tuple)
        assert isinstance(manager.insights_ns, tuple)
        assert isinstance(manager.strategy_ns, tuple)
