"""Test fixtures — mock XHS client, mock LLM, test graph."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

# Mock playwright before any imports
playwright_mock = MagicMock()
sys.modules["playwright"] = playwright_mock
sys.modules["playwright.async_api"] = MagicMock()

import pytest
from unittest.mock import AsyncMock, MagicMock

from xhs_growth.state.schema import XHSGrowthState, WorkflowPhase


@pytest.fixture
def initial_state() -> dict:
    """标准初始状态"""
    return {
        "phase": WorkflowPhase.SCOUTING,
        "current_agent": "orchestrator",
        "error": None,
        "retry_count": 0,
        "messages": [],
        "trend_data": {},
        "content_plan": {},
        "copy_content": {},
        "visual_plan": {},
        "publish_result": {},
        "analytics": {},
        "engagement_actions": [],
        "human_feedback": {},
        "content_history": [],
        "performance_log": [],
        "account_id": "test_account",
        "session_id": "test_session",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }


@pytest.fixture
def mock_llm():
    """模拟 LLM 响应"""
    llm = AsyncMock()
    response = MagicMock()
    response.content = '{"hot_topics": [{"topic": "测试话题", "heat_score": 80}]}'
    llm.ainvoke = AsyncMock(return_value=response)
    return llm


@pytest.fixture
def mock_store():
    """模拟 LangGraph BaseStore"""
    store = AsyncMock()
    store.asearch = AsyncMock(return_value=[])
    store.aput = AsyncMock()
    return store
