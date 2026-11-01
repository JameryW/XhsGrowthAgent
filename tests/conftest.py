"""Test fixtures — mock XHS client, mock LLM, test graph."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

# --- DSH Windows sandbox compatibility -------------------------------------
# The DSH sandbox translates a POSIX 0700 directory mode into an ACL that denies
# the owning process, so every `mkdir(mode=0o700)` becomes a directory this
# process cannot open or list. pytest's `tmp_path` factory creates its base and
# per-test dirs exactly that way (as do `tempfile.mkdtemp`/`TemporaryDirectory`),
# which turned a full run into ~200 fixture-setup errors under:
#     PermissionError: [WinError 5] ...\Temp\dsh-*\pytest-of-<user>
# On normal Windows, `mkdir` ignores the mode entirely, so stripping it here is
# a no-op outside the sandbox. The predictable `pytest-of-<user>` root from
# earlier runs is already unreadable, hence the fresh private temproot.
if sys.platform == "win32" and os.environ.get("DSH_SHELL") == "1":
    _real_mkdir = os.mkdir

    def _mkdir_without_private_mode(path, mode=0o777, *, dir_fd=None):
        return _real_mkdir(path, 0o777 if mode == 0o700 else mode, dir_fd=dir_fd)

    os.mkdir = _mkdir_without_private_mode  # type: ignore[assignment]
    # The sandbox's system temp dir is not writable, so ``tempfile.gettempdir()``
    # falls back to the *current directory* (the repo root).  That is how the
    # leaked ``dsh-pytest-temproot-*`` / ``xhs_images`` / ``data-gym-cache``
    # directories appeared in the checkout: the docs-citation corpus walk then
    # counted their files as "ours" and bare ``host:port`` tokens started
    # resolving as citations.  Point the standard temp variables at a
    # dot-prefixed, gitignored directory inside the repo (the corpus rule treats
    # a dot-prefixed component as not ours) so every test-created temp file stays
    # out of the checkout root and out of citation resolution.
    _tempdir = Path(__file__).resolve().parents[1] / ".dsh-tmp"
    os.makedirs(_tempdir, mode=0o777, exist_ok=True)
    for _temp_var in ("TMPDIR", "TEMP", "TMP"):
        os.environ[_temp_var] = str(_tempdir)
    # ``tempfile`` caches the first answer in ``tempfile.tempdir``; pytest itself
    # may already have asked before this conftest ran, caching the repo root.  Set
    # the cache directly, otherwise tiktoken's cache dir and the upload dir keep
    # landing in the checkout root despite the environment override.
    tempfile.tempdir = str(_tempdir)
    _temproot = _tempdir / "pytest-temproot"
    os.makedirs(_temproot, mode=0o777, exist_ok=True)
    os.environ.setdefault("PYTEST_DEBUG_TEMPROOT", tempfile.mkdtemp(prefix="run-", dir=_temproot))

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
# live DB connection. The one exception is opt-in and self-isolating:
# tests/integration/test_creator_agent_backend_parity.py opens its own pool from
# XHS_PG_PARITY_URI (a different variable, so it cannot leak here) and drops a
# scratch database it created.
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


@pytest.fixture(autouse=True)
def _reset_workflow_event_store():
    """Isolate the P1a-S2 in-memory Event store between tests.

    Telemetry no longer lives in the checkpoint, so the fallback store is
    process-global state that would otherwise leak entries (and cost totals)
    from one test's thread_id into the next.
    """
    from backend.state.events import reset_memory_store

    reset_memory_store()
    yield
    reset_memory_store()


@pytest.fixture(autouse=True)
def _reset_execution_lease_store():
    """Isolate the P2b execution-lease fallback store between tests.

    S1 only wrote leases, so a row left behind by one test was invisible. S2
    makes the lease answer "is this thread running", which turns such a row into
    a wrong answer in the next test (running where stale was expected).
    """
    from backend.db import execution_leases

    execution_leases._reset_memory_store()
    yield
    execution_leases._reset_memory_store()


# ── Standard fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def xhs_read_grant(monkeypatch):
    """An account that is entitled to read: a usable cookie in the environment.

    票 5g / §9.6: the read capabilities' declared ``auth_scope`` is enforced at
    the call site now, so a test asserting that a platform read *happened* has
    to describe an account that may make it — otherwise the read is skipped for
    a reason that has nothing to do with what the test is about.

    This seeds a cookie ``XhsCredential.usable`` accepts and lets the real
    resolver compute the grant, rather than stubbing ``granted_scopes``: the
    wiring is then exercised end to end (env -> credential -> grant ->
    invoke). The refusal side is pinned separately in
    ``tests/unit/agents/test_scope_wiring.py``, which needs a grant it can
    withhold — not one this fixture hands to everybody.

    票 5av: the third tier is part of the real answer now.  ``xhs:outreach`` is
    granted whenever the account's outreach policy allows engagement (the safe
    default ``inbound_only`` does), so a usable cookie resolves to all three.
    """
    monkeypatch.setenv("XHS_COOKIE", "a1=0123456789abcdef0123")
    return ("xhs:read", "xhs:write", "xhs:outreach")


@pytest.fixture
def initial_state() -> dict:
    """标准初始状态"""
    return {
        "phase": WorkflowPhase.SCOUTING,
        "current_agent": "orchestrator",
        "error": None,
        "retry_count": 0,
        "trend_data": {},
        "content_plan": {},
        "copy_content": {},
        "visual_plan": {},
        "publish_result": {},
        "analytics": {},
        "engagement_actions": [],
        "human_feedback": {},
        # No "performance_log": P1a-S2 telemetry lives in the Event store.
        "account_id": "test_account",
        "session_id": "test_session",
        "thread_id": "test_session",
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
