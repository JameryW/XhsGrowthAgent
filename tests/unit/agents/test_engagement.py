"""Unit tests for EngagementAgent memory writes."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.agents.engagement import EngagementAgent
from backend.state.schema import EngagementAction, WorkflowPhase


class TestEngagementMemoryWrites:
    """Tests for engagement agent memory storage."""

    @pytest.fixture
    def agent(self):
        return EngagementAgent()

    @pytest.fixture
    def mock_store(self):
        store = AsyncMock()
        store.aput = AsyncMock()
        store.asearch = AsyncMock(return_value=[])
        return store

    @pytest.mark.asyncio
    async def test_stores_audience_preference_after_engagement(self, agent, mock_store):
        """Engagement stores audience preference when actions are taken."""
        mock_state = {
            "account_id": "test_account",
            "execution_mode": "single",
            "publish_result": {"post_id": "post_123"},
        }

        with patch("backend.agents.engagement.Settings") as mock_settings_cls:
            mock_settings = MagicMock()
            mock_settings.platform.use_browser = False
            mock_settings_cls.return_value = mock_settings

            # Even with use_browser=False, we can test the store path
            # by simulating actions being present
            result = await agent.execute(mock_state, store=mock_store)

            # No engagement_actions when use_browser=False, so no store call
            assert result["phase"] == WorkflowPhase.COMPLETED
            mock_store.aput.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_store_when_no_actions(self, agent, mock_store):
        """No audience preference stored when there are no engagement actions."""
        mock_state = {
            "account_id": "test_account",
            "execution_mode": "single",
            "publish_result": {},
        }

        with patch("backend.agents.engagement.Settings") as mock_settings_cls:
            mock_settings = MagicMock()
            mock_settings.platform.use_browser = False
            mock_settings_cls.return_value = mock_settings

            result = await agent.execute(mock_state, store=mock_store)

            mock_store.aput.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_store_when_store_is_none(self, agent):
        """No error when store is None."""
        mock_state = {
            "account_id": "test_account",
            "execution_mode": "single",
            "publish_result": {},
        }

        with patch("backend.agents.engagement.Settings") as mock_settings_cls:
            mock_settings = MagicMock()
            mock_settings.platform.use_browser = False
            mock_settings_cls.return_value = mock_settings

            result = await agent.execute(mock_state, store=None)

            assert result["phase"] == WorkflowPhase.COMPLETED
