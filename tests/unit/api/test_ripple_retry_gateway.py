"""``ripple-retry`` runs its simulations through the Tool Gateway (票 5p).

The route used to call ``RippleService.submit_and_wait`` directly, under a
comment that said why: retry means "run a real simulation again", so the cached
health check and the fallback had to be bypassed. That intent is now carried by
the capability payload (``require_live=True``) — the simulation still cannot be
answered with zeroed fallback data, and a retry that could not simulate writes
nothing and leaves the stored ``ripple_reason`` standing.

These pin the payload contract and the write-nothing half; the artifact write
seam for the same route is pinned in ``test_route_artifact_seams.py``.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.deps import get_current_user
from backend.api.middleware import error_handler_middleware
from backend.api.routes.workflow import router as workflow_router
from backend.db.accounts import AccountRow
from backend.db.workflows import WorkflowRow
from backend.tools.runtime.models import ErrorKind, ToolResult

_OWNED = AccountRow(id="acc1", name="acc1", is_active=True, owner_user_id="user-test")


def _graph() -> MagicMock:
    snapshot = MagicMock()
    snapshot.values = {
        "session_id": "s1",
        "account_id": "acc1",
        "phase": "planning",
        "ripple_reason": "timeout",
        # Fallback-shaped body: this is what makes the route eligible at all.
        "ripple_prediction": {
            "viral_probability": 0,
            "confidence": 0,
            "estimated_reach": 0,
        },
        "content_plan": {
            "selected_topic": "露营咖啡",
            "hashtags": ["a"],
            "content_type": "note",
            "content_angle": "户外",
            "category": "咖啡",
            "key_points": ["p1"],
        },
    }
    snapshot.next = ("ripple_gate",)
    snapshot.tasks = ()
    snapshot.interrupts = ()

    graph = MagicMock()
    # No store: refify stays inline and the assertions can read the bodies.
    graph.store = None
    graph.aget_state = AsyncMock(return_value=snapshot)
    graph.aupdate_state = AsyncMock()
    return graph


def _client(graph: MagicMock) -> TestClient:
    app = FastAPI()
    app.include_router(workflow_router, prefix="/api/workflow")
    app.state.graph = graph
    app.middleware("http")(error_handler_middleware)

    async def _user() -> dict[str, str]:
        return {"id": "user-test", "username": "tester"}

    app.dependency_overrides[get_current_user] = _user
    return TestClient(app)


def _gateway(pred: ToolResult, pmf: ToolResult) -> MagicMock:
    async def _invoke(capability: str, *_args: Any, **_kwargs: Any) -> ToolResult:
        return pred if capability == "ripple.predict_spread" else pmf

    gateway = MagicMock()
    gateway.invoke = AsyncMock(side_effect=_invoke)
    return gateway


def _ok(capability: str, body: dict[str, Any]) -> ToolResult:
    return ToolResult(capability=capability, ok=True, value=body)


def _domain_failure(capability: str, reason: str) -> ToolResult:
    return ToolResult(
        capability=capability,
        ok=False,
        error=f"domain outcome: {reason}",
        error_kind=ErrorKind.DOMAIN,
        domain={"reason": reason},
    )


def _drive_retry(client: TestClient, gateway: MagicMock) -> None:
    """Run the route's background coroutine in-scope (no loose task at teardown)."""
    captured: dict[str, Any] = {}
    real_create_task = asyncio.create_task

    def _fake_create_task(coro: Any, **kwargs: Any) -> Any:
        if getattr(coro, "__name__", "") == "_run_retry":
            captured["coro"] = coro
            task = MagicMock()
            task.get_name = lambda: kwargs.get("name", "")
            return task
        return real_create_task(coro, **kwargs)

    with (
        patch(
            "backend.db.workflows.get_workflow",
            AsyncMock(return_value=WorkflowRow(thread_id="t1", account_id="acc1")),
        ),
        patch("backend.api.account_scope.get_account", AsyncMock(return_value=_OWNED)),
        patch("backend.tools.runtime.bridge.shared_gateway", return_value=gateway),
        patch(
            "backend.api.routes._wf_application.asyncio.create_task",
            side_effect=_fake_create_task,
        ),
    ):
        resp = client.post("/api/workflow/ripple-retry/t1")
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["status"] == "retrying", resp.json()
        asyncio.run(captured["coro"])


def test_the_retry_asks_for_a_live_simulation() -> None:
    """Both capabilities are called with ``require_live=True`` (票 5p 的核心).

    The direct call used to exist to "bypass health-check/fallback"; the intent
    has to survive the migration, otherwise a retry can be silently answered by
    the degraded body and write zeros over the stored fallback flags.
    """
    graph = _graph()
    gateway = _gateway(
        _ok("ripple.predict_spread", {"ripple_prediction": {"viral_probability": 0.7}}),
        _ok("ripple.validate_pmf", {"ripple_pmf": {"pmf_score": 0.6}}),
    )

    _drive_retry(_client(graph), gateway)

    calls = {call.args[0]: call.args[1] for call in gateway.invoke.await_args_list}
    assert set(calls) == {"ripple.predict_spread", "ripple.validate_pmf"}
    for capability, payload in calls.items():
        assert payload["require_live"] is True, capability
        assert payload["max_wait"] == 1800.0, capability
        assert payload["thread_id"] == "t1", capability


def test_a_successful_retry_writes_both_bodies_and_clears_the_flags() -> None:
    graph = _graph()
    gateway = _gateway(
        _ok(
            "ripple.predict_spread",
            {"ripple_prediction": {"viral_probability": 0.7, "estimated_reach": 5200}},
        ),
        _ok("ripple.validate_pmf", {"ripple_pmf": {"pmf_score": 0.6}}),
    )

    _drive_retry(_client(graph), gateway)

    graph.aupdate_state.assert_awaited_once()
    written = graph.aupdate_state.await_args.args[1]
    assert written["ripple_prediction"]["viral_probability"] == 0.7
    assert written["ripple_pmf"]["pmf_score"] == 0.6
    assert written["ripple_reason"] is None
    assert written["ripple_fallback"] is None


def test_a_degraded_retry_writes_nothing() -> None:
    """No real simulation happened: the stored reason must survive intact.

    This is the half the old ``except Exception: return`` provided by *not*
    reaching the update block; the Gateway path has to keep it, because a
    DomainOutcome is a result, not an exception.
    """
    graph = _graph()
    gateway = _gateway(
        _domain_failure("ripple.predict_spread", "unavailable"),
        _domain_failure("ripple.validate_pmf", "unavailable"),
    )

    _drive_retry(_client(graph), gateway)

    graph.aupdate_state.assert_not_awaited()


def test_one_failed_capability_is_enough_to_write_nothing() -> None:
    """Both simulations must run: a half-success is not a fresh analysis."""
    graph = _graph()
    gateway = _gateway(
        _ok("ripple.predict_spread", {"ripple_prediction": {"viral_probability": 0.7}}),
        _domain_failure("ripple.validate_pmf", "timeout"),
    )

    _drive_retry(_client(graph), gateway)

    graph.aupdate_state.assert_not_awaited()
