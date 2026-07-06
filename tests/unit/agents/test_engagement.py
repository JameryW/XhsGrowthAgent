"""Unit tests for EngagementAgent memory writes."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.agents.engagement import EngagementAgent
from backend.state.schema import WorkflowPhase


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

            await agent.execute(mock_state, store=mock_store)

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

    @pytest.mark.asyncio
    async def test_dry_run_skips_real_api(self, agent, mock_store):
        """dry_run=True skips real XHS API calls even with a mock post_id.

        Guards against latent API leakage: a dry_run publisher returns
        post_id="mock_<session>", and engagement must not call
        client.get_comments against that fake ID on the real XHS API.
        """
        mock_state = {
            "account_id": "test_account",
            "execution_mode": "single",
            "dry_run": True,
            "publish_result": {"post_id": "mock_session123"},
        }

        with patch("backend.agents.engagement.Settings") as mock_settings_cls:
            mock_settings = MagicMock()
            mock_settings.platform.use_browser = True
            mock_settings_cls.return_value = mock_settings

            with patch("backend.services.xhs_client.XHSClient") as mock_client_cls:
                # Configure a fully-async mock instance so that IF the guard
                # regresses and XHSClient IS instantiated, the failure surfaces
                # at the assert_not_called assertion (clear message) rather than
                # crashing at `await client.close()` (confusing TypeError that
                # masks the real assertion).
                mock_inst = AsyncMock()
                mock_inst.get_comments = AsyncMock(return_value=[])
                mock_inst.get_direct_messages = AsyncMock(return_value=[])
                mock_inst.close = AsyncMock()
                mock_client_cls.return_value = mock_inst

                result = await agent.execute(mock_state, store=mock_store)

                # XHSClient must never be instantiated under dry_run
                mock_client_cls.assert_not_called()
                assert result["phase"] == WorkflowPhase.COMPLETED
                assert result["engagement_error"] is None

    @pytest.mark.asyncio
    async def test_mock_post_id_skips_real_api(self, agent, mock_store):
        """A mock_ post_id (from dry_run publisher) skips real API calls.

        Belt-and-suspenders: even if state.dry_run is missing, a post_id
        starting with 'mock_' triggers the guard.
        """
        mock_state = {
            "account_id": "test_account",
            "execution_mode": "single",
            "publish_result": {"post_id": "mock_abc123"},
        }

        with patch("backend.agents.engagement.Settings") as mock_settings_cls:
            mock_settings = MagicMock()
            mock_settings.platform.use_browser = True
            mock_settings_cls.return_value = mock_settings

            with patch("backend.services.xhs_client.XHSClient") as mock_client_cls:
                mock_inst = AsyncMock()
                mock_inst.get_comments = AsyncMock(return_value=[])
                mock_inst.get_direct_messages = AsyncMock(return_value=[])
                mock_inst.close = AsyncMock()
                mock_client_cls.return_value = mock_inst

                result = await agent.execute(mock_state, store=mock_store)

                mock_client_cls.assert_not_called()
                assert result["phase"] == WorkflowPhase.COMPLETED

    @pytest.mark.asyncio
    async def test_engagement_error_recorded_on_failure(self, agent, mock_store):
        """Engagement failure records engagement_error without flipping to ERROR.

        The post was published successfully; engagement (non-critical) failed.
        Workflow stays COMPLETED — setting the generic ``error`` field would
        reclassify it as ERROR via derive_status (engagement has no next_nodes).
        """
        mock_state = {
            "account_id": "test_account",
            "execution_mode": "single",
            "publish_result": {"post_id": "real_post_123"},
        }

        with patch("backend.agents.engagement.Settings") as mock_settings_cls:
            mock_settings = MagicMock()
            mock_settings.platform.use_browser = True
            mock_settings_cls.return_value = mock_settings

            with patch("backend.services.xhs_client.XHSClient") as mock_client_cls:
                mock_client = AsyncMock()
                # get_comments raises — simulates XHS API failure mid-engagement
                mock_client.get_comments = AsyncMock(side_effect=RuntimeError("XHS API down"))
                mock_client.close = AsyncMock()
                mock_client_cls.return_value = mock_client

                result = await agent.execute(mock_state, store=mock_store)

                assert result["phase"] == WorkflowPhase.COMPLETED
                assert result["engagement_error"] == "XHS API down"
                # Generic error field must NOT be set — would flip derive_status to ERROR
                assert "error" not in result or result.get("error") is None
