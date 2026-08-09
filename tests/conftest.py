"""Test fixtures — mock XHS client, mock LLM, test graph."""

from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, MagicMock

# Tests must never inherit a developer's local browser setting from `.env`.
# The real-browser paths are opt-in and explicitly configured by the tests that
# cover them; all other graph/integration tests should remain hermetic.
os.environ.setdefault("XHS_USE_BROWSER", "false")

# Hermetic env: tests must not inherit a developer's `.env` (which points
# POSTGRES_URI at a container host like `postgres-xhs` that is unreachable
# from the host). If that URI leaks in, the app lifespan's init_pool() retries
# DNS for ~60s before giving up — paid by the first TestClient(app) in every
# pytest process. Pop it before any backend import and neutralise load_dotenv
# so app.py's module-level `load_dotenv(override=True)` can't re-inject it.
# Tests that need pool behavior mock `is_pool_ready` explicitly; none rely on a
# live DB connection (verified across the suite).
os.environ.pop("POSTGRES_URI", None)
os.environ.pop("REDIS_URI", None)
# App lifespan compiles the development graph for TestClient-based integration
# tests. Keep that hermetic: the production default local embedding model may
# download/load hundreds of MB before the first request. Individual embedding
# tests use clear=True patches when they need to exercise a real provider path.
os.environ["XHS_EMBED_MODEL"] = "disabled"
import dotenv as _dotenv

_dotenv.load_dotenv = lambda *a, **kw: False  # type: ignore[assignment]

# Mock playwright before any imports
playwright_mock = MagicMock()
sys.modules["playwright"] = playwright_mock
sys.modules["playwright.async_api"] = MagicMock()

import pytest  # noqa: E402  (after playwright sys.modules mock above)

from backend.state.schema import WorkflowPhase  # noqa: E402

# ── Global LLM/Ripple mock ──────────────────────────────────────────────────
# Prevent any test from accidentally calling real LLM or Ripple APIs.


@pytest.fixture(autouse=True)
def _mock_get_model():
    """Auto-mock get_model in all import locations to prevent real LLM calls."""
    mock_model = MagicMock()
    mock_model.ainvoke = AsyncMock(return_value=MagicMock(content='{"result": "mocked"}'))
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("backend.models.router.get_model", lambda *a, **kw: mock_model)
        mp.setattr("backend.agents.base.get_model", lambda *a, **kw: mock_model)
        mp.setattr("backend.services.llm_enrichment.get_model", lambda *a, **kw: mock_model)
        yield


@pytest.fixture(autouse=True)
def _mock_ripple_service():
    """Auto-mock RippleService.get_instance to prevent real Ripple API calls."""
    mock_service = MagicMock()
    mock_service.is_healthy = MagicMock(return_value=False)
    mock_service.predict_spread = AsyncMock(return_value={"ripple_fallback": True})
    mock_service.validate_pmf = AsyncMock(return_value={"ripple_fallback": True})
    mock_service.health_check = AsyncMock()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "backend.services.ripple_service.RippleService.get_instance",
            lambda: mock_service,
        )
        # backend.tools.ripple.client is a module, not a package — mock the class directly
        try:
            from backend.tools.ripple.client import RippleService as ClientRippleService

            mp.setattr(ClientRippleService, "get_instance", lambda: mock_service)
        except ImportError:
            pass
        yield


# ── Standard fixtures ────────────────────────────────────────────────────────


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
