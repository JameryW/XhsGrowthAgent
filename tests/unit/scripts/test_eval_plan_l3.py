"""P3/E4: the live-run planner must refuse anything the user did not authorise.

The decisions are literal: fewer than 200 model calls, the test account only, an
LLM judge allowed.  These tests pin the refusals, because a planner that says
"ready" wrongly is worse than no planner at all — it would be the thing an
operator points at when an unapproved run starts.  The budget is checked against
**total** estimated calls (workflow + judge), not judge verdicts alone; otherwise a
50-sample "≤199" plan could spend far more than the approval.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
EVAL_DIR = REPO / "scripts" / "eval"
if str(EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(EVAL_DIR))

import plan_l3 as plan_l3  # noqa: E402

ARMED = {"XHS_EVAL_LIVE": "1"}


def _plan(**overrides):
    base = {
        "samples": 3,
        "account": "test-account",
        "judge": "llm",
        "max_calls": 199,
        "calls_per_sample": 5,
    }
    base.update(overrides)
    return plan_l3.L3Plan(**base)


def test_a_complete_plan_is_ready():
    readiness = plan_l3.validate(_plan(), environ=ARMED)
    assert readiness.ready is True, readiness.problems
    assert readiness.problems == []


def test_an_unarmed_run_is_blocked_even_when_everything_else_is_present():
    readiness = plan_l3.validate(_plan(), environ={})
    assert readiness.ready is False
    assert any("XHS_EVAL_LIVE" in problem for problem in readiness.problems)


def test_the_test_account_is_mandatory():
    readiness = plan_l3.validate(_plan(account=""), environ=ARMED)
    assert readiness.ready is False
    assert any("account is required" in problem for problem in readiness.problems)


def test_the_approved_budget_cap_is_literal():
    readiness = plan_l3.validate(_plan(max_calls=200), environ=ARMED)
    assert readiness.ready is False
    assert any("exceeds the approved cap of 199" in problem for problem in readiness.problems)


def test_sample_bounds_are_enforced():
    assert plan_l3.validate(_plan(samples=0), environ=ARMED).ready is False
    assert plan_l3.validate(_plan(samples=51), environ=ARMED).ready is False
    assert plan_l3.validate(_plan(samples=50, calls_per_sample=1), environ=ARMED).ready is True


def test_an_unknown_workflow_call_estimate_blocks_the_run():
    readiness = plan_l3.validate(_plan(calls_per_sample=0), environ=ARMED)
    assert readiness.ready is False
    assert any("calls-per-sample" in problem for problem in readiness.problems)


def test_the_budget_covers_total_calls_not_only_judge_verdicts():
    """ "<200 calls" is about everything the run spends, not one verdict per sample."""
    readiness = plan_l3.validate(
        _plan(samples=30, calls_per_sample=10, max_calls=199), environ=ARMED
    )
    assert readiness.ready is False
    assert any("estimated total calls" in problem for problem in readiness.problems)


def test_a_missing_quality_judge_is_blocked():
    readiness = plan_l3.validate(_plan(judge="none"), environ=ARMED)
    assert readiness.ready is False
    assert any("quality dimension" in problem for problem in readiness.problems)


def test_more_verdicts_than_budget_is_blocked():
    readiness = plan_l3.validate(_plan(samples=10, max_calls=5, calls_per_sample=1), environ=ARMED)
    assert readiness.ready is False
    assert any("exceed max_calls" in problem for problem in readiness.problems)


def test_a_human_judge_is_allowed_with_a_note_not_a_block():
    readiness = plan_l3.validate(_plan(judge="human"), environ=ARMED)
    assert readiness.ready is True
    assert any("human reviewer" in note for note in readiness.notes)


def test_the_report_is_json_able_and_names_the_budget():
    report = plan_l3.plan_report(_plan(), plan_l3.validate(_plan(), environ=ARMED))
    json.dumps(report)
    assert report["ready"] is True
    assert report["approved_max_calls"] == 199
    assert report["plan"]["judge_calls"] == 3
    assert report["plan"]["estimated_total_calls"] == 18


def test_the_cli_armed_mode_is_the_gate(monkeypatch, capsys):
    monkeypatch.delenv("XHS_EVAL_LIVE", raising=False)
    assert plan_l3.main(["--armed", "--account", "test-account", "--calls-per-sample", "5"]) == 1
    output = capsys.readouterr().out
    assert "ready: no" in output
    assert "nothing was launched" in output

    monkeypatch.setenv("XHS_EVAL_LIVE", "1")
    assert plan_l3.main(["--armed", "--account", "test-account", "--calls-per-sample", "5"]) == 0
    assert "ready: yes" in capsys.readouterr().out


def test_the_cli_json_mode_prints_the_plan(monkeypatch, capsys):
    monkeypatch.setenv("XHS_EVAL_LIVE", "1")
    assert (
        plan_l3.main(
            ["--json", "--account", "test-account", "--samples", "2", "--calls-per-sample", "5"]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report["plan"]["samples"] == 2
    assert report["plan"]["estimated_total_calls"] == 12
    assert report["ready"] is True


def test_any_live_run_needs_arming_even_with_a_human_judge():
    """The workflow spends model calls regardless of who judges."""
    readiness = plan_l3.validate(_plan(judge="human"), environ={})
    assert readiness.ready is False
    assert any("XHS_EVAL_LIVE" in problem for problem in readiness.problems)


def test_the_report_states_the_estimate_is_not_a_cap():
    report = plan_l3.plan_report(_plan(), plan_l3.validate(_plan(), environ=ARMED))
    assert "estimate" in report["plan"]["estimate_basis"]
    assert "not a runtime cap" in report["plan"]["estimate_basis"]
