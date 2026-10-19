"""Inventory over a *real* timeline — the emitters and the reader must agree.

The unit tests feed hand-written dicts. Shaped like the producers, but written
by the same hand that wrote the reader — which is exactly how a field rename
slips through. This one writes through the actual emitters (node perf entry,
progress signal, verification decision), reads back through ``load_perf_log``
(the only correct reader, legacy-aware), and inventories that.
"""

from __future__ import annotations

import pytest

from backend.agents.nodes._base import node_perf_entry
from backend.services.signal_inventory import inventory
from backend.services.verification_policy import ActionRisk, VerificationInput, decide
from backend.state.events import emit_events, load_perf_log
from backend.state.progress import detect_progress, progress_event

THREAD = "thread-inventory-1"


async def _seed() -> None:
    node = node_perf_entry(
        "copywriter",
        started_at="2026-10-19T10:00:00+00:00",
        completed_at="2026-10-19T10:00:03+00:00",
        status="completed",
        error=None,
        retries=0,
    )
    # A stalled tool loop: three identical payloads is the detector's rule.
    signal = detect_progress([{"kind": "tool", "tool": "xhs.search", "result": {"n": 7}}] * 3)
    assert signal.stalled
    progress = progress_event(signal, account_id="acct", thread_id=THREAD)
    verification = decide(VerificationInput(action="publish", risk=ActionRisk.CRITICAL)).to_event(
        action="publish", thread_id=THREAD
    )

    written = await emit_events(THREAD, [node, progress, verification])
    assert written == 3


@pytest.mark.asyncio
async def test_inventory_reads_what_the_emitters_wrote():
    await _seed()

    entries = await load_perf_log(THREAD)
    report = inventory(entries)

    assert report.has_data is True
    assert report.total_entries == 3
    assert report.by_kind == (("node", 1), ("progress", 1), ("verification", 1))
    # Everything modern: the S2 migration means no kindless entries here.
    assert report.kindless_node_entries == 0
    assert report.unknown_kinds == ()

    assert report.progress.emitted == 1
    assert report.progress.by_reason == (("tool_output_repeated", 1),)
    assert report.progress.samples[0]["evidence"]["count"] == 3

    assert report.verification.recorded == 1
    assert report.verification.required == 1
    assert report.verification.by_tier == (("human", 1),)

    assert report.action.refusals == 0


@pytest.mark.asyncio
async def test_an_empty_thread_reports_no_data():
    entries = await load_perf_log("thread-never-existed")
    report = inventory(entries)
    assert report.has_data is False
    assert report.total_entries == 0
