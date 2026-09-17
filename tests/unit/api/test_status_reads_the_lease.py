"""S2: status derivation answers from the lease; serialization stays process-local.

The question "is this thread running" used to be asked nine times in two
modules, each time by reading this process's task registries -- so a process
that never had the task answered "no", and the workflow was reported stale
while another replica was happily running it. ``has_active_execution`` answers
from the lease instead, and these tests pin both halves of that: the lease
decides the reported verdict, while the guards that decide whether to *start*
work keep asking this process.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import timedelta

import pytest

from backend.api.routes import _runner, _wf_runtime
from backend.db import execution_leases as leases
from backend.state.machine import WorkflowStatus, derive_status

_OTHER_INSTANCE = "other-host:4242:deadbeef"


class _Snapshot:
    """Minimal StateSnapshot stand-in: enough for derive_status."""

    def __init__(self, next_nodes: tuple[str, ...] = (), values: dict | None = None) -> None:
        self.values = values if values is not None else {"session_id": "s1"}
        self.next = next_nodes
        self.interrupts = ()


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(leases, "is_pool_ready", lambda: False)
    leases._reset_memory_store()
    _runner._background_tasks.clear()
    _runner._active_sync_executions.clear()
    yield
    leases._reset_memory_store()
    _runner._background_tasks.clear()
    _runner._active_sync_executions.clear()


async def _seed_local_task(thread_id: str) -> asyncio.Task[None]:
    """Register a not-yet-done task in this process, as a live run would."""

    async def _hang() -> None:
        await asyncio.sleep(30)

    task = asyncio.create_task(_hang())
    _runner._background_tasks[thread_id] = task
    await asyncio.sleep(0)
    return task


async def _drop_local_task(task: asyncio.Task[None]) -> None:
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    _runner._background_tasks.clear()


class TestTheLeaseDecidesTheVerdict:
    async def test_a_lease_held_by_another_instance_counts_as_active(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The case the registries cannot see: someone else is running it."""
        monkeypatch.setattr(leases, "_instance_id", _OTHER_INSTANCE)
        await leases.acquire("t1")

        assert _runner.process_has_active_task("t1") is False
        assert await _runner.has_active_execution("t1") is True

    async def test_a_silent_lease_does_not_count_as_active(self) -> None:
        await leases.acquire("t1")
        # Age the row past its own budget without touching ``state``.
        monkeypatch_now = leases._utcnow() + timedelta(seconds=leases.LEASE_TTL_SECONDS + 1)
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(leases, "_utcnow", lambda: monkeypatch_now)
            assert await _runner.has_active_execution("t1") is False

    async def test_a_released_lease_does_not_count_as_active(self) -> None:
        await leases.acquire("t1")
        assert await leases.release("t1") is True

        assert await _runner.has_active_execution("t1") is False

    async def test_the_verdict_is_what_derive_status_reports(self) -> None:
        """Same snapshot, same next nodes -- only the lease differs."""
        snapshot = _Snapshot(next_nodes=("scout",))

        assert derive_status(snapshot, has_active_task=False) is WorkflowStatus.STALE

        await leases.acquire("t1")
        has_active = await _runner.has_active_execution("t1")
        assert has_active is True
        assert derive_status(snapshot, has_active_task=has_active) is WorkflowStatus.RUNNING


class TestThisProcessStillAnswersForThisProcess:
    async def test_a_local_task_is_active_even_with_no_lease(self) -> None:
        """A live run must never be reported stale just because the lease failed."""
        task = await _seed_local_task("t1")
        try:
            assert await leases.get_lease("t1") is None
            assert await _runner.has_active_execution("t1") is True
        finally:
            await _drop_local_task(task)

    async def test_a_broken_lease_read_falls_back_to_the_process(self) -> None:
        """A store error must degrade to today's answer, not to "nothing runs"."""

        async def _boom(thread_id: str) -> bool:
            raise RuntimeError("lease store down")

        task = await _seed_local_task("t1")
        try:
            with pytest.MonkeyPatch.context() as mp:
                mp.setattr(leases, "thread_is_held", _boom)
                assert await _runner.has_active_execution("t1") is True
        finally:
            await _drop_local_task(task)

    async def test_a_broken_lease_read_answers_not_held(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With nothing local to fall back on, a broken read must not invent a holder.

        The OR above covers the case the store cannot answer for -- this process.
        Any *other* claim it cannot verify must not be made up: answering "held"
        on a store error would report every thread as running, and the orphan
        reporting this slice exists to provide would go quiet exactly when the
        store is least trustworthy.
        """

        async def _boom(thread_id: str) -> bool:
            raise RuntimeError("lease store down")

        monkeypatch.setattr(leases, "thread_is_held", _boom)
        assert await _runner.has_active_execution("t1") is False

    async def test_the_two_questions_diverge_on_a_foreign_lease(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Why the serialization guards keep asking this process.

        A foreign live lease says "someone is running it" (so it is not an
        orphan) but says nothing about whether *we* already have a task for it
        -- acting on the ownership answer would let a retry start a second
        execution here.
        """
        monkeypatch.setattr(leases, "_instance_id", _OTHER_INSTANCE)
        await leases.acquire("t1")

        assert await _runner.has_active_execution("t1") is True
        assert _runner.process_has_active_task("t1") is False


class TestLocalRegistriesStillCount:
    async def test_a_sync_execution_counts_without_any_lease(self) -> None:
        """The second registry term, and the one a lease cannot stand in for.

        Sync sources do call ``start_lease``, but the registry is written
        *unconditionally* while the lease write is best-effort -- so a store
        failure must not be the thing that turns this process's own in-flight
        run into a "stale" verdict.
        """
        assert await leases.get_lease("t1") is None
        _runner._active_sync_executions.add("t1")

        assert _runner.process_has_active_task("t1") is True
        assert await _runner.has_active_execution("t1") is True


class TestOrphanDetection:
    async def test_a_foreign_live_lease_is_not_an_orphan(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(leases, "_instance_id", _OTHER_INSTANCE)
        await leases.acquire("t1")

        assert await _wf_runtime._is_orphan_running("t1", "running") is False

    async def test_no_lease_at_all_is_an_orphan(self) -> None:
        assert await _wf_runtime._is_orphan_running("t1", "running") is True

    async def test_a_silent_lease_is_an_orphan(self) -> None:
        await leases.acquire("t1")
        aged = leases._utcnow() + timedelta(seconds=leases.LEASE_TTL_SECONDS + 1)
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(leases, "_utcnow", lambda: aged)
            assert await _wf_runtime._is_orphan_running("t1", "running") is True

    async def test_a_row_that_is_not_running_is_never_an_orphan(self) -> None:
        assert await _wf_runtime._is_orphan_running("t1", "completed") is False
