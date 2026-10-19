"""Signal inventory — the read side must not flatter the data.

The module's only job is counting, so the tests are about the three ways a
counter lies: inventing zeros, hiding entries it did not understand, and
blurring a legacy field into a modern one.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from backend.db.workflow_events import EVENT_KINDS
from backend.services.signal_inventory import (
    SAMPLE_LIMIT,
    UNSPECIFIED,
    inventory,
)

ROOT = Path(__file__).resolve().parents[3]


def _node(agent: str = "copywriter", **extra):
    entry = {"kind": "node", "agent": agent, "duration_seconds": 1.0}
    entry.update(extra)
    return entry


def _progress(reason: str = "same_hints_repeated", **extra):
    entry = {
        "kind": "progress",
        "reason": reason,
        "window": 2,
        "evidence": {"rounds": [1, 2]},
        "thread_id": "t-1",
        "timestamp": "2026-10-19T00:00:00+00:00",
    }
    entry.update(extra)
    return entry


def _verification(**extra):
    entry = {
        "kind": "verification",
        "action": "publish",
        "required": True,
        "tier": "human",
        "reason": "risk_floor",
        "expected_benefit": 0.9,
    }
    entry.update(extra)
    return entry


class TestNoDataIsNotZero:
    def test_empty_timeline_has_no_data(self):
        report = inventory([])
        assert report.has_data is False
        assert report.by_kind == ()

    def test_no_progress_is_an_empty_tuple_not_a_zero_row(self):
        report = inventory([_node()])
        assert report.has_data is True
        assert report.progress.emitted == 0
        assert report.progress.by_reason == ()
        assert report.progress.samples == ()

    def test_malformed_only_still_counts_the_damage(self):
        report = inventory([None, "not-an-entry", 42])
        assert report.has_data is False
        assert report.malformed_entries == 3


class TestLegacyAndDrift:
    def test_kindless_entries_count_as_node_and_are_flagged(self):
        report = inventory([{"agent": "analyst", "duration_seconds": 2.0}, _node()])
        assert report.by_kind == (("node", 2),)
        assert report.kindless_node_entries == 1

    def test_unknown_kind_is_surfaced_not_dropped(self):
        report = inventory([{"kind": "made_up"}, _node()])
        assert report.unknown_kinds == ("made_up",)
        # Still counted: dropping it would make the total disagree with the input.
        assert ("made_up", 1) in report.by_kind
        assert report.total_entries == 2

    def test_every_declared_kind_is_known(self):
        # A false positive here means EVENT_KINDS and this reader drifted apart.
        report = inventory([{"kind": kind} for kind in sorted(EVENT_KINDS)])
        assert report.unknown_kinds == ()

    def test_ordering_is_deterministic(self):
        report = inventory([_node(), _node(), {"kind": "llm"}, {"kind": "context"}])
        assert report.by_kind == (("node", 2), ("context", 1), ("llm", 1))


class TestProgress:
    def test_reasons_and_windows_are_aggregated(self):
        report = inventory(
            [
                _progress("same_hints_repeated", window=2),
                _progress("same_hints_repeated", window=2),
                _progress("revised_without_improvement", window=2),
            ]
        )
        assert report.progress.emitted == 3
        assert report.progress.by_reason == (
            ("same_hints_repeated", 2),
            ("revised_without_improvement", 1),
        )
        assert report.progress.windows == (2,)

    def test_samples_are_capped_and_carry_evidence(self):
        report = inventory([_progress() for _ in range(SAMPLE_LIMIT + 4)])
        assert len(report.progress.samples) == SAMPLE_LIMIT
        sample = report.progress.samples[0]
        assert sample["evidence"] == {"rounds": [1, 2]}
        assert sample["thread_id"] == "t-1"
        # Counted fully even though only a few are echoed.
        assert report.progress.emitted == SAMPLE_LIMIT + 4

    def test_sample_omits_absent_thread_id(self):
        report = inventory([_progress(thread_id="")])
        assert "thread_id" not in report.progress.samples[0]

    def test_boolean_window_is_not_a_window(self):
        # ``True`` is an int in Python; counting it as window 1 would invent a
        # producer that never existed.
        report = inventory([_progress(window=True)])
        assert report.progress.windows == ()

    def test_missing_reason_is_labelled_not_invented(self):
        report = inventory([_progress(reason="")])
        assert report.progress.by_reason == ((UNSPECIFIED, 1),)

    def test_non_mapping_evidence_does_not_kill_the_report(self):
        # A stray string where a dict belongs is a producer bug; the reader
        # reports it as absent instead of raising and losing the whole run.
        report = inventory([_progress(evidence="oops"), _verification()])
        assert report.progress.samples[0]["evidence"] is None
        assert report.verification.recorded == 1


class TestVerificationAndActions:
    def test_only_a_literal_true_counts_as_required(self):
        report = inventory(
            [
                _verification(required=True),
                _verification(required=False, tier="none", reason="dry_run"),
                _verification(required="yes"),
            ]
        )
        assert report.verification.recorded == 3
        assert report.verification.required == 1
        # The third entry only overrides ``required``; its tier stays "human".
        assert report.verification.by_tier == (("human", 2), ("none", 1))
        assert ("dry_run", 1) in report.verification.by_reason

    def test_action_refusals_are_grouped_by_kind(self):
        report = inventory(
            [
                {"kind": "action", "action": "policy_denied"},
                {"kind": "action", "action": "policy_denied"},
                {"kind": "action", "action": "lease_refused"},
            ]
        )
        assert report.action.refusals == 3
        assert report.action.by_action == (("policy_denied", 2), ("lease_refused", 1))

    def test_verification_and_action_are_not_confused(self):
        # Both carry an ``action`` key; only ``kind`` separates a verdict from
        # a refusal. Mixing them would report decisions as denials.
        report = inventory([_verification()])
        assert report.action.refusals == 0
        assert report.verification.recorded == 1


class TestCli:
    def test_events_export_prints_a_report_and_exits_zero(self, tmp_path):
        export = tmp_path / "run.json"
        export.write_text(
            json.dumps({"events": [_node(), _progress(), _verification()]}), encoding="utf-8"
        )
        done = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/benchmarks/signal_inventory.py"),
                "--events",
                str(export),
            ],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
        )
        assert done.returncode == 0, done.stderr
        assert "progress signals: 1" in done.stdout
        assert "verification decisions: 1" in done.stdout

    def test_no_data_exits_zero(self, tmp_path):
        export = tmp_path / "empty.json"
        export.write_text("[]", encoding="utf-8")
        done = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/benchmarks/signal_inventory.py"),
                "--events",
                str(export),
            ],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
        )
        # "No data" is a finding, not a failure — CI must not read it as red.
        assert done.returncode == 0, done.stderr
        assert "Verdict: nothing recorded" in done.stdout
