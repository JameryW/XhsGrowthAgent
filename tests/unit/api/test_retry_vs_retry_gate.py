"""Retry-vs-retry serialization: one repair per thread at a time, per process.

``docs/execution-plane.md`` §7.1 registered exactly one open input: two repairs
could take flight together.  The slot cannot answer it (one task per thread, and
three call sites cancel the occupant), ``_detached_tasks`` answers only "what must
the preempting canceller stop", and the lease cannot separate two holders inside
the same process (``owner_id`` is the instance).  This file pins the third answer
that was added -- ``_runner._retry_tasks`` -- and the two entry points that read
it:

- each entry refuses while *either* repair is being started or is running;
- the claim is taken **before** ``create_task``, synchronously, so two requests
  that both passed the read-only guard cannot both start a task -- the loser
  never creates one;
- the claim is released on every settle path -- including a task cancelled before
  its first turn, where no ``finally`` inside the coroutine would run;
- the gate stays a repair-only answer: it is never OR-ed into
  ``process_has_active_task`` / ``has_active_execution`` (those are read by twelve
  call sites; a repair in flight is not "the workflow is running").
"""

from __future__ import annotations

import ast
import asyncio
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langgraph.store.memory import InMemoryStore

from backend.api.routes import _runner, _wf_actions
from backend.db import execution_leases as leases

_ROOT = Path(__file__).resolve().parents[3]
_RUNNER = _ROOT / "backend/api/routes/_runner.py"
_ACTIONS = _ROOT / "backend/api/routes/_wf_actions.py"
_ARTIFACTS = "backend.state.artifacts"
_GATEWAY = "backend.tools.runtime.bridge.shared_gateway"
_RUN_PUBLISH = "backend.api.routes._wf_actions.run_publish"
_DB_UPSERT = "backend.api.routes._wf_actions._db_upsert"
_EVENT_BUS = "backend.api.routes._wf_actions.EventBusService"
_OWNED = "backend.api.routes._wf_actions.assert_thread_owned"
_USER = {"id": "user-test"}
_REFUSAL = "工作流正在运行，无法重试。"


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Memory-backed leases and empty registries, restored afterwards."""
    monkeypatch.setattr(leases, "is_pool_ready", lambda: False)
    leases._reset_memory_store()
    _runner._background_tasks.clear()
    _runner._active_sync_executions.clear()
    _runner._retry_tasks.clear()
    yield
    leases._reset_memory_store()
    _runner._background_tasks.clear()
    _runner._active_sync_executions.clear()
    _runner._retry_tasks.clear()


def _request(graph: MagicMock) -> MagicMock:
    request = MagicMock()
    request.app.state.graph = graph
    request.headers = {"content-type": "application/json"}
    request.json = AsyncMock(return_value={})
    return request


def _graph() -> MagicMock:
    """One checkpoint that satisfies both repair entry points."""
    snapshot = MagicMock()
    snapshot.values = {
        "session_id": "t1",
        "account_id": "acc1",
        "phase": "planning",
        "ripple_reason": "timeout",
        "content_plan": {"selected_topic": "露营咖啡", "hashtags": []},
        "copy_content": {"selected_title": "t", "body_text": "b"},
        "publish_result": {"status": "failed", "post_id": ""},
    }
    snapshot.next = ("ripple_gate",)
    snapshot.tasks = ()
    snapshot.interrupts = ()

    graph = MagicMock()
    graph.store = InMemoryStore()
    graph.aget_state = AsyncMock(return_value=snapshot)
    graph.aupdate_state = AsyncMock()
    return graph


def _identity_artifacts() -> tuple[Any, Any]:
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


def _tool_result(capability: str, value: dict[str, Any]) -> Any:
    from backend.tools.runtime.models import ToolResult

    return ToolResult(capability=capability, ok=True, value=value)


def _blocked_gateway(entered: asyncio.Event, release: asyncio.Event, calls: list[str]) -> MagicMock:
    """A Gateway whose two ripple capabilities wait until *release* is set."""
    gateway = MagicMock()

    async def _invoke(
        capability: str, payload: Any = None, *, thread_id: str = "", **_kwargs: Any
    ) -> Any:
        calls.append(capability)
        entered.set()
        await release.wait()
        if capability == "ripple.predict_spread":
            return _tool_result(capability, {"ripple_prediction": {"viral_probability": 0.4}})
        return _tool_result(capability, {"ripple_pmf": {"pmf_score": 0.6}})

    gateway.invoke = _invoke
    return gateway


# ── the gate: one repair at a time ───────────────────────────────────────────


async def test_a_second_ripple_retry_is_refused_while_one_is_in_flight() -> None:
    graph = _graph()
    request = _request(graph)
    entered, release = asyncio.Event(), asyncio.Event()
    calls: list[str] = []
    resolve_state, refify_updates = _identity_artifacts()

    with (
        patch(_OWNED, new_callable=AsyncMock),
        patch(_GATEWAY, return_value=_blocked_gateway(entered, release, calls)),
        resolve_state,
        refify_updates,
    ):
        first = await _wf_actions.retry_ripple_analysis("t1", request, _USER)
        assert first.data["status"] == "retrying", first.data
        task = _runner._retry_tasks["t1"]
        await entered.wait()

        before = len(calls)
        second = await _wf_actions.retry_ripple_analysis("t1", request, _USER)
        assert second.data["status"] == "skipped", second.data
        assert second.data["message"] == _REFUSAL
        assert len(calls) == before, "the refused retry reached the simulation"

        release.set()
        await asyncio.wait_for(task, timeout=2)

    assert _runner.retry_in_flight("t1") is False


async def test_a_ripple_retry_blocks_a_publish_retry() -> None:
    graph = _graph()
    request = _request(graph)
    entered, release = asyncio.Event(), asyncio.Event()
    calls: list[str] = []
    resolve_state, refify_updates = _identity_artifacts()

    with (
        patch(_OWNED, new_callable=AsyncMock),
        patch(_GATEWAY, return_value=_blocked_gateway(entered, release, calls)),
        patch(_RUN_PUBLISH, new_callable=AsyncMock) as publish,
        patch(_DB_UPSERT, new_callable=AsyncMock),
        patch(_EVENT_BUS) as bus,
        resolve_state,
        refify_updates,
    ):
        bus.get_instance.return_value = MagicMock()
        first = await _wf_actions.retry_ripple_analysis("t1", request, _USER)
        assert first.data["status"] == "retrying", first.data
        task = _runner._retry_tasks["t1"]
        await entered.wait()

        second = await _wf_actions.retry_publish("t1", request, _USER)
        assert second.data["status"] == "skipped", second.data
        assert second.data["message"] == _REFUSAL
        publish.assert_not_awaited()

        release.set()
        await asyncio.wait_for(task, timeout=2)


async def test_a_publish_retry_blocks_a_ripple_retry() -> None:
    graph = _graph()
    request = _request(graph)
    entered, release = asyncio.Event(), asyncio.Event()
    resolve_state, refify_updates = _identity_artifacts()
    gateway = MagicMock()
    gateway.invoke = AsyncMock()

    async def _publish(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        entered.set()
        await release.wait()
        return {"publish_result": {"status": "failed", "error": "x"}, "publish_options": None}

    with (
        patch(_OWNED, new_callable=AsyncMock),
        patch(_RUN_PUBLISH, side_effect=_publish),
        patch(_DB_UPSERT, new_callable=AsyncMock),
        patch(_EVENT_BUS) as bus,
        patch(_GATEWAY, return_value=gateway),
        resolve_state,
        refify_updates,
    ):
        bus.get_instance.return_value = MagicMock()
        first = await _wf_actions.retry_publish("t1", request, _USER)
        assert first.data["status"] == "retrying", first.data
        task = _runner._retry_tasks["t1"]
        await entered.wait()

        second = await _wf_actions.retry_ripple_analysis("t1", request, _USER)
        assert second.data["status"] == "skipped", second.data
        gateway.invoke.assert_not_awaited()

        release.set()
        await asyncio.wait_for(task, timeout=2)


async def test_two_concurrent_requests_only_one_starts() -> None:
    """Both pass the read-only guard; the claim makes exactly one of them win.

    The early guard cannot close this window by itself -- it runs before the
    state reads.  ``claim_retry`` is synchronous and precedes ``create_task``, so
    the event loop serializes the two claims and the loser creates no task at all.
    """
    graph = _graph()
    request = _request(graph)
    entered, release = asyncio.Event(), asyncio.Event()
    calls: list[str] = []
    resolve_calls = {"n": 0}
    both_in = asyncio.Event()

    async def _slow_resolve(_store: Any, _tid: str, values: Any) -> Any:
        resolve_calls["n"] += 1
        if resolve_calls["n"] >= 2:
            both_in.set()
        if resolve_calls["n"] <= 2:
            await both_in.wait()
        return values

    with (
        patch(_OWNED, new_callable=AsyncMock),
        patch(_GATEWAY, return_value=_blocked_gateway(entered, release, calls)),
        patch(f"{_ARTIFACTS}.resolve_state", side_effect=_slow_resolve),
        patch(
            f"{_ARTIFACTS}.refify_updates",
            AsyncMock(side_effect=lambda _store, _tid, updates, **_kw: updates),
        ),
    ):
        first, second = await asyncio.gather(
            _wf_actions.retry_ripple_analysis("t1", request, _USER),
            _wf_actions.retry_ripple_analysis("t1", request, _USER),
        )
        statuses = sorted([first.data["status"], second.data["status"]])
        assert statuses == ["retrying", "skipped"], statuses

        holder = _runner._retry_tasks["t1"]
        await entered.wait()
        release.set()
        await asyncio.wait_for(holder, timeout=2)

    assert len([call for call in calls if call == "ripple.predict_spread"]) == 1
    assert _runner.retry_in_flight("t1") is False


async def test_two_concurrent_publish_retries_only_one_starts() -> None:
    """The publish entry has the same race, and its own claim to close it.

    Without a *behavioural* case here, deleting the publish entry's claim would
    only move a static counter -- the double-publish risk itself would be
    unpinned.
    """
    graph = _graph()
    request = _request(graph)
    entered, release = asyncio.Event(), asyncio.Event()
    resolve_calls = {"n": 0}
    both_in = asyncio.Event()

    async def _slow_resolve(_store: Any, _tid: str, values: Any) -> Any:
        resolve_calls["n"] += 1
        if resolve_calls["n"] >= 2:
            both_in.set()
        if resolve_calls["n"] <= 2:
            await both_in.wait()
        return values

    async def _publish(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        entered.set()
        await release.wait()
        return {"publish_result": {"status": "failed", "error": "x"}, "publish_options": None}

    with (
        patch(_OWNED, new_callable=AsyncMock),
        patch(_RUN_PUBLISH, side_effect=_publish) as publish,
        patch(_DB_UPSERT, new_callable=AsyncMock),
        patch(_EVENT_BUS) as bus,
        patch(f"{_ARTIFACTS}.resolve_state", side_effect=_slow_resolve),
        patch(
            f"{_ARTIFACTS}.refify_updates",
            AsyncMock(side_effect=lambda _store, _tid, updates, **_kw: updates),
        ),
    ):
        bus.get_instance.return_value = MagicMock()
        first, second = await asyncio.gather(
            _wf_actions.retry_publish("t1", request, _USER),
            _wf_actions.retry_publish("t1", request, _USER),
        )
        statuses = sorted([first.data["status"], second.data["status"]])
        assert statuses == ["retrying", "skipped"], statuses

        holder = _runner._retry_tasks["t1"]
        await entered.wait()
        release.set()
        await asyncio.wait_for(holder, timeout=2)

    publish.assert_awaited_once()
    assert _runner.retry_in_flight("t1") is False


async def test_the_gate_opens_again_after_the_retry_finishes() -> None:
    graph = _graph()
    request = _request(graph)
    calls: list[str] = []

    async def _invoke(
        capability: str, payload: Any = None, *, thread_id: str = "", **_kwargs: Any
    ) -> Any:
        calls.append(capability)
        if capability == "ripple.predict_spread":
            return _tool_result(capability, {"ripple_prediction": {"viral_probability": 0.4}})
        return _tool_result(capability, {"ripple_pmf": {"pmf_score": 0.6}})

    gateway = MagicMock()
    gateway.invoke = _invoke
    resolve_state, refify_updates = _identity_artifacts()

    with (
        patch(_OWNED, new_callable=AsyncMock),
        patch(_GATEWAY, return_value=gateway),
        resolve_state,
        refify_updates,
    ):
        first = await _wf_actions.retry_ripple_analysis("t1", request, _USER)
        assert first.data["status"] == "retrying", first.data
        await asyncio.wait_for(_runner._retry_tasks["t1"], timeout=2)
        assert _runner.retry_in_flight("t1") is False

        second = await _wf_actions.retry_ripple_analysis("t1", request, _USER)
        assert second.data["status"] == "retrying", second.data
        await asyncio.wait_for(_runner._retry_tasks["t1"], timeout=2)
        assert calls.count("ripple.predict_spread") == 2


# ── the claim is released on every settle path ──────────────────────────────


async def test_a_cancelled_retry_releases_the_gate() -> None:
    """Cancellation is how a resume stops a repair -- and it must free the gate."""
    graph = _graph()
    request = _request(graph)
    entered, release = asyncio.Event(), asyncio.Event()
    calls: list[str] = []
    resolve_state, refify_updates = _identity_artifacts()

    with (
        patch(_OWNED, new_callable=AsyncMock),
        patch(_GATEWAY, return_value=_blocked_gateway(entered, release, calls)),
        resolve_state,
        refify_updates,
    ):
        first = await _wf_actions.retry_ripple_analysis("t1", request, _USER)
        assert first.data["status"] == "retrying", first.data
        task = _runner._retry_tasks["t1"]
        await entered.wait()

        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.sleep(0)

        assert _runner._retry_tasks.get("t1") is None, "the claim outlived the task"
        assert _runner.retry_in_flight("t1") is False

        release.set()
        second = await _wf_actions.retry_ripple_analysis("t1", request, _USER)
        assert second.data["status"] == "retrying", second.data
        await asyncio.wait_for(_runner._retry_tasks["t1"], timeout=2)


async def test_a_claim_is_released_when_the_task_is_cancelled_before_its_first_turn() -> None:
    """A ``finally`` would not run here: the coroutine never gets a turn.

    This is why the cleanup is a done callback.  Without it the thread would stay
    gated until the process restarted.
    """

    async def _never() -> None:
        await asyncio.Event().wait()

    task = asyncio.create_task(_never())
    assert _runner.claim_retry("t1") is True
    _runner.attach_retry("t1", task)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    assert _runner._retry_tasks.get("t1") is None
    assert _runner.retry_in_flight("t1") is False


async def test_abandon_claim_opens_the_gate() -> None:
    """``create_task`` raising must not leave the thread gated forever."""
    assert _runner.claim_retry("t1") is True
    assert _runner.retry_in_flight("t1") is True
    _runner.abandon_claim("t1")
    assert _runner.retry_in_flight("t1") is False
    assert _runner.claim_retry("t1") is True
    _runner.abandon_claim("t1")


async def test_a_handler_that_cannot_create_the_task_gives_the_claim_back() -> None:
    """The abandon path, exercised through the handler rather than the helper."""

    class _NoCreateTask:
        def __getattr__(self, name: str) -> Any:
            return getattr(asyncio, name)

        def create_task(self, coro: Any, **_kwargs: Any) -> Any:
            coro.close()
            raise RuntimeError("event loop is closed")

    graph = _graph()
    request = _request(graph)
    resolve_state, refify_updates = _identity_artifacts()

    with (
        patch(_OWNED, new_callable=AsyncMock),
        patch(_GATEWAY, return_value=MagicMock()),
        patch("backend.api.routes._wf_actions.asyncio", _NoCreateTask()),
        resolve_state,
        refify_updates,
        pytest.raises(RuntimeError, match="event loop is closed"),
    ):
        await _wf_actions.retry_ripple_analysis("t1", request, _USER)

    assert _runner.retry_in_flight("t1") is False
    assert _runner._retry_tasks.get("t1") is None


async def test_claim_retry_refuses_a_second_task_for_a_live_thread() -> None:
    async def _never() -> None:
        await asyncio.Event().wait()

    first = asyncio.create_task(_never())
    try:
        assert _runner.claim_retry("t1") is True
        _runner.attach_retry("t1", first)
        assert _runner.claim_retry("t1") is False
        assert _runner._retry_tasks["t1"] is first
    finally:
        first.cancel()
        await asyncio.gather(first, return_exceptions=True)


async def test_forget_retry_does_not_pop_a_newer_entry() -> None:
    """The identity guard: a stale callback must not remove the next claim."""

    async def _never() -> None:
        await asyncio.Event().wait()

    old = asyncio.create_task(_never())
    new = asyncio.create_task(_never())
    try:
        assert _runner.claim_retry("t1") is True
        _runner.attach_retry("t1", old)
        _runner._retry_tasks["t1"] = new
        _runner._forget_retry("t1", old)
        assert _runner._retry_tasks.get("t1") is new
    finally:
        old.cancel()
        new.cancel()
        await asyncio.gather(old, new, return_exceptions=True)


# ── the gate stays repair-scoped ────────────────────────────────────────────


def _functions(tree: ast.Module) -> list[ast.AsyncFunctionDef | ast.FunctionDef]:
    return [
        node for node in ast.walk(tree) if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
    ]


def test_the_retry_gate_is_not_a_general_busy_answer() -> None:
    """Nothing widens the two busy answers -- neither the table nor the predicate.

    Checking only the literal ``_retry_tasks`` is not enough: OR-ing
    ``retry_in_flight`` into ``has_active_execution`` never writes the table's
    name, so this scan has to know the predicate spelling too (a mutation that
    did exactly that stayed green before this line existed).
    """
    tree = ast.parse(_RUNNER.read_text(encoding="utf-8"))
    busy = {"process_has_active_task", "has_active_execution"}
    leaked = []
    for func in _functions(tree):
        if func.name not in busy:
            continue
        body = ast.unparse(func)
        if "_retry_tasks" in body or "retry_in_flight" in body:
            leaked.append(func.name)
    assert leaked == [], f"the gate widened a general busy answer: {leaked}"


def test_both_repair_handlers_read_and_claim_the_gate() -> None:
    tree = ast.parse(_ACTIONS.read_text(encoding="utf-8"))
    by_name = {func.name: func for func in _functions(tree)}
    for handler in ("retry_ripple_analysis", "retry_publish"):
        body = ast.unparse(by_name[handler])
        assert body.count("retry_in_flight(") == 1, handler
        assert body.count("claim_retry(") == 1, handler


def test_the_gate_has_two_write_sites_and_one_claimant_cleanup() -> None:
    """Claim and attach are the only writes; both live in ``_runner``.

    The handlers never touch the table themselves -- that is what keeps the
    claim's shape (placeholder then task) an invariant of one module.
    """
    tree = ast.parse(_RUNNER.read_text(encoding="utf-8"))
    by_name = {func.name: func for func in _functions(tree)}

    def _writes(func: ast.AsyncFunctionDef | ast.FunctionDef) -> int:
        total = 0
        for node in ast.walk(func):
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if isinstance(target, ast.Subscript):
                    base = getattr(target.value, "attr", None) or getattr(target.value, "id", None)
                    if base == "_retry_tasks":
                        total += 1
        return total

    assert _writes(by_name["claim_retry"]) == 1
    assert _writes(by_name["attach_retry"]) == 1
    assert _writes(by_name["abandon_claim"]) == 0

    attach_body = ast.unparse(by_name["attach_retry"])
    assert "add_done_callback" in attach_body
    forget = by_name["_forget_retry"]
    assert "pop" in ast.unparse(forget)
    guarded = any(
        isinstance(node, ast.If) and any(isinstance(sub, ast.Is) for sub in ast.walk(node.test))
        for node in ast.walk(forget)
    )
    assert guarded, "the cleanup has no identity guard"
