"""A run's intent as one value, and the mapping it compiles to (P2c-S3b).

``/start`` used to build its graph input from a 24-key dict literal and then
mutate one of those keys when the mode was ``brief``. The literal carried two
facts that nothing else could answer:

* which phase the run starts in -- it took the caller's and, for brief mode,
  overwrote it;
* whether the run starts at all -- brief mode with no body parks in
  ``awaiting_brief``.

Both are now the goal's (``backend/state/goal.py``). The phase in particular is
worth a test that says *the caller has no say*: the graph's entry is always
``orchestrator`` and that node unconditionally writes the mode's phase, so a
caller-supplied phase never chose the entry -- it only made ``/start``'s response
and the DB row name a phase the graph was not in.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from typing import Any

import pytest

from backend.state.enums import WorkflowMode, WorkflowPhase
from backend.state.goal import BriefInput, Goal
from backend.state.modes import get_mode_spec

#: The key set ``/start`` seeded before this slice, transcribed from the literal
#: it replaced (``backend/api/routes/workflow.py``) rather than imported from the
#: thing under test. Transcribing is the point: a key that stops being seeded
#: then fails here instead of quietly changing what a run starts with.
SEEDED_KEYS = frozenset(
    {
        "phase",
        "current_agent",
        "error",
        "retry_count",
        "execution_mode",
        "workflow_mode",
        "trend_data",
        "content_plan",
        "copy_content",
        "visual_plan",
        "publish_result",
        "analytics",
        "engagement_actions",
        "human_feedback",
        "account_id",
        "session_id",
        "thread_id",
        "topic",
        "niche",
        "niche_resolution",
        "dry_run",
        "auto_publish",
        "created_at",
        "updated_at",
    }
)

CREATED_AT = "2026-09-17T00:00:00+00:00"


def _goal(**overrides: Any) -> Goal:
    fields: dict[str, Any] = {
        "account_id": "acc1",
        "thread_id": "xhs_acc1_deadbeef",
        "mode": WorkflowMode.TREND,
        "topic": "豆浆机推荐",
        "niche": "母婴",
        "niche_resolution": {"source": "manual"},
        "execution_mode": "single",
        "dry_run": False,
        "auto_publish": False,
        "brief": None,
        "created_at": CREATED_AT,
    }
    fields.update(overrides)
    return Goal(**fields)


def _brief(body: dict[str, Any] | None = None, ref: dict[str, Any] | None = None) -> BriefInput:
    return BriefInput(body=body or {"raw_text": "原文", "source_type": "text"}, ref=ref)


class TestTheCompiledState:
    """The mapping a run starts from -- key for key the literal it replaced."""

    def test_it_seeds_exactly_the_keys_the_literal_did(self) -> None:
        assert set(_goal().compile_initial_state()) == SEEDED_KEYS

    def test_it_seeds_no_key_the_literal_did_not(self) -> None:
        # The other direction, spelled out: a superset would pass the equality
        # above only by failing this one, and a diff is easier to read than a
        # symmetric-difference on a 24-element set.
        compiled = _goal().compile_initial_state()
        assert sorted(compiled) == sorted(SEEDED_KEYS)

    def test_every_value_is_the_one_the_literal_wrote(self) -> None:
        state = _goal().compile_initial_state()
        assert state["phase"] is WorkflowPhase.SCOUTING
        assert state["current_agent"] == "orchestrator"
        assert state["error"] is None
        assert state["retry_count"] == 0
        assert state["execution_mode"] == "single"
        assert state["workflow_mode"] is WorkflowMode.TREND
        assert state["trend_data"] == {}
        assert state["content_plan"] == {}
        assert state["copy_content"] == {}
        assert state["visual_plan"] == {}
        assert state["publish_result"] == {}
        assert state["analytics"] == {}
        assert state["engagement_actions"] == []
        assert state["human_feedback"] == {}
        assert state["account_id"] == "acc1"
        assert state["session_id"] == "xhs_acc1_deadbeef"
        assert state["thread_id"] == "xhs_acc1_deadbeef"
        assert state["topic"] == "豆浆机推荐"
        assert state["niche"] == "母婴"
        assert state["niche_resolution"] == {"source": "manual"}
        assert state["dry_run"] is False
        assert state["auto_publish"] is False
        assert state["created_at"] == CREATED_AT
        assert state["updated_at"] == CREATED_AT

    def test_no_performance_log_is_seeded(self) -> None:
        # P1a-S2 moved telemetry to the Event store; seeding the key would mark a
        # new thread as legacy for the inline-passthrough branch of the reader.
        assert "performance_log" not in _goal().compile_initial_state()

    def test_the_switches_travel(self) -> None:
        goal = _goal(dry_run=True, auto_publish=True, execution_mode="continuous")
        state = goal.compile_initial_state()
        assert state["dry_run"] is True
        assert state["auto_publish"] is True
        assert state["execution_mode"] == "continuous"

    def test_the_goal_state_is_named_after_the_thread_it_opens(self) -> None:
        state = _goal(thread_id="xhs_acc1_1234abcd").compile_initial_state()
        assert state["session_id"] == state["thread_id"] == "xhs_acc1_1234abcd"

    def test_the_niche_resolution_is_copied_rather_than_shared(self) -> None:
        goal = _goal()
        state = goal.compile_initial_state()
        assert state["niche_resolution"] == goal.niche_resolution
        assert state["niche_resolution"] is not goal.niche_resolution

    def test_created_and_updated_are_one_instant(self) -> None:
        # The literal called ``datetime.now()`` three times (twice here, once for
        # the DB row) so the three could differ by microseconds. A run is created
        # once; one value is the honest spelling.
        state = _goal().compile_initial_state()
        assert state["created_at"] == state["updated_at"] == CREATED_AT


class TestTheStartPhaseIsTheModes:
    """The caller has no say -- ``WorkflowStartRequest`` no longer offers one."""

    def test_trend_starts_at_scouting(self) -> None:
        assert _goal(mode=WorkflowMode.TREND).start_phase is WorkflowPhase.SCOUTING

    def test_brief_starts_at_briefing(self) -> None:
        assert _goal(mode=WorkflowMode.BRIEF).start_phase is WorkflowPhase.BRIEFING

    def test_the_phase_is_the_specs_own_value(self) -> None:
        # Derived from the registry, not declared a second time: a mode whose
        # entry moved would otherwise start its runs somewhere else entirely.
        for mode in WorkflowMode:
            spec = get_mode_spec(mode)
            assert _goal(mode=mode).start_phase is spec.initial_phase

    def test_a_brief_run_starts_at_briefing_even_with_a_body(self) -> None:
        goal = _goal(mode=WorkflowMode.BRIEF, brief=_brief())
        assert goal.compile_initial_state()["phase"] is WorkflowPhase.BRIEFING

    def test_the_spec_comes_from_the_registry(self) -> None:
        assert _goal(mode=WorkflowMode.BRIEF).spec is get_mode_spec(WorkflowMode.BRIEF)

    def test_the_phase_reaches_the_state_as_a_concrete_phase(self) -> None:
        # It used to be whatever the request held, so two ``isinstance`` guards
        # existed to stringify it. The goal always knows the concrete member.
        state = _goal().compile_initial_state()
        assert isinstance(state["phase"], WorkflowPhase)
        assert state["phase"].value == "scouting"


class TestWaitingForABrief:
    """Whether a run starts now or parks until a brief arrives."""

    def test_a_brief_run_without_a_body_waits(self) -> None:
        assert _goal(mode=WorkflowMode.BRIEF, brief=None).waits_for_brief_upload is True

    def test_a_brief_run_with_a_body_does_not_wait(self) -> None:
        assert _goal(mode=WorkflowMode.BRIEF, brief=_brief()).waits_for_brief_upload is False

    def test_a_trend_run_never_waits(self) -> None:
        assert _goal(mode=WorkflowMode.TREND, brief=None).waits_for_brief_upload is False


class TestWhereTheBriefBodyGoes:
    """Two destinations, decided by whether the artifact store took the body."""

    def test_a_stored_brief_contributes_a_ref_and_not_the_body(self) -> None:
        ref = {"ref": "artifact://brief_content/latest"}
        state = _goal(mode=WorkflowMode.BRIEF, brief=_brief(ref=ref)).compile_initial_state()
        assert state["artifacts"]["brief_content"] == ref
        assert "brief_content" not in state

    def test_an_unstored_brief_keeps_the_body_inline(self) -> None:
        body = {"raw_text": "原文", "source_type": "text"}
        state = _goal(mode=WorkflowMode.BRIEF, brief=_brief(body=body)).compile_initial_state()
        assert state["brief_content"] == body
        assert "artifacts" not in state

    def test_the_ref_is_the_stores_receipt_rather_than_a_copy(self) -> None:
        # ``is_stored`` is the question the route's ``if`` used to ask inline.
        stored = _brief(ref={"ref": "artifact://brief_content/latest"})
        assert stored.is_stored is True
        assert _brief().is_stored is False

    def test_a_run_without_a_brief_contributes_neither_key(self) -> None:
        state = _goal().compile_initial_state()
        assert "artifacts" not in state
        assert "brief_content" not in state

    def test_a_brief_fragment_never_replaces_a_seeded_key(self) -> None:
        # The fragment is merged into the seeded mapping; if it ever grew a key
        # the literal already writes, the merge would silently win. Pin the
        # fragment's own surface so that is a decision rather than an accident.
        assert set(_brief().as_state_fragment()) == {"brief_content"}
        assert set(_brief(ref={"ref": "r"}).as_state_fragment()) == {"artifacts"}


class TestTheGoalIsFrozen:
    def test_it_cannot_be_mutated_after_construction(self) -> None:
        # A goal describes a run that has already been compiled; letting a caller
        # edit one afterwards would let the state and the intent drift apart.
        goal = _goal()
        with pytest.raises(FrozenInstanceError):
            goal.mode = WorkflowMode.BRIEF  # type: ignore[misc]
