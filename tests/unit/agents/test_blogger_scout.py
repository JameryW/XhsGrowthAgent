"""Unit tests for BloggerScoutAgent."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.agents.blogger_scout import BloggerScoutAgent
from backend.config.models import TaskType
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

    def test_task_type_is_mock_gen(self, agent):
        """blogger_scout routes to MOCK_GEN (轻模型) for虚构候选生成,
        not SCOUTING (which trend_scout keeps for真实趋势分析)."""
        assert agent.task_type == TaskType.MOCK_GEN
        assert agent.task_type != TaskType.SCOUTING

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
        """Execute returns LLM-generated blogger candidates."""
        mock_response = MagicMock()
        mock_response.content = '{"candidates": [{"user_id": "mock_001", "nickname": "博主A", "follower_count": 5000, "note_count": 100, "total_engagement": 3000, "top_note_title": "美食探店"}, {"user_id": "mock_002", "nickname": "博主B", "follower_count": 3000, "note_count": 80, "total_engagement": 2000, "top_note_title": "咖啡推荐"}]}'  # noqa: E501
        agent._model = AsyncMock()
        agent._model.ainvoke = AsyncMock(return_value=mock_response)

        result = await agent.execute(trend_state, store=mock_store)

        assert "blogger_candidates" in result
        assert len(result["blogger_candidates"]) == 2
        assert result["blogger_candidates"][0]["user_id"] == "mock_001"
        assert result["blogger_candidates"][0]["total_engagement"] > 0

    @pytest.mark.asyncio
    async def test_execute_respects_candidate_limit(self, agent, brief_state, mock_store):
        """Execute respects blogger_candidate_limit."""
        candidates = [
            {
                "user_id": f"mock_{i}",
                "nickname": f"User {i}",
                "follower_count": 1000 + i,
                "note_count": 10,
                "total_engagement": 100 + i,
                "top_note_title": f"Note {i}",
            }
            for i in range(10)
        ]
        mock_response = MagicMock()
        mock_response.content = json.dumps({"candidates": candidates}, ensure_ascii=False)
        agent._model = AsyncMock()
        agent._model.ainvoke = AsyncMock(return_value=mock_response)

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
    async def test_execute_uses_llm_generation(self, agent, trend_state, mock_store):
        """Uses LLM mock generation for blogger candidates."""
        mock_response = MagicMock()
        mock_response.content = '{"candidates": [{"user_id": "mock_001", "nickname": "测试博主", "follower_count": 5000, "note_count": 50, "total_engagement": 3000, "top_note_title": "测试笔记标题"}]}'  # noqa: E501

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
        mock_response = MagicMock()
        mock_response.content = '{"candidates": [{"user_id": "001", "nickname": "博主A", "follower_count": 1000, "note_count": 20, "total_engagement": 500, "top_note_title": "标题"}]}'  # noqa: E501

        agent._model = AsyncMock()
        agent._model.ainvoke = AsyncMock(return_value=mock_response)
        result = await agent.execute(trend_state, store=mock_store)

        assert result["blogger_candidates"][0]["user_id"] == "mock_001"

    @pytest.mark.asyncio
    async def test_execute_llm_fallback_adds_avatar_url(self, agent, trend_state, mock_store):
        """LLM fallback adds empty avatar_url if not present in LLM response."""
        mock_response = MagicMock()
        mock_response.content = '{"candidates": [{"user_id": "mock_001", "nickname": "博主A", "follower_count": 1000, "note_count": 20, "total_engagement": 500, "top_note_title": "标题"}]}'  # noqa: E501

        agent._model = AsyncMock()
        agent._model.ainvoke = AsyncMock(return_value=mock_response)
        result = await agent.execute(trend_state, store=mock_store)

        assert "avatar_url" in result["blogger_candidates"][0]

    @pytest.mark.asyncio
    async def test_execute_llm_fallback_failure_returns_empty(self, agent, trend_state, mock_store):
        """Returns hardcoded fallback when LLM fallback also fails."""
        agent._model = AsyncMock()
        agent._model.ainvoke = AsyncMock(side_effect=Exception("LLM error"))
        result = await agent.execute(trend_state, store=mock_store)

        # Should get hardcoded fallback instead of empty
        assert len(result["blogger_candidates"]) > 0
        assert result["phase"] == WorkflowPhase.CREATING

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
