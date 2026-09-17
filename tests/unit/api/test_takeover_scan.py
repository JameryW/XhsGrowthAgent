"""The takeover scan's decisions (P2b-S3).

The scan exists to close one gap: after a ``kill -9`` the DB row said
"running" forever and only a person could move it. What it must *not* do is
resume work that is unsafe to re-run, and what it must never do is resume a
thread someone else is still running.

So these tests are about refusals and gates at least as much as about
successes:

* a candidate is only resumed **after** ``acquire`` grants the lease -- the
  candidate list is never trusted on its own;
* a pending gate or the publisher is **refused**, and the refusal is recorded
  as an event so "the scan looked and declined" stays distinguishable from
  "the scan never saw it";
* a refusal leaves the lease alone, so the thread stays recoverable by a
  person;
* one bad row does not fail the pass, and a failing pass does not kill the
  scheduler.

The lease backend is forced to the in-memory fallback so the tests do not
depend on whether a local Postgres happens to be up.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from backend.api.routes import _takeover as takeover_module
from backend.db import execution_leases as leases
from backend.db import workflow_events

_BASE = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)

#: Stands in for a second instance of the service holding a live lease.
_OTHER_INSTANCE = "other-host:4242:beef"


@pytest.fixture(autouse=True)
def _memory_leases(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(leases, "is_pool_ready", lambda: False)
    leases._reset_memory_store()
    workflow_events._reset_memory_store()
    yield
    leases._reset_memory_store()
    workflow_events._reset_memory_store()


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Fake clock driving ``leases._utcnow``; ``clock[0]`` is the offset."""
    ticks = [0.0]
    monkeypatch.setattr(leases, "_utcnow", lambda: _BASE + timedelta(seconds=ticks[0]))
    return ticks


@pytest.fixture
def dead_owner(monkeypatch: pytest.MonkeyPatch):
    """Leave a lease behind the way a killed *other* instance does.

    Acquiring as a different owner id matters: it is what makes the row
    genuinely foreign, so "the scan left the lease alone" is a real assertion
    rather than a comparison of an id with itself.
    """
    live = leases._instance_id

    async def _expire(clock: list[float], thread_id: str, *, ttl: float = leases.LEASE_TTL_SECONDS):
        monkeypatch.setattr(leases, "_instance_id", f"{live}:killed")
        assert await leases.acquire(thread_id, ttl_seconds=ttl) is True
        monkeypatch.setattr(leases, "_instance_id", live)
        clock[0] += ttl + 1.0
        return live

    return _expire


@pytest.fixture
def resume(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Capture ``_start_resume_task`` instead of starting a real run."""
    started: list[dict[str, Any]] = []

    async def _fake(thread_id, graph, config, phase, *, input_data=None):
        started.append({"thread_id": thread_id, "phase": str(phase), "input_data": input_data})

    monkeypatch.setattr("backend.api.routes._wf_runtime._start_resume_task", _fake)
    return started


@pytest.fixture
def events(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Capture the durable decision records instead of writing them."""
    recorded: list[dict[str, Any]] = []

    async def _fake(thread_id, entries, /):
        recorded.extend({"thread_id": thread_id, **entry} for entry in entries)
        return len(entries)

    monkeypatch.setattr("backend.db.workflow_events.append_events", _fake)
    return recorded


class _Snapshot:
    def __init__(self, values: dict[str, Any] | None = None, next_nodes: tuple[str, ...] = ()):
        self.values = values or {}
        self.next = tuple(next_nodes)


class _Graph:
    def __init__(self, snapshot: _Snapshot | None = None, *, error: Exception | None = None):
        self._snapshot = snapshot
        self._error = error
        self.reads = 0

    async def aget_state(self, config: dict[str, Any]) -> _Snapshot:
        self.reads += 1
        if self._error is not None:
            raise self._error
        assert self._snapshot is not None
        return self._snapshot


def _app(graph: Any) -> SimpleNamespace:
    return SimpleNamespace(state=SimpleNamespace(graph=graph))


class TestCandidates:
    async def test_nothing_expired_means_nothing_happens(self, resume, events):
        graph = _Graph(_Snapshot({"session_id": "t1"}, ("copywriter",)))

        report = await takeover_module.takeover_scan(_app(graph), source="periodic")

        assert report["newly_expired"] == 0
        assert report["decisions"] == []
        assert graph.reads == 0, "a thread with no lease was read anyway"
        assert resume == [] and events == []

    async def test_an_expired_lease_is_the_candidate(self, clock, dead_owner, resume):
        await dead_owner(clock, "t1")
        graph = _Graph(_Snapshot({"session_id": "t1"}, ("copywriter",)))

        report = await takeover_module.takeover_scan(_app(graph), source="periodic")

        assert report["newly_expired"] == 1
        assert [d["outcome"] for d in report["decisions"]] == ["taken_over"]


class TestTheLeaseGate:
    async def test_it_resumes_only_after_it_holds_the_lease(self, clock, dead_owner, resume):
        live = await dead_owner(clock, "t1")
        graph = _Graph(_Snapshot({"session_id": "t1"}, ("copywriter",)))

        await takeover_module.takeover_scan(_app(graph), source="periodic")

        record = await leases.get_lease("t1")
        assert record is not None
        assert record.state is leases.LeaseState.HELD
        assert record.owner_id == live
        assert len(resume) == 1

    async def test_it_resumes_from_the_checkpoint_not_to_a_chosen_node(
        self, clock, dead_owner, resume
    ):
        """``input_data=None`` is native resume: LangGraph re-runs the *pending*
        node. A ``Command(goto=...)`` would re-run a node that already
        completed -- the retry path, which a scan must not take on its own."""
        await dead_owner(clock, "t1")
        graph = _Graph(_Snapshot({"session_id": "t1"}, ("copywriter",)))

        await takeover_module.takeover_scan(_app(graph), source="periodic")

        assert resume[0]["input_data"] is None
        # The phase it writes must be non-terminal, or /status would lie.
        assert resume[0]["phase"] not in ("completed", "cancelled", "error")

    async def test_a_candidate_it_cannot_acquire_is_skipped(
        self, resume, events, monkeypatch: pytest.MonkeyPatch
    ):
        """The candidate list is not trusted: ``acquire`` decides.

        This is the two-scans-at-once race -- another instance reached the same
        expiry first. Handing the scan the id directly is the point: even given
        the candidate it must not resume.
        """
        live = leases._instance_id
        monkeypatch.setattr(leases, "_instance_id", _OTHER_INSTANCE)
        assert await leases.acquire("t1") is True
        # Back to this instance: the row is now foreign *and* held by someone
        # else, which is the only shape that makes the gate observable.
        monkeypatch.setattr(leases, "_instance_id", live)

        async def _hands_it_over() -> list[str]:
            return ["t1"]

        monkeypatch.setattr(takeover_module, "expire_scan", _hands_it_over)
        graph = _Graph(_Snapshot({"session_id": "t1"}, ("copywriter",)))

        report = await takeover_module.takeover_scan(_app(graph), source="periodic")

        assert [d["outcome"] for d in report["decisions"]] == ["skipped"]
        assert report["decisions"][0]["reason"] == "lease_refused"
        assert resume == []
        assert events == [], "a skip is not a decision worth an event"


class TestWhatItRefuses:
    async def test_a_pending_gate_is_refused_with_a_reason(self, clock, dead_owner, resume, events):
        await dead_owner(clock, "t1")
        graph = _Graph(_Snapshot({"session_id": "t1"}, ("review_gate",)))

        report = await takeover_module.takeover_scan(_app(graph), source="startup")

        assert report["decisions"][0]["outcome"] == "refused"
        assert report["decisions"][0]["reason"] == "needs_human"
        assert resume == [], "a gate was resumed for a person"
        assert events == [
            {
                "thread_id": "t1",
                "kind": takeover_module.TAKEOVER_EVENT_KIND,
                "outcome": "refused",
                "reason": "needs_human",
                "pending": ["review_gate"],
                "source": "startup",
                "ts": events[0]["ts"],
            }
        ]

    async def test_a_pending_publisher_is_refused_as_irreversible(
        self, clock, dead_owner, resume, events
    ):
        await dead_owner(clock, "t1")
        graph = _Graph(_Snapshot({"session_id": "t1"}, ("publisher",)))

        report = await takeover_module.takeover_scan(_app(graph), source="startup")

        assert report["decisions"][0]["reason"] == "irreversible"
        assert resume == []
        assert events[0]["reason"] == "irreversible"

    async def test_a_refusal_leaves_the_lease_alone(self, clock, dead_owner, resume):
        """The thread must stay recoverable by a person afterwards.

        Claiming the lease and then declining would make the row look running
        for a whole TTL and lock /recover out of it -- a refusal that causes the
        harm it was avoiding.
        """
        live = await dead_owner(clock, "t1")
        graph = _Graph(_Snapshot({"session_id": "t1"}, ("publish_gate",)))

        await takeover_module.takeover_scan(_app(graph), source="startup")

        record = await leases.get_lease("t1")
        assert record is not None
        assert record.state is leases.LeaseState.EXPIRED
        assert record.owner_id == f"{live}:killed", "the scan took the lease anyway"
        assert await leases.thread_is_held("t1") is False


class TestWhatItSkips:
    async def test_no_checkpoint_is_skipped(self, clock, dead_owner, resume):
        await dead_owner(clock, "t1")
        graph = _Graph(_Snapshot({}, ()))

        report = await takeover_module.takeover_scan(_app(graph), source="startup")

        assert report["decisions"] == [
            {"thread_id": "t1", "outcome": "skipped", "reason": "no_checkpoint"}
        ]
        assert resume == []

    async def test_a_run_with_nothing_pending_is_skipped(self, clock, dead_owner, resume):
        """A finished or errored run is the human /recover path, not an
        interrupted loop."""
        await dead_owner(clock, "t1")
        graph = _Graph(_Snapshot({"session_id": "t1"}, ()))

        report = await takeover_module.takeover_scan(_app(graph), source="startup")

        assert report["decisions"][0]["reason"] == "nothing_pending"
        assert resume == []

    async def test_an_unreadable_state_is_skipped_not_fatal(self, clock, dead_owner, resume):
        await dead_owner(clock, "t1")
        graph = _Graph(error=RuntimeError("checkpoint store down"))

        report = await takeover_module.takeover_scan(_app(graph), source="startup")

        assert report["decisions"][0]["reason"] == "state_unreadable"
        assert report["error"] is None, "one bad row failed the whole pass"


class TestItDecidesOnce:
    async def test_a_refused_expiry_is_not_re_decided(self, clock, dead_owner, events):
        """Otherwise a permanently-refused thread writes an event every cycle."""
        await dead_owner(clock, "t1")
        graph = _Graph(_Snapshot({"session_id": "t1"}, ("publish_gate",)))
        app = _app(graph)

        first = await takeover_module.takeover_scan(app, source="startup")
        second = await takeover_module.takeover_scan(app, source="periodic")

        assert first["newly_expired"] == 1
        assert second["newly_expired"] == 0
        assert second["decisions"] == []
        assert len(events) == 1


class TestTheReport:
    async def test_it_names_the_source_and_both_timestamps(self, clock, dead_owner, resume):
        await dead_owner(clock, "t1")
        graph = _Graph(_Snapshot({"session_id": "t1"}, ("copywriter",)))

        report = await takeover_module.takeover_scan(_app(graph), source="startup")

        assert report["source"] == "startup"
        assert report["started_at"] and report["finished_at"]
        assert report["error"] is None

    async def test_a_missing_graph_is_reported_not_raised(self):
        app = SimpleNamespace(state=SimpleNamespace(graph=None))

        report = await takeover_module.takeover_scan(app, source="startup")

        assert report["error"] == "no_graph"

    async def test_a_failing_expire_scan_is_reported_not_raised(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        async def _boom() -> list[str]:
            raise RuntimeError("lease store down")

        monkeypatch.setattr(takeover_module, "expire_scan", _boom)
        graph = _Graph(_Snapshot({"session_id": "t1"}, ("copywriter",)))

        report = await takeover_module.takeover_scan(_app(graph), source="periodic")

        assert report["error"] is not None and "lease store down" in report["error"]
        assert report["finished_at"] is not None


class TestTheAppStatus:
    async def test_the_status_records_the_pass(self, clock, dead_owner, resume, events):
        await dead_owner(clock, "t1")
        graph = _Graph(_Snapshot({"session_id": "t1"}, ("copywriter",)))
        app = _app(graph)
        app.state.takeover_status = {"durability": "none", "enabled": True}

        takeover_module._merge_status(
            app, await takeover_module.takeover_scan(app, source="startup")
        )

        status = app.state.takeover_status
        assert status["run_count"] == 1
        assert status["last_source"] == "startup"
        assert status["last_newly_expired"] == 1
        assert status["last_taken_over"] == 1
        assert status["last_refused"] == 0
        assert status["last_skipped"] == 0
        assert status["last_error"] is None
        # Fields the scan does not own survive the merge.
        assert status["durability"] == "none"
        assert status["enabled"] is True

    async def test_the_status_bucket_is_created_when_absent(self, clock, resume):
        app = _app(_Graph(_Snapshot({"session_id": "t1"}, ("copywriter",))))
        assert not hasattr(app.state, "takeover_status")

        takeover_module._merge_status(
            app, await takeover_module.takeover_scan(app, source="startup")
        )

        assert app.state.takeover_status["run_count"] == 1

    async def test_a_failing_pass_is_counted_and_kept(self, monkeypatch: pytest.MonkeyPatch):
        async def _boom() -> list[str]:
            raise RuntimeError("lease store down")

        monkeypatch.setattr(takeover_module, "expire_scan", _boom)
        app = _app(_Graph(_Snapshot({"session_id": "t1"}, ("copywriter",))))

        takeover_module._merge_status(
            app, await takeover_module.takeover_scan(app, source="periodic")
        )

        status = app.state.takeover_status
        assert status["run_count"] == 1
        assert status["last_error"] is not None

    async def test_the_decision_log_is_bounded(self, clock, dead_owner, resume, monkeypatch):
        """``app.state`` outlives the process's memory of past scans."""
        for index in range(25):
            # Zero-padded so lexical order (which is the order expire_scan
            # returns) matches numeric order.
            await dead_owner(clock, f"t{index:02d}")
        app = _app(_Graph(_Snapshot({"session_id": "x"}, ("copywriter",))))

        takeover_module._merge_status(
            app, await takeover_module.takeover_scan(app, source="periodic")
        )

        log = app.state.takeover_status["last_decisions"]
        assert len(log) == takeover_module._MAX_LOGGED_DECISIONS
        # The newest survive, not the oldest.
        assert log[-1]["thread_id"] == "t24"


class TestTheScheduler:
    async def test_it_runs_passes_until_cancelled(self, monkeypatch: pytest.MonkeyPatch):
        sources: list[str] = []

        async def _fake_scan(app, *, source):
            sources.append(source)
            return {
                "source": source,
                "started_at": "s",
                "finished_at": "f",
                "newly_expired": 0,
                "decisions": [],
                "error": None,
            }

        monkeypatch.setattr(takeover_module, "takeover_scan", _fake_scan)
        app = _app(_Graph(_Snapshot()))

        task = asyncio.create_task(takeover_module.takeover_scheduler(app, interval_seconds=0.01))
        await asyncio.sleep(0.05)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

        assert sources, "the scheduler never ran a pass"
        assert set(sources) == {"periodic"}
        # Cancelling can land between a pass and its merge, so only the lower
        # bound is asserted.
        assert app.state.takeover_status["run_count"] >= 1

    async def test_a_failing_pass_does_not_kill_the_loop(self, monkeypatch: pytest.MonkeyPatch):
        calls = {"n": 0}

        async def _flaky_scan(app, *, source):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("first pass explodes")
            return {
                "source": source,
                "started_at": "s",
                "finished_at": "f",
                "newly_expired": 0,
                "decisions": [],
                "error": None,
            }

        monkeypatch.setattr(takeover_module, "takeover_scan", _flaky_scan)
        app = _app(_Graph(_Snapshot()))

        task = asyncio.create_task(takeover_module.takeover_scheduler(app, interval_seconds=0.01))
        for _ in range(50):
            if calls["n"] >= 2:
                break
            await asyncio.sleep(0.01)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

        assert calls["n"] >= 2, "one failing pass ended the loop"


class TestTheStartupPass:
    async def test_it_runs_a_startup_pass(self, monkeypatch: pytest.MonkeyPatch):
        seen: list[str] = []

        async def _fake_scan(app, *, source):
            seen.append(source)
            return {
                "source": source,
                "started_at": "s",
                "finished_at": "f",
                "newly_expired": 0,
                "decisions": [],
                "error": None,
            }

        monkeypatch.setattr(takeover_module, "takeover_scan", _fake_scan)
        app = _app(_Graph(_Snapshot()))

        await takeover_module.startup_takeover_scan(app)

        assert seen == ["startup"]
        assert app.state.takeover_status["last_source"] == "startup"

    async def test_a_failing_startup_pass_does_not_block_startup(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Before S3 there was no automatic takeover; a scan that cannot run
        must degrade to exactly that, not to a service that will not boot."""

        async def _boom(app, *, source):
            raise RuntimeError("no graph yet")

        monkeypatch.setattr(takeover_module, "takeover_scan", _boom)
        app = _app(_Graph(_Snapshot()))

        await takeover_module.startup_takeover_scan(app)

        assert not hasattr(app.state, "takeover_status")


class TestItDoesNotRunTheGraphItself:
    async def test_the_scan_never_invokes_the_graph(self, clock, dead_owner):
        """Resuming is delegated to the one function that also persists status
        and emits transitions. A scan that invoked the graph directly would
        bypass all of it."""
        await dead_owner(clock, "t1")
        graph = _Graph(_Snapshot({"session_id": "t1"}, ("copywriter",)))
        graph.ainvoke = AsyncMock(side_effect=AssertionError("the scan ran the graph"))

        await takeover_module.takeover_scan(_app(graph), source="startup")

        graph.ainvoke.assert_not_called()


class TestTheStatusKeySet:
    """The weather the health surface reads. A merge that invented a key would
    quietly outgrow every reader that whitelists fields."""

    async def test_the_merge_never_invents_a_key(self, clock, dead_owner, resume):
        await dead_owner(clock, "t1")
        app = _app(_Graph(_Snapshot({"session_id": "t1"}, ("copywriter",))))
        app.state.takeover_status = takeover_module.initial_status(
            enabled=True, durability="none", interval_seconds=60.0
        )
        before = set(app.state.takeover_status)

        takeover_module._merge_status(
            app, await takeover_module.takeover_scan(app, source="startup")
        )

        assert set(app.state.takeover_status) == before

    def test_a_fresh_bucket_says_which_state_it_is_in(self):
        """``status`` separates "not scheduled" from "ran and found nothing",
        and ``durability`` separates "nothing was taken over" from "nothing
        durable could have been" (P2b ruling 2)."""
        off = takeover_module.initial_status(
            enabled=False, durability="none", interval_seconds=60.0
        )
        on = takeover_module.initial_status(
            enabled=True, durability="durable", interval_seconds=60.0
        )

        assert off["status"] == "disabled" and off["enabled"] is False
        assert on["status"] == "scheduled" and on["enabled"] is True
        assert off["durability"] == "none" and on["durability"] == "durable"

    def test_two_fresh_buckets_do_not_share_their_decision_log(self):
        first = takeover_module.initial_status(
            enabled=True, durability="none", interval_seconds=60.0
        )
        second = takeover_module.initial_status(
            enabled=True, durability="none", interval_seconds=60.0
        )

        first["last_decisions"].append({"thread_id": "t1"})

        assert second["last_decisions"] == []

    async def test_the_run_count_accumulates(self, clock, dead_owner, resume):
        """A counter that resets to 1 every pass still looks right once."""
        await dead_owner(clock, "t1")
        app = _app(_Graph(_Snapshot({"session_id": "t1"}, ("copywriter",))))

        takeover_module._merge_status(
            app, await takeover_module.takeover_scan(app, source="startup")
        )
        takeover_module._merge_status(
            app, await takeover_module.takeover_scan(app, source="periodic")
        )

        assert app.state.takeover_status["run_count"] == 2


class TestTheSchedulerWaits:
    async def test_it_does_not_scan_until_the_interval_has_passed(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """The startup pass covers "right now"; the loop is for later. Scanning
        immediately would double-scan every boot, and a loop that never sleeps
        would spin."""
        sources: list[str] = []

        async def _fake_scan(app, *, source):
            sources.append(source)
            return {
                "source": source,
                "started_at": "s",
                "finished_at": "f",
                "newly_expired": 0,
                "decisions": [],
                "error": None,
            }

        monkeypatch.setattr(takeover_module, "takeover_scan", _fake_scan)
        app = _app(_Graph(_Snapshot()))

        task = asyncio.create_task(takeover_module.takeover_scheduler(app, interval_seconds=0.5))
        await asyncio.sleep(0.1)
        assert sources == [], "the scheduler scanned before its interval elapsed"
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
