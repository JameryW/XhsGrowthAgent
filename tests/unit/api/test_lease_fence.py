"""The lease fence (P2b-S3).

A lease only excludes another owner if the old owner stops when it loses one.
S1 recorded leases and logged a lost one; S2 read them for status. Neither made
a lost lease *stop* anything -- which was harmless while nothing acted on a
lease, and is not harmless now that the scan takes an expired one over: "the
old owner kept going" and "no two writers on one checkpoint" cannot both hold.

``_fence_on_lost_lease`` draws the line between the two ways a heartbeat ends.
It ends by itself when ``renew`` answers False -- the row is not ours any more,
so the run must stop. It is cancelled by ``end_lease`` on the normal path --
the run is finishing, and fencing there would cancel every run as it completed.
"""

from __future__ import annotations

import asyncio
import contextlib
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.api.routes import _runner as runner_module


@pytest.fixture(autouse=True)
def _isolate_runner_state():
    """Keep module-level runner registries clean across tests."""
    runner_module._background_tasks.clear()
    runner_module._last_status.clear()
    yield
    runner_module._background_tasks.clear()
    runner_module._last_status.clear()


async def _heartbeat_that_ends() -> None:
    """Stands in for ``renew`` answering False."""
    await asyncio.sleep(0)


async def _heartbeat_that_runs() -> None:
    await asyncio.sleep(30)


class TestTheFence:
    async def test_a_heartbeat_that_ends_by_itself_cancels_the_run(self):
        async def _run() -> None:
            heartbeat = asyncio.create_task(_heartbeat_that_ends())
            runner_module._fence_on_lost_lease("t1", heartbeat)
            # Outliving the heartbeat is the entire scenario.
            await asyncio.sleep(30)

        task = asyncio.create_task(_run())
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=5)

    async def test_a_cancelled_heartbeat_does_not_fence(self):
        """``end_lease`` cancels the heartbeat on the normal path. Fencing there
        would cancel every run at the moment it finished."""

        async def _run() -> bool:
            heartbeat = asyncio.create_task(_heartbeat_that_runs())
            lost = runner_module._fence_on_lost_lease("t1", heartbeat)
            heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat
            await asyncio.sleep(0.01)
            return lost.is_set()

        assert await asyncio.wait_for(asyncio.create_task(_run()), timeout=5) is False

    async def test_the_event_is_set_before_the_cancellation_is_delivered(self):
        """The ``CancelledError`` handler reads this event to decide whether it
        may write a status, so it has to be set by the time cancellation lands."""
        seen: list[bool] = []

        async def _run() -> None:
            heartbeat = asyncio.create_task(_heartbeat_that_ends())
            lost = runner_module._fence_on_lost_lease("t1", heartbeat)
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                seen.append(lost.is_set())
                raise

        task = asyncio.create_task(_run())
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=5)
        assert seen == [True]

    async def test_a_run_that_already_finished_is_not_cancelled(self):
        """The callback fires whenever the heartbeat ends, including after the
        run returned. Cancelling a finished task is not possible -- but the
        guard has to be there for the callback not to try."""

        async def _run() -> None:
            heartbeat = asyncio.create_task(_heartbeat_that_ends())
            runner_module._fence_on_lost_lease("t1", heartbeat)

        task = asyncio.create_task(_run())
        await asyncio.wait_for(task, timeout=5)
        await asyncio.sleep(0.05)  # let the heartbeat end and the callback fire

        assert task.done() and not task.cancelled()


class TestAFencedRunWritesNoStatus:
    """The status the run would otherwise write is ``cancelled`` -- and that
    would erase the takeover that just started, because the instance holding
    the lease owns the row now."""

    async def test_it_does_not_persist_cancelled(self, monkeypatch: pytest.MonkeyPatch):
        thread_id = "xhs_test_fence_writes_nothing"
        config = {"configurable": {"thread_id": thread_id}}

        snapshot = MagicMock()
        snapshot.values = {"session_id": thread_id, "phase": "creating"}
        snapshot.next = ["copywriter"]
        snapshot.tasks = []
        snapshot.interrupts = []
        snapshot.metadata = {}

        async def _ainvoke(input_data, config):
            await asyncio.sleep(30)  # the fence cancels us here
            return {}

        graph = MagicMock()
        graph.ainvoke = _ainvoke
        graph.aget_state = AsyncMock(return_value=snapshot)
        graph.aupdate_state = AsyncMock()

        upserts: list[dict] = []

        async def _capture_upsert(tid, **fields):
            upserts.append(fields)

        async def _start_lease(tid, **kwargs):
            async def _ends() -> None:
                await asyncio.sleep(0)

            return asyncio.create_task(_ends())

        monkeypatch.setattr(runner_module, "_db_upsert", _capture_upsert)
        monkeypatch.setattr("backend.db.execution_leases.start_lease", _start_lease)

        async def _registered_run() -> None:
            # _run_graph_and_persist only writes when it is the registered task
            # for the thread. Registering it is what makes an empty `upserts`
            # evidence for the lease guard rather than for that other guard.
            runner_module._background_tasks[thread_id] = asyncio.current_task()
            await runner_module._run_graph_and_persist(
                thread_id, graph, config, None, source="start"
            )

        task = asyncio.create_task(_registered_run())
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=5)

        assert upserts == []
