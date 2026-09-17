"""The workflow mode registry (P2c-S3a).

``backend/state/modes.py`` is the single declaration of what a mode means, and
:func:`~backend.state.modes.mode_spec` the only reader of ``state``'s mode. These
tests pin the two properties the slice rests on:

* the registry is **exhaustive** and **read-only** (adding a mode is adding a
  row, and there is no way to add one that is half-described);
* the two readers divide the work by *who is allowed to refuse* -- the strict
  one raises for a value that came from outside, the total one falls back to the
  declared default and reports it, because state read out of a checkpoint is not
  something this layer may reject.

The join between the registry and the graph (which nodes the tables may name,
which routers answer what) is checked in
``tests/unit/graph/test_modes_registry.py``, where the graph is available.
"""

from __future__ import annotations

import logging
from types import MappingProxyType

import pytest

from backend.state.enums import WorkflowMode, WorkflowPhase
from backend.state.modes import (
    DEFAULT_WORKFLOW_MODE,
    WORKFLOW_MODES,
    ModeSpec,
    UnknownWorkflowModeError,
    get_mode_spec,
    is_known_mode,
    mode_spec,
    stored_mode,
)

_LOGGER = "xhs_growth.state.modes"


class TestTheRegistryIsExhaustive:
    def test_every_mode_has_a_spec(self) -> None:
        assert set(WORKFLOW_MODES) == set(WorkflowMode)

    def test_the_default_is_a_declared_mode(self) -> None:
        assert DEFAULT_WORKFLOW_MODE in WORKFLOW_MODES

    def test_the_registry_cannot_be_edited_in_place(self) -> None:
        # A mapping a reader can mutate is a declaration that can drift from
        # what the tests read.
        assert isinstance(WORKFLOW_MODES, MappingProxyType)
        with pytest.raises(TypeError):
            WORKFLOW_MODES[WorkflowMode.TREND] = WORKFLOW_MODES[WorkflowMode.BRIEF]  # type: ignore[index]


class TestTheTotalReader:
    def test_a_declared_mode_is_read(self) -> None:
        assert mode_spec({"workflow_mode": "brief"}).mode is WorkflowMode.BRIEF
        assert mode_spec({"workflow_mode": WorkflowMode.BRIEF}).mode is WorkflowMode.BRIEF

    def test_a_missing_mode_is_the_declared_default(self) -> None:
        assert mode_spec({}).mode is DEFAULT_WORKFLOW_MODE

    def test_a_none_mode_is_the_declared_default(self, caplog: pytest.LogCaptureFixture) -> None:
        # ``None`` is an *absent* mode, not an unrecognised one -- the shape a
        # checkpoint has when the key was never written -- so it must not be
        # reported the way an unknown value is. Without this the two cases are
        # only distinguishable by reading the branch that separates them.
        with caplog.at_level(logging.WARNING, logger=_LOGGER):
            assert mode_spec({"workflow_mode": None}).mode is DEFAULT_WORKFLOW_MODE
        assert caplog.text == ""

    def test_the_default_is_trend(self) -> None:
        # Not a tautology: eight read points used to spell the default as the
        # literal "trend", so what an absent or unknown mode *means* is part of
        # the contract this module took over. Assert with the literal, not with
        # the constant, or the test moves with whatever the constant becomes.
        assert DEFAULT_WORKFLOW_MODE is WorkflowMode.TREND
        assert mode_spec({}).entry == "trend_scout"

    def test_an_unknown_mode_falls_back_and_says_so(self, caplog: pytest.LogCaptureFixture) -> None:
        # The fallback is allowed -- see the module docstring -- but the silence
        # is not: every read used to carry its own `"trend"` default, which is
        # exactly what made an unknown mode indistinguishable from trend.
        with caplog.at_level(logging.WARNING, logger=_LOGGER):
            spec = mode_spec({"workflow_mode": "brand_campaign", "thread_id": "xhs_1"})
        assert spec.mode is DEFAULT_WORKFLOW_MODE
        assert "brand_campaign" in caplog.text
        assert "xhs_1" in caplog.text

    def test_a_known_mode_is_not_reported_as_an_anomaly(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING, logger=_LOGGER):
            mode_spec({"workflow_mode": "brief"})
        assert caplog.text == ""


class TestTheStrictReaderRefuses:
    def test_it_names_the_value_and_the_alternatives(self) -> None:
        with pytest.raises(UnknownWorkflowModeError) as excinfo:
            get_mode_spec("brand_campaign")
        assert excinfo.value.value == "brand_campaign"
        assert "brand_campaign" in str(excinfo.value)
        assert "brief" in str(excinfo.value) and "trend" in str(excinfo.value)

    def test_refusing_is_a_value_error(self) -> None:
        # So that a boundary that already handles ValueError keeps working.
        with pytest.raises(ValueError):
            get_mode_spec("brand_campaign")

    def test_it_still_answers_for_a_real_mode(self) -> None:
        assert get_mode_spec(WorkflowMode.BRIEF) is WORKFLOW_MODES[WorkflowMode.BRIEF]
        assert get_mode_spec("brief") is WORKFLOW_MODES[WorkflowMode.BRIEF]


class TestStoredModeKeepsWhatItDoesNotUnderstand:
    def test_a_stored_value_comes_back_as_a_plain_string(self) -> None:
        got = stored_mode({"workflow_mode": WorkflowMode.BRIEF})
        assert got == "brief"
        assert type(got) is str

    def test_an_unknown_stored_value_is_preserved(self) -> None:
        # The write-back must not normalise: an unrecognised value is still the
        # value the thread was created with, and rewriting it to the default
        # would erase the only record that a thread predates the boundary.
        assert stored_mode({"workflow_mode": "brand_campaign"}) == "brand_campaign"

    def test_absent_and_empty_are_none(self) -> None:
        assert stored_mode({}) is None
        assert stored_mode({"workflow_mode": None}) is None
        assert stored_mode({"workflow_mode": ""}) is None


class TestTheSpecAnswers:
    def test_the_entry_is_the_idle_route(self) -> None:
        for spec in WORKFLOW_MODES.values():
            assert spec.entry == spec.phase_routes[WorkflowPhase.IDLE]

    def test_a_phase_the_table_does_not_list_routes_to_the_entry(self) -> None:
        for spec in WORKFLOW_MODES.values():
            assert WorkflowPhase.PUBLISHING not in spec.phase_routes
            assert spec.route(WorkflowPhase.PUBLISHING) == spec.entry
            assert spec.route("not_a_phase") == spec.entry

    def test_the_modes_answer_differently_where_it_matters(self) -> None:
        trend = WORKFLOW_MODES[WorkflowMode.TREND]
        brief = WORKFLOW_MODES[WorkflowMode.BRIEF]
        assert trend.initial_phase is WorkflowPhase.SCOUTING
        assert brief.initial_phase is WorkflowPhase.BRIEFING
        assert trend.entry == "trend_scout"
        assert brief.entry == "brief_analyzer"
        assert trend.runs_blogger_selection and not brief.runs_blogger_selection
        assert trend.reanalysis_node == "content_strategist"
        assert brief.reanalysis_node == "brief_analyzer"

    def test_a_phase_table_without_an_idle_route_is_refused(self) -> None:
        # Without IDLE there is no entry, and `entry` is what every unlisted
        # phase falls back to -- so a table missing it is not a table.
        with pytest.raises(ValueError, match="idle"):
            ModeSpec(
                mode=WorkflowMode.TREND,
                initial_phase=WorkflowPhase.SCOUTING,
                phase_routes={WorkflowPhase.SCOUTING: "trend_scout"},
                reanalysis_node="content_strategist",
                runs_blogger_selection=True,
            )


class TestIsKnownMode:
    def test_it_accepts_a_member_and_its_value(self) -> None:
        assert is_known_mode(WorkflowMode.TREND)
        assert is_known_mode("brief")

    def test_it_refuses_what_is_not_a_mode_without_raising(self) -> None:
        for value in ("brand_campaign", None, 5, "", "trend "):
            assert not is_known_mode(value)
