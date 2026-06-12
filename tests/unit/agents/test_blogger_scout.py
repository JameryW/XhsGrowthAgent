"""Unit tests for BloggerScoutAgent."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.agents.blogger_scout import BloggerScoutAgent
from backend.services.xhs_client import XHSSearchResult
from backend.state.enums import WorkflowMode, WorkflowPhase


class TestBloggerScoutAgent:
    """Tests for BloggerScoutAgent blogger discovery."""

    @pytest.fixture
    def agent(self):
        """Create blogger scout instance."""
        return BloggerScoutAgent()

    @pytest.fixture
    def mock_store(self):
        """Mock LangGraph store."""
        return AsyncMock()

    @pytest.fixture
    def trend_state(self):
        """State for trend mode with keywords."""
        return {
            "account_id": "test_account",
            "workflow_mode": WorkflowMode.TREND,
            "phase": WorkflowPhase.CREATING,
            "xhs_cookie": "test_cookie",
            "trend_data": {
                "trending_keywords": ["美食探店", "咖啡推荐", "甜品"],
            },
            "content_plan": {
                "selected_topic": "下午茶",
            },
            "blogger_candidate_limit": 5,
        }

    @pytest.fixture
    def brief_state(self):
        """State for brief mode with keywords."""
        return {
            "account_id": "test_account",
            "workflow_mode": WorkflowMode.BRIEF,
            "phase": WorkflowPhase.CREATING,
            "xhs_cookie": "test_cookie",
            "brief_content": {
                "required_keywords": ["几素风扇", "婴儿车风扇"],
                "brand_name": "几素",
            },
            "blogger_candidate_limit": 3,
        }

    def test_agent_attributes(self, agent):
        """Verify agent class attributes."""
        assert agent.agent_name == "blogger_scout"
        assert agent.prompt_file == "blogger_scout.yaml"

    def test_extract_keywords_trend_mode(self, agent, trend_state):
        """Extract keywords from trend mode state."""
        keywords = agent._extract_keywords(trend_state)

        assert "美食探店" in keywords
        assert "下午茶" in keywords
        assert len(keywords) <= 5

    def test_extract_keywords_brief_mode(self, agent, brief_state):
        """Extract keywords from brief mode state."""
        keywords = agent._extract_keywords(brief_state)

        assert "几素风扇" in keywords
        assert "几素" in keywords

    def test_extract_keywords_deduplicates(self, agent):
        """Keywords are deduplicated while preserving order."""
        state = {
            "trend_data": {"trending_keywords": ["美食", "美食", "咖啡"]},
            "content_plan": {"selected_topic": "美食"},
            "brief_content": {},
        }
        keywords = agent._extract_keywords(state)

        assert keywords.count("美食") == 1
        assert "咖啡" in keywords

    def test_extract_keywords_empty_state(self, agent):
        """Returns empty list when no keywords available."""
        keywords = agent._extract_keywords({})
        assert keywords == []

    def test_extract_keywords_limits_to_5(self, agent):
        """At most 5 keywords are returned."""
        state = {
            "trend_data": {"trending_keywords": [f"kw{i}" for i in range(10)]},
            "content_plan": {},
            "brief_content": {},
        }
        keywords = agent._extract_keywords(state)
        assert len(keywords) <= 5

    @pytest.mark.asyncio
    async def test_execute_returns_candidates(self, agent, trend_state, mock_store):
        """Execute returns blogger candidates with engagement sorting."""
        mock_search_results = [
            XHSSearchResult(
                note_id="n1", title="美食探店", user_name="博主A", user_id="u1",
                likes=100, comments=20, collects=30, cover_url="", note_url="",
            ),
            XHSSearchResult(
                note_id="n2", title="咖啡推荐", user_name="博主B", user_id="u2",
                likes=50, comments=10, collects=15, cover_url="", note_url="",
            ),
        ]

        mock_user_info = {
            "avatar": "http://avatar.jpg",
            "follows": 5000,
            "notes_count": 100,
        }

        with patch("backend.services.xhs_client.XHSClient") as MockClient:
            mock_client = MagicMock()
            mock_client._http = MagicMock()
            mock_client.search_posts = AsyncMock(return_value=mock_search_results)
            mock_client.get_user_info = AsyncMock(return_value=mock_user_info)
            mock_client.close = AsyncMock()
            MockClient.return_value = mock_client

            result = await agent.execute(trend_state, store=mock_store)

        assert "blogger_candidates" in result
        assert len(result["blogger_candidates"]) == 2
        # Sorted by engagement: 博主A (150 per keyword × keywords) > 博主B (75 per keyword × keywords)
        assert result["blogger_candidates"][0]["user_id"] == "u1"
        assert result["blogger_candidates"][0]["total_engagement"] > 0

    @pytest.mark.asyncio
    async def test_execute_respects_candidate_limit(self, agent, brief_state, mock_store):
        """Execute respects blogger_candidate_limit."""
        mock_search_results = [
            XHSSearchResult(
                note_id=f"n{i}", title=f"Note {i}", user_name=f"User {i}",
                user_id=f"u{i}", likes=10 * i, comments=0, collects=0,
                cover_url="", note_url="",
            )
            for i in range(10)
        ]

        with patch("backend.services.xhs_client.XHSClient") as MockClient:
            mock_client = MagicMock()
            mock_client._http = MagicMock()
            mock_client.search_posts = AsyncMock(return_value=mock_search_results)
            mock_client.get_user_info = AsyncMock(return_value={})
            mock_client.close = AsyncMock()
            MockClient.return_value = mock_client

            result = await agent.execute(brief_state, store=mock_store)

        assert len(result["blogger_candidates"]) <= brief_state["blogger_candidate_limit"]

    @pytest.mark.asyncio
    async def test_execute_no_keywords_returns_empty(self, agent, mock_store):
        """Returns hardcoded fallback candidates when no keywords found."""
        state = {
            "account_id": "test",
            "workflow_mode": WorkflowMode.TREND,
            "trend_data": {},
            "content_plan": {},
            "brief_content": {},
        }

        result = await agent.execute(state, store=mock_store)

        # Now always returns fallback candidates instead of empty
        assert len(result["blogger_candidates"]) > 0
        assert result["phase"] == WorkflowPhase.CREATING

    @pytest.mark.asyncio
    async def test_execute_no_cookie_falls_back_to_llm(self, agent, trend_state, mock_store):
        """Falls back to LLM mock generation when no XHS cookie available."""
        trend_state["xhs_cookie"] = ""

        mock_response = MagicMock()
        mock_response.content = '{"candidates": [{"user_id": "mock_001", "nickname": "测试博主", "follower_count": 5000, "note_count": 50, "total_engagement": 3000, "top_note_title": "测试笔记标题"}]}'

        agent._model = AsyncMock()
        agent._model.ainvoke = AsyncMock(return_value=mock_response)
        result = await agent.execute(trend_state, store=mock_store)

        assert len(result["blogger_candidates"]) == 1
        assert result["blogger_candidates"][0]["user_id"].startswith("mock_")
        assert result["blogger_candidates"][0]["nickname"] == "测试博主"
        assert result["phase"] == WorkflowPhase.CREATING

    @pytest.mark.asyncio
    async def test_execute_llm_fallback_ensures_mock_prefix(self, agent, trend_state, mock_store):
        """LLM fallback ensures all user_ids have mock_ prefix even if LLM omits it."""
        trend_state["xhs_cookie"] = ""

        mock_response = MagicMock()
        mock_response.content = '{"candidates": [{"user_id": "001", "nickname": "博主A", "follower_count": 1000, "note_count": 20, "total_engagement": 500, "top_note_title": "标题"}]}'

        agent._model = AsyncMock()
        agent._model.ainvoke = AsyncMock(return_value=mock_response)
        result = await agent.execute(trend_state, store=mock_store)

        assert result["blogger_candidates"][0]["user_id"] == "mock_001"

    @pytest.mark.asyncio
    async def test_execute_llm_fallback_adds_avatar_url(self, agent, trend_state, mock_store):
        """LLM fallback adds empty avatar_url if not present in LLM response."""
        trend_state["xhs_cookie"] = ""

        mock_response = MagicMock()
        mock_response.content = '{"candidates": [{"user_id": "mock_001", "nickname": "博主A", "follower_count": 1000, "note_count": 20, "total_engagement": 500, "top_note_title": "标题"}]}'

        agent._model = AsyncMock()
        agent._model.ainvoke = AsyncMock(return_value=mock_response)
        result = await agent.execute(trend_state, store=mock_store)

        assert "avatar_url" in result["blogger_candidates"][0]

    @pytest.mark.asyncio
    async def test_execute_llm_fallback_failure_returns_empty(self, agent, trend_state, mock_store):
        """Returns hardcoded fallback when LLM fallback also fails."""
        trend_state["xhs_cookie"] = ""

        agent._model = AsyncMock()
        agent._model.ainvoke = AsyncMock(side_effect=Exception("LLM error"))
        result = await agent.execute(trend_state, store=mock_store)

        # Should get hardcoded fallback instead of empty
        assert len(result["blogger_candidates"]) > 0
        assert result["phase"] == WorkflowPhase.CREATING

    @pytest.mark.asyncio
    async def test_execute_xhs_cookie_takes_priority(self, agent, trend_state, mock_store):
        """Real XHS client takes priority over LLM fallback."""
        mock_search_results = [
            XHSSearchResult(
                note_id="n1", title="真实笔记", user_name="真实博主", user_id="real_u1",
                likes=200, comments=30, collects=50, cover_url="", note_url="",
            ),
        ]

        mock_model = AsyncMock()

        with patch("backend.services.xhs_client.XHSClient") as MockClient:
            mock_client = MagicMock()
            mock_client._http = MagicMock()
            mock_client.search_posts = AsyncMock(return_value=mock_search_results)
            mock_client.get_user_info = AsyncMock(return_value={})
            mock_client.close = AsyncMock()
            MockClient.return_value = mock_client

            agent._model = mock_model
            result = await agent.execute(trend_state, store=mock_store)

        mock_model.ainvoke.assert_not_called()
        assert result["blogger_candidates"][0]["user_id"] == "real_u1"

    @pytest.mark.asyncio
    async def test_execute_api_error_returns_empty(self, agent, trend_state, mock_store):
        """Returns hardcoded fallback candidates on API error."""
        with patch("backend.services.xhs_client.XHSClient") as MockClient:
            mock_client = MagicMock()
            mock_client._http = MagicMock()
            mock_client.search_posts = AsyncMock(side_effect=Exception("API error"))
            mock_client.close = AsyncMock()
            MockClient.return_value = mock_client

            result = await agent.execute(trend_state, store=mock_store)

        assert len(result["blogger_candidates"]) > 0
        assert result["phase"] == WorkflowPhase.CREATING

    @pytest.mark.asyncio
    async def test_execute_top_note_tracking(self, agent, trend_state, mock_store):
        """Tracks top note title per blogger based on engagement."""
        # Two notes from same blogger — second has higher engagement
        mock_search_results = [
            XHSSearchResult(
                note_id="n1", title="低互动笔记", user_name="博主A", user_id="u1",
                likes=10, comments=0, collects=0, cover_url="", note_url="",
            ),
            XHSSearchResult(
                note_id="n2", title="高互动笔记", user_name="博主A", user_id="u1",
                likes=500, comments=50, collects=100, cover_url="", note_url="",
            ),
        ]

        with patch("backend.services.xhs_client.XHSClient") as MockClient:
            mock_client = MagicMock()
            mock_client._http = MagicMock()
            mock_client.search_posts = AsyncMock(return_value=mock_search_results)
            mock_client.get_user_info = AsyncMock(return_value={})
            mock_client.close = AsyncMock()
            MockClient.return_value = mock_client

            result = await agent.execute(trend_state, store=mock_store)

        assert len(result["blogger_candidates"]) == 1
        assert result["blogger_candidates"][0]["top_note_title"] == "高互动笔记"

    def test_summarize_trend_data_empty(self, agent):
        """Returns default message for empty trend data."""
        summary = agent._summarize_trend_data({})
        assert summary == "无趋势数据"

    def test_summarize_trend_data_with_keywords(self, agent):
        """Summarizes trend data with keywords."""
        trend_data = {"trending_keywords": ["美食", "咖啡", "甜品"]}
        summary = agent._summarize_trend_data(trend_data)
        assert "热门关键词" in summary
        assert "美食" in summary

    def test_summarize_trend_data_with_hot_topics(self, agent):
        """Summarizes trend data with hot topics."""
        trend_data = {"hot_topics": ["夏日穿搭", "防晒推荐"]}
        summary = agent._summarize_trend_data(trend_data)
        assert "热门话题" in summary

    def test_summarize_trend_data_with_notes(self, agent):
        """Summarizes trend data with trending notes."""
        trend_data = {
            "trending_notes": [
                {"title": "爆款笔记A"},
                {"title": "爆款笔记B"},
            ]
        }
        summary = agent._summarize_trend_data(trend_data)
        assert "热门笔记" in summary
        assert "爆款笔记A" in summary
