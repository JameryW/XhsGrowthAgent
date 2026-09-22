"""Tests for the P1a-S2 Event store and its read façade.

Covers the telemetry tier that replaced the checkpoint's ``performance_log``:
append/list ordering and thread isolation in the no-Postgres fallback, the
legacy-checkpoint passthrough in :func:`load_perf_log` (decision D1: existing
threads keep their inline log), and the thread-id resolution the writers rely
on.

The app pool is never ready under tests (``conftest`` pops ``POSTGRES_URI``),
so every assertion here exercises the in-memory fallback — the same branch
dev/CI use.
"""

from __future__ import annotations

from backend.db.workflow_events import append_events, list_events
from backend.state.events import (
    has_inline_perf_log,
    inline_perf_log,
    load_perf_log,
    resolve_thread_id,
)

THREAD = "xhs_test_events"


class TestAppendAndList:
    async def test_round_trip_preserves_order_and_payload(self):
        await append_events(
            THREAD,
            [
                {"kind": "node", "agent": "orchestrator", "completed_at": "t1"},
                {"kind": "llm", "agent": "copywriter", "cost_usd": 0.01},
            ],
        )
        events = await list_events(THREAD)
        assert [e["kind"] for e in events] == ["node", "llm"]
        assert events[0]["agent"] == "orchestrator"
        assert events[1]["cost_usd"] == 0.01

    async def test_missing_kind_defaults_to_node(self):
        # Pre-kind performance_log entries were read as node entries; the store
        # must keep that meaning rather than dropping the kind discriminator.
        await append_events(THREAD, [{"agent": "legacy-agent"}])
        (event,) = await list_events(THREAD)
        assert event["agent"] == "legacy-agent"

        by_kind = await list_events(THREAD, kind="node")
        assert len(by_kind) == 1

    async def test_threads_are_isolated(self):
        await append_events("thread-a", [{"kind": "node", "agent": "a"}])
        await append_events("thread-b", [{"kind": "node", "agent": "b"}])
        assert [e["agent"] for e in await list_events("thread-a")] == ["a"]
        assert [e["agent"] for e in await list_events("thread-b")] == ["b"]

    async def test_kind_filter(self):
        await append_events(
            THREAD,
            [{"kind": "node"}, {"kind": "llm", "cost_usd": 0.02}, {"kind": "llm"}],
        )
        assert len(await list_events(THREAD, kind="llm")) == 2
        assert len(await list_events(THREAD)) == 3

    async def test_empty_inputs_are_noops(self):
        assert await append_events("", [{"kind": "node"}]) == 0
        assert await append_events(THREAD, []) == 0
        assert await list_events("") == []

    async def test_reads_are_defensive_about_non_dict_payloads(self):
        # Writers filter non-dicts, so this is a guard for direct callers.
        assert await append_events(THREAD, ["not-a-dict"]) == 0  # type: ignore[list-item]


class TestLoadPerfLog:
    async def test_returns_stored_events_for_new_threads(self):
        await append_events(THREAD, [{"kind": "llm", "cost_usd": 0.5}])
        events = await load_perf_log(THREAD, {"thread_id": THREAD})
        assert [e.get("cost_usd") for e in events] == [0.5]

    async def test_legacy_inline_log_passes_through(self):
        # No stored events, but the checkpoint (pre-S2 thread) carries the log.
        values = {"thread_id": THREAD, "performance_log": [{"kind": "node", "agent": "old"}]}
        events = await load_perf_log(THREAD, values)
        assert [e["agent"] for e in events] == ["old"]

    async def test_legacy_thread_resumed_after_migration_keeps_both(self):
        # Inline entries are the older ones, so they come first.
        await append_events(THREAD, [{"kind": "node", "agent": "new"}])
        values = {"thread_id": THREAD, "performance_log": [{"kind": "node", "agent": "old"}]}
        events = await load_perf_log(THREAD, values)
        assert [e["agent"] for e in events] == ["old", "new"]

    async def test_no_thread_and_no_inline_is_empty(self):
        assert await load_perf_log("", {}) == []


class TestInlinePerfLogHelpers:
    def test_inline_perf_log_filters_non_dicts(self):
        values = {"performance_log": [{"kind": "node"}, "junk", None]}
        assert inline_perf_log(values) == [{"kind": "node"}]

    def test_has_inline_perf_log_detects_key_presence(self):
        # Presence, not truthiness: an empty inline list still marks a legacy
        # thread whose checkpoint predates the migration.
        assert has_inline_perf_log({"performance_log": []}) is True
        assert has_inline_perf_log({"thread_id": "t"}) is False
        assert has_inline_perf_log(None) is False


class TestResolveThreadId:
    def test_prefers_thread_id(self):
        assert resolve_thread_id({"thread_id": "t1", "session_id": "s1"}) == "t1"

    def test_falls_back_to_session_id_for_cli_states(self):
        # The CLI's initial state only carries session_id; every writer sets it
        # to the thread id, so telemetry still lands under the right thread.
        assert resolve_thread_id({"session_id": "s1"}) == "s1"

    def test_empty_state_is_empty_string(self):
        assert resolve_thread_id({}) == ""
        assert resolve_thread_id(None) == ""


def test_legacy_marker_is_listed_as_a_dead_state_key():
    """The key hydration declares dead and the key the reader treats as the
    legacy marker must not drift apart — an inconsistency would let a
    re-declared state field silently re-enter the checkpoint."""
    from backend.state.events import LEGACY_PERF_LOG_KEY
    from backend.state.hydration import STATE_LEVEL_DEAD_KEYS

    assert LEGACY_PERF_LOG_KEY in STATE_LEVEL_DEAD_KEYS
