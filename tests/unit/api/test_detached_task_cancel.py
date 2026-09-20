"""取消一个刻意不在槽里的任务（09-20-retry-cancel-must-wait）。

``_runner._background_tasks`` 每 thread 一槽，三个调用点会取消坐在里面的那一个，
所以 ripple-retry 不进那个槽 —— 这条裁定（#634）**没有变**。变的是「不在槽里」
过去同时意味着「够不着」：resume 可以在 ripple-retry 还在写同一个 checkpoint 时起来，
而没有任何东西叫得停它。

**租约不是那扇门。** 两条授予路径都把「同一 ``owner_id``」当成可授予
（``backend/db/execution_leases.py:301``、``backend/db/execution_leases.py:384``），
而 ``owner_id`` 认的是**进程**、不是任务 ⇒ 同进程的第二个执行者拿到的是 ``granted``。
这条是本片必须新增一张表的依据，也是下面第三个用例的前提。

**「等」是承重的。** 被取消的协程退场时会跑 ``_execution_lease`` 的 ``finally`` →
``end_lease`` → ``release``，而 ``release`` 只按 ``owner_id`` 认领 ⇒ 它置的是
**接任者刚拿到的那一行**。所以 ``cancel_detached_and_wait`` 不只是取消，它等。
第四个用例把两侧都测出来：不等 ⇒ 接任者的 ``renew`` 是 ``LOST``（它会被自己的栅栏
取消）；等 ⇒ ``RENEWED``。
"""

from __future__ import annotations

import asyncio
import contextlib
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.api.routes import _runner, _wf_runtime
from backend.db import execution_leases as leases

_TID = "t1"


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch):
    """Memory-backed leases（内存后端答不出 ``UNKNOWN``，答案因此是确定的）与空登记表。"""
    monkeypatch.setattr(leases, "is_pool_ready", lambda: False)
    _runner._background_tasks.clear()
    _runner._detached_tasks.clear()
    _runner._active_sync_executions.clear()
    leases._reset_memory_store()
    yield
    _runner._background_tasks.clear()
    _runner._detached_tasks.clear()
    _runner._active_sync_executions.clear()
    leases._reset_memory_store()


async def _forever(started: asyncio.Event | None = None, slow_unwind: bool = False) -> None:
    """一个不会自己结束的任务；被取消时可选地慢一点退场（真代码的 finally 里有 await）。"""
    if started is not None:
        started.set()
    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        if slow_unwind:
            await asyncio.sleep(0.05)
        raise


async def _holding_a_lease(started: asyncio.Event, slow_unwind: bool) -> None:
    """持租约不放 —— 形状与 ``_run_retry`` 一样（整段落在 ``_execution_lease`` 里）。"""
    async with _runner._execution_lease(_TID) as lease:
        assert lease.outcome is leases.AcquireOutcome.GRANTED, lease.outcome
        started.set()
        await _forever(slow_unwind=slow_unwind)


def _graph() -> MagicMock:
    snapshot = MagicMock()
    snapshot.values = {"session_id": _TID, "phase": "publishing"}
    snapshot.next = ()
    snapshot.tasks = ()
    snapshot.interrupts = ()
    graph = MagicMock()
    graph.store = None
    graph.aget_state = AsyncMock(return_value=snapshot)
    graph.ainvoke = AsyncMock(return_value={})
    graph.aupdate_state = AsyncMock()
    return graph


async def _resume(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_wf_runtime, "_db_upsert", AsyncMock())
    monkeypatch.setattr(_runner, "_run_graph_and_persist", AsyncMock())
    await _wf_runtime._start_resume_task(
        _TID, _graph(), {"configurable": {"thread_id": _TID}}, "publishing"
    )


async def test_a_resume_reaches_the_detached_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    """登记过的任务被取消，**且在 resume 返回之前就已经退完**。

    后半句才是这个用例的重点：``_start_resume_task`` 对槽那一路只 ``cancel()``、
    不等（那一路的退场语义由 ``_run_graph_and_persist`` 的 ``CancelledError`` 分支钉着，
    见 ``docs/execution-plane.md`` §7.1）。detached 这一路必须等，理由在第四个用例。
    """
    started = asyncio.Event()
    retry = asyncio.create_task(_forever(started), name=f"ripple-retry-{_TID}")
    _runner._detached_tasks[_TID] = retry
    await started.wait()

    await _resume(monkeypatch)

    assert retry.done(), "resume 返回时重试还在退场 —— 那就没有等到"
    assert retry.cancelled()


async def test_an_unregistered_task_is_left_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    """正对照：取消瞄准的是**登记表**，不是「所有名字对得上的任务」。

    这个旁观者连 ``name=`` 都和真的一样 —— 差别只有「没进表」。所以一条按名字扫
    ``asyncio.all_tasks()`` 的实现会在这里红。
    """
    started = asyncio.Event()
    bystander = asyncio.create_task(_forever(started), name=f"ripple-retry-{_TID}")
    await started.wait()

    try:
        await _resume(monkeypatch)
        assert not bystander.done(), "没进表的任务也被取消了 —— 靶子不是这张表"
    finally:
        bystander.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await bystander


async def test_the_lease_cannot_see_a_second_executor_in_this_process() -> None:
    """本片那条**依据**的可执行版本：同进程第二个持有者拿到的是 ``granted``。

    没有这一条，「为什么要新增一张表」就只能靠读 SQL 相信。两个任务各自
    ``_execution_lease``，第一个还没退，第二个就被授予 —— 因为 ``owner_id``
    认的是进程（``backend/db/execution_leases.py:301`` / ``:384``）。
    """
    first_entered = asyncio.Event()
    second_entered = asyncio.Event()
    first = asyncio.create_task(_holding_a_lease(first_entered, slow_unwind=False))
    await first_entered.wait()

    second = asyncio.create_task(_holding_a_lease(second_entered, slow_unwind=False))
    await asyncio.wait_for(second_entered.wait(), timeout=5)

    for task in (first, second):
        task.cancel()
    await asyncio.gather(first, second, return_exceptions=True)


async def test_without_the_wait_the_successor_fences_itself() -> None:
    """★ 「等」为什么是承重的：不等的时候，接任者会被自己的栅栏取消。

    这条**故意测一个坏的关法**，因为它是 ``cancel_detached_and_wait`` 里那个 ``await``
    的理由。它红的方式有两种，两种都值得看：要么 ``end_lease`` 变成了按任务计数、
    要么 ``release`` 变得认得出「这一行还有人用」—— 那时这个 ``await`` 就不再承重，
    该回来把它的 docstring 与 §7.1 一起改掉。
    """
    started = asyncio.Event()
    retry = asyncio.create_task(_holding_a_lease(started, slow_unwind=True))
    _runner._detached_tasks[_TID] = retry
    await started.wait()

    retry.cancel()  # 照槽那一路的写法：只 cancel，不等

    async with _runner._execution_lease(_TID) as successor:
        assert successor.outcome is leases.AcquireOutcome.GRANTED
        await asyncio.gather(retry, return_exceptions=True)  # 让它退场落地
        assert await leases.renew_outcome(_TID) is leases.RenewOutcome.LOST


async def test_the_wait_keeps_the_successors_lease() -> None:
    """对照：``cancel_detached_and_wait`` 之后，接任者拿到的租约还是它自己的。"""
    started = asyncio.Event()
    retry = asyncio.create_task(_holding_a_lease(started, slow_unwind=True))
    _runner._detached_tasks[_TID] = retry
    await started.wait()

    await _runner.cancel_detached_and_wait(_TID)
    assert retry.done()

    async with _runner._execution_lease(_TID) as successor:
        assert successor.outcome is leases.AcquireOutcome.GRANTED
        assert await leases.renew_outcome(_TID) is leases.RenewOutcome.RENEWED
        assert not successor.lost.is_set()
