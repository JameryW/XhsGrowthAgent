"""The two repair paths hold the same lease the unified entry holds.

``docs/execution-plane.md`` §2 used to say the lease covered only the one path
that writes checkpoints, and §7 named two repair paths as the exception.  The
sentence was true and the exception was the thing worth fixing: an execution
holding no lease is invisible to ``expire_scan``, so a takeover scan could start
a second writer on the same checkpoint while a retry was mid-flight.

These tests are the difference between "§7 says it takes a lease" and "it does":

- the lease is **held while the work runs** and **released** when it ends --
  observed from inside the work, not inferred from the endpoint's reply;
- a **refused** lease does not gate the work (P2b ruling 2): the block runs with
  no fence, which is why "take a lease" introduces no refusal branch;
- the lease is released even when the work raises -- the leak is the one new
  failure mode this change could have added, so it is pinned, not argued about;
- the **fence needs no registry entry**: its cancel target is
  ``asyncio.current_task()``, which is what makes the lease usable by a path that
  deliberately stays out of ``_background_tasks`` (see §7.1);
- a **leaked** lease cannot become an automatic re-run, because the pending node
  of either repair path is one the takeover registry refuses.

The two endpoint tests drive the coroutine in a fresh loop rather than letting
the request's portal run it, so the observation is deterministic.  ``_wf_actions``
is the only module whose ``asyncio`` is substituted -- the lease helper and
``start_lease`` must keep the real module, or the heartbeat would be a mock and
the release assertion would be testing the substitution instead of the code.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langgraph.store.memory import InMemoryStore

from backend.api.deps import get_current_user
from backend.api.middleware import error_handler_middleware
from backend.api.routes import _runner as runner_module
from backend.api.routes.workflow import router as workflow_router
from backend.db import execution_leases as leases
from backend.db.accounts import AccountRow
from backend.db.workflows import WorkflowRow
from backend.graph.takeover_safety import takeover_verdict

_OWNED = AccountRow(id="acc1", name="acc1", is_active=True, owner_user_id="user-test")
_RIPPLE_SERVICE = "backend.services.ripple_service.RippleService.get_instance"
_RUN_PUBLISH = "backend.api.routes._wf_actions.run_publish"
_DB_UPSERT = "backend.api.routes._wf_actions._db_upsert"
_EVENT_BUS = "backend.api.routes._wf_actions.EventBusService"
_ARTIFACTS = "backend.state.artifacts"


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Memory-backed leases and empty registries, restored afterwards."""
    monkeypatch.setattr(leases, "is_pool_ready", lambda: False)
    leases._reset_memory_store()
    runner_module._background_tasks.clear()
    runner_module._active_sync_executions.clear()
    yield
    leases._reset_memory_store()
    runner_module._background_tasks.clear()
    runner_module._active_sync_executions.clear()


class _AsyncioShim:
    """``asyncio`` as seen by ``_wf_actions``: ``create_task`` captured, rest real."""

    def __init__(self, captured: dict[str, Any]) -> None:
        self._captured = captured

    def create_task(self, coro: Any, **kwargs: Any) -> MagicMock:
        self._captured["coro"] = coro
        task = MagicMock()
        task.get_name = lambda: str(kwargs.get("name", ""))
        return task

    def __getattr__(self, name: str) -> Any:
        return getattr(asyncio, name)


def _drive(captured: dict[str, Any]) -> None:
    """Run the captured coroutine to completion in its own loop."""
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(captured["coro"])
    finally:
        loop.close()


@contextlib.contextmanager
def _client(graph: MagicMock) -> Iterator[TestClient]:
    app = FastAPI()
    app.include_router(workflow_router, prefix="/api/workflow")
    app.state.graph = graph
    app.middleware("http")(error_handler_middleware)

    async def _user() -> dict[str, str]:
        return {"id": "user-test", "username": "tester"}

    app.dependency_overrides[get_current_user] = _user
    db_row = WorkflowRow(thread_id="t1", account_id="acc1")
    with (
        patch("backend.db.workflows.get_workflow", AsyncMock(return_value=db_row)),
        patch("backend.api.account_scope.get_account", AsyncMock(return_value=_OWNED)),
    ):
        yield TestClient(app)


def _ripple_graph() -> MagicMock:
    snapshot = MagicMock()
    snapshot.values = {
        "session_id": "t1",
        "account_id": "acc1",
        "phase": "planning",
        "ripple_reason": "timeout",
        "content_plan": {"selected_topic": "露营咖啡", "hashtags": []},
    }
    snapshot.next = ("ripple_gate",)
    snapshot.tasks = ()
    snapshot.interrupts = ()

    graph = MagicMock()
    graph.store = InMemoryStore()
    graph.aget_state = AsyncMock(return_value=snapshot)
    graph.aupdate_state = AsyncMock()
    return graph


def _publish_graph() -> MagicMock:
    snapshot = MagicMock()
    snapshot.values = {
        "session_id": "t1",
        "account_id": "acc1",
        "phase": "publishing",
        "copy_content": {"selected_title": "t", "body_text": "b"},
        "publish_result": {"status": "failed", "post_id": ""},
    }
    snapshot.next = ("publisher",)
    snapshot.tasks = ()
    snapshot.interrupts = ()

    graph = MagicMock()
    graph.store = InMemoryStore()
    graph.aget_state = AsyncMock(return_value=snapshot)
    graph.aupdate_state = AsyncMock()
    return graph


def _passthrough_artifacts() -> Any:
    """The read/write seam as identity: the lease question is not about refs."""
    return (
        patch(
            f"{_ARTIFACTS}.resolve_state",
            AsyncMock(side_effect=lambda _store, _tid, values: values),
        ),
        patch(
            f"{_ARTIFACTS}.refify_updates",
            AsyncMock(side_effect=lambda _store, _tid, updates, **_kw: updates),
        ),
    )


# ── the lease is held while the work runs ────────────────────────────────────


def test_ripple_retry_holds_the_lease_while_the_simulation_runs() -> None:
    """Observed from inside ``submit_and_wait``, not from the endpoint's reply."""
    graph = _ripple_graph()
    seen: dict[str, Any] = {}
    captured: dict[str, Any] = {}

    service = MagicMock()

    async def _submit(*_args: Any, **kwargs: Any) -> dict[str, Any]:
        seen.setdefault("during", []).append(await leases.get_lease(kwargs["thread_id"]))
        return {}

    service.submit_and_wait = _submit
    service._parse_spread_result = lambda _raw: {}
    service._parse_pmf_result = lambda _raw: {}

    resolve_state, refify_updates = _passthrough_artifacts()
    with (
        _client(graph) as client,
        patch(_RIPPLE_SERVICE, return_value=service),
        resolve_state,
        refify_updates,
        patch("backend.api.routes._wf_actions.asyncio", _AsyncioShim(captured)),
    ):
        resp = client.post("/api/workflow/ripple-retry/t1")
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["status"] == "retrying", resp.json()
        _drive(captured)

    during = seen.get("during")
    assert during, "the ripple retry never reached the simulation"
    for record in during:
        assert record is not None, "no lease row while the retry was running"
        assert record.state is leases.LeaseState.HELD
        assert record.owner_id == leases.instance_identity()[0]
    after = asyncio.run(leases.get_lease("t1"))
    assert after.state is leases.LeaseState.RELEASED, "the lease outlived the retry"


def test_publish_retry_holds_the_lease_while_it_publishes() -> None:
    """Same rule, one handler over; the record is taken inside ``run_publish``."""
    graph = _publish_graph()
    seen: dict[str, Any] = {}
    captured: dict[str, Any] = {}

    async def _publish(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        seen["during"] = await leases.get_lease("t1")
        return {"publish_result": {"status": "failed", "error": "x"}, "publish_options": None}

    resolve_state, refify_updates = _passthrough_artifacts()
    with (
        _client(graph) as client,
        patch(_RUN_PUBLISH, side_effect=_publish),
        patch(_DB_UPSERT, new_callable=AsyncMock),
        patch(_EVENT_BUS) as bus,
        resolve_state,
        refify_updates,
        patch("backend.api.routes._wf_actions.asyncio", _AsyncioShim(captured)),
    ):
        bus.get_instance.return_value = MagicMock()
        resp = client.post("/api/workflow/publish-retry/t1")
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["status"] == "retrying", resp.json()
        _drive(captured)

    during = seen.get("during")
    assert during is not None, "no lease row while the retry was publishing"
    assert during.state is leases.LeaseState.HELD
    assert during.owner_id == leases.instance_identity()[0]
    after = asyncio.run(leases.get_lease("t1"))
    assert after.state is leases.LeaseState.RELEASED


# ── a refusal is not a gate, and a leak is impossible ────────────────────────


async def test_a_refused_lease_does_not_gate_the_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P2b ruling 2, on the helper the repair paths use.

    This is why "give them a lease" introduces no refusal branch: the only
    difference between a granted and a refused lease is whether a fence exists.
    """
    ran = False

    async def _boom(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("lease store unavailable")

    monkeypatch.setattr(leases, "start_lease", _boom)
    async with runner_module._execution_lease("t1") as lost:
        ran = True
        assert lost.is_set() is False, "a refused lease must not set the lost flag"
    assert ran, "the block must run even when the store cannot answer"


async def test_the_lease_is_released_when_the_work_raises() -> None:
    """The one new failure mode this change could have added: a leaked HELD row.

    A leaked row goes silent and expires, and the scan then considers a thread
    nobody is running -- so "release on every exit" is pinned, not trusted.
    """
    with pytest.raises(ValueError, match="work failed"):
        async with runner_module._execution_lease("t1"):
            raise ValueError("work failed")

    record = await leases.get_lease("t1")
    assert record is not None, "the lease was never taken"
    assert record.state is leases.LeaseState.RELEASED


async def test_the_fence_reaches_a_task_that_is_not_in_the_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No ``_background_tasks`` entry is needed to be fenced.

    This is the property that lets ripple-retry hold a lease while deliberately
    keeping out of the shared slot (§7.1: the slot is keyed by ``thread_id`` and
    three call sites cancel its occupant).  A heartbeat that ends *not cancelled*
    means ``renew`` answered False -- i.e. the row is no longer ours.
    """

    async def _already_finished() -> None:
        return None

    heartbeat = asyncio.create_task(_already_finished())
    await asyncio.sleep(0)  # let it finish before the fence registers on it
    monkeypatch.setattr(leases, "start_lease", AsyncMock(return_value=heartbeat))

    reached = asyncio.Event()
    with pytest.raises(asyncio.CancelledError):
        async with runner_module._execution_lease("t1") as lost:
            assert runner_module._background_tasks.get("t1") is None
            await asyncio.sleep(0.05)
            reached.set()
    assert lost.is_set(), "the fence did not fire for a registry-less task"
    assert not reached.is_set()


# ── the leak cannot become an automatic re-run ───────────────────────────────


def test_a_leaked_repair_lease_cannot_be_taken_over() -> None:
    """The pending node of either repair path is one the takeover registry refuses.

    A repair lease that leaks (``kill -9``) goes silent, expires, and is then
    *considered* by the scan -- acceptable only because the decision it reaches is
    ``refused``: ``publisher`` is the single irreversible node and ``ripple_gate``
    is where a person answers.  Without this, "the retry died and the scan re-ran
    the thread" could reach a real publish.
    """
    for pending in (("publisher",), ("ripple_gate",)):
        may_resume, worst = takeover_verdict(pending)
        assert may_resume is False, f"{pending} would have been resumed"
        assert worst is not None
        assert worst.value in ("irreversible", "needs_human")
