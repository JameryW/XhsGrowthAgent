"""S1 is wired in, and its wiring changes nothing.

The data plane could pass every test in ``tests/unit/db/test_execution_leases.py``
while never being called by production — the shape the repo has been bitten by
before (a declared mechanism with no caller). These tests close that gap from
both sides:

- the unified runner really does hold a lease *while the graph runs*, and hands
  it back when it finishes;
- when the lease store is broken outright, the runner still returns its result,
  because an observational lease must never gate execution.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from backend.api.routes import _runner as runner_module
from backend.db import execution_leases as leases
from backend.state.enums import WorkflowPhase

_LEASE_MODULE = "backend.db.execution_leases"
_POOL_READY = "backend.db.pool.is_pool_ready"


def _make_graph(result: dict, values: dict) -> MagicMock:
    snapshot = MagicMock()
    snapshot.values = values
    snapshot.next = []
    snapshot.tasks = []
    snapshot.interrupts = []
    snapshot.metadata = {}

    graph = MagicMock()
    graph.ainvoke = AsyncMock(return_value=result)
    graph.aget_state = AsyncMock(return_value=snapshot)
    graph.aupdate_state = AsyncMock()
    return graph


def _reset() -> None:
    leases._reset_memory_store()
    runner_module._background_tasks.clear()
    runner_module._last_status.clear()


async def test_runner_holds_the_lease_while_the_graph_runs(monkeypatch) -> None:
    """The lease exists during execution, not only after it."""
    monkeypatch.setattr(leases, "is_pool_ready", lambda: False)
    _reset()

    thread_id = "xhs_test_lease_wiring_001"
    config = {"configurable": {"thread_id": thread_id}}
    observed: dict[str, object] = {}

    result = {"phase": WorkflowPhase.SCOUTING.value}
    graph = _make_graph(result, {"phase": "scouting"})

    async def _observe_during_run(*_args: object, **_kwargs: object) -> dict:
        observed["lease"] = await leases.get_lease(thread_id)
        return result

    graph.ainvoke = AsyncMock(side_effect=_observe_during_run)

    with patch(_POOL_READY, return_value=False):
        await runner_module._run_graph_and_persist(thread_id, graph, config, None, source="start")

    during = observed["lease"]
    assert during is not None, "the runner never acquired a lease"
    assert during.state is leases.LeaseState.HELD
    assert during.owner_id == leases.instance_identity()[0]
    # ...and it is handed back rather than left to expire.
    after = await leases.get_lease(thread_id)
    assert after.state is leases.LeaseState.RELEASED
    _reset()


async def test_runner_still_runs_when_the_lease_store_fails() -> None:
    """An observational lease never gates the work it describes."""
    _reset()

    thread_id = "xhs_test_lease_wiring_002"
    config = {"configurable": {"thread_id": thread_id}}
    graph = _make_graph({"phase": WorkflowPhase.SCOUTING.value}, {"phase": "scouting"})

    with (
        patch(_POOL_READY, return_value=False),
        patch(
            f"{_LEASE_MODULE}.start_lease",
            new_callable=AsyncMock,
            side_effect=RuntimeError("lease store unavailable"),
        ),
        patch(
            f"{_LEASE_MODULE}.end_lease",
            new_callable=AsyncMock,
            side_effect=RuntimeError("lease store unavailable"),
        ),
    ):
        result = await runner_module._run_graph_and_persist(
            thread_id, graph, config, None, source="start"
        )

    assert result == {"phase": WorkflowPhase.SCOUTING.value}
    _reset()
