"""Unit tests for Memory Manager."""

from unittest.mock import AsyncMock, MagicMock
import pytest

from xhs_growth.memory.store import MemoryManager


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
        # Check namespace and key
        call_args = mock_store.aput.call_args
        assert call_args[0][0] == manager.content_history_ns
        assert call_args[0][1] == "post_123"

    @pytest.mark.asyncio
    async def test_store_insight(self, manager, mock_store):
        """store_insight calls store.aput."""
        await manager.store_insight(mock_store, "美食话题互动率高", {"post_id": "123"})

        mock_store.aput.assert_called_once()
        call_args = mock_store.aput.call_args
        assert call_args[0][0] == manager.insights_ns

    @pytest.mark.asyncio
    async def test_store_audience_preference(self, manager, mock_store):
        """store_audience_preference calls store.aput."""
        await manager.store_audience_preference(
            mock_store, "偏好美食内容", {"category": "food"}
        )

        mock_store.aput.assert_called_once()
        call_args = mock_store.aput.call_args
        assert call_args[0][0] == manager.audience_ns

    @pytest.mark.asyncio
    async def test_store_strategy_note(self, manager, mock_store):
        """store_strategy_note calls store.aput."""
        await manager.store_strategy_note(mock_store, "发布时段优化", {"time": "18:00"})

        mock_store.aput.assert_called_once()
        call_args = mock_store.aput.call_args
        assert call_args[0][0] == manager.strategy_ns

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
            manager.content_history_ns, query="美食", limit=5
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
            manager.insights_ns, query="发布", limit=3
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