"""The workflow modes, declared once.

A run's mode used to decide four different things, spread over three layers, and
every one of them spelled it the same way: read the mode out of the state
mapping, fall back to trend when it was missing, and compare it with the
string brief. That had two consequences.

* **A mode's behaviour was nowhere stated.** It was the conjunction of nine
  such branches, so "stop growing ``workflow_mode``" was an agreement rather
  than a mechanism -- adding a mode meant finding the branches that needed one
  more arm, and nothing failed if one was missed.
* **An unknown mode was indistinguishable from ``trend``.** Every read carried a
  ``"trend"`` default, so a run started with ``workflow_mode="foo"`` behaved
  exactly like a trend run and nothing anywhere said so.

This module is the single declaration. :func:`mode_spec` is the only place in
the repository that reads ``state["workflow_mode"]``; every other site asks a
spec a question the spec can answer. ``backend/graph/plan.py`` is where those
answers are checked against the graph that has to live up to them
(:func:`~backend.graph.plan.mode_registry_complaints`).

Where an unknown mode is refused, and where it is not
-----------------------------------------------------
:func:`get_mode_spec` raises :class:`UnknownWorkflowModeError`, and the request
boundary is typed as :class:`WorkflowMode`, so a *new* run cannot carry an
unknown mode: pydantic answers 422 and names the values it accepts.

:func:`mode_spec` -- the reader the routers and the agents use -- does **not**
raise, and that is deliberate rather than lenient. State read out of a
checkpoint is not something this layer is allowed to reject: raising inside a
graph node is the P1d shape (a ``KeyError`` on a path nobody watches), and a
thread persisted before this module existed would stop being readable at all,
against the P1 red line that existing checkpoints stay readable and are never
rewritten. So the state-side read is a **total** function whose fallback is
*declared* (:data:`DEFAULT_WORKFLOW_MODE`) and *reported* (a warning naming the
offending value) instead of being implied by a default argument.

Why the node names here are strings
----------------------------------
``backend/graph`` imports ``backend/agents``, which imports this module, so a
registry that named its nodes by importing the graph would close a cycle. The
strings are checked against the real node set where the graph is available
(``backend/graph/plan.py``), which is also where the same strings are compared
with ``PLAN_TEMPLATES``.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final, Literal

from backend.state.enums import WorkflowMode, WorkflowPhase

logger = logging.getLogger("xhs_growth.state.modes")

#: Every value a mode phase table may route to. Declared here rather than in
#: ``backend/graph/routers.py`` -- which re-exports it, so the name its readers
#: know still resolves -- because it is the vocabulary of a ``ModeSpec`` field:
#: spelling it as a ``Literal`` is what makes a typo in a phase table a static
#: error instead of a ``KeyError`` inside langgraph at run time.
OrchestratorDestination = Literal[
    "trend_scout",
    "brief_analyzer",
    "content_strategist",
    "copywriter",
    "analyst",
    "__end__",
]

#: Where a ripple ``reangle`` may send a run. The two answers all three ripple
#: routers choose between, narrowed to a type so they can return it directly.
ReanalysisDestination = Literal["content_strategist", "brief_analyzer"]


class UnknownWorkflowModeError(ValueError):
    """A value was asked to be a workflow mode and is not one.

    Named rather than a bare ``ValueError`` so a caller at a boundary can
    report which value was refused and which ones exist.
    """

    def __init__(self, value: Any) -> None:
        self.value = value
        super().__init__(
            f"{value!r} is not a workflow mode; known modes are "
            f"{sorted(mode.value for mode in WorkflowMode)}"
        )


@dataclass(frozen=True, slots=True)
class ModeSpec:
    """Everything the pipeline branches on, for one workflow mode."""

    mode: WorkflowMode

    #: The phase ``OrchestratorAgent`` writes into a run it is starting. This is
    #: not the same statement as :attr:`entry` -- one writes a phase, the other
    #: turns a phase into a node -- and the two *can* disagree, which is why
    #: ``plan.py`` checks ``phase_routes[initial_phase] == entry`` rather than
    #: trusting whoever edits this table next.
    initial_phase: WorkflowPhase

    #: Phase -> entry node, for ``orchestrator_router``. A phase that is not a
    #: key (another mode's phase, a legacy phase, a bare string a checkpoint
    #: still holds) routes to :attr:`entry` -- that fallback is why trend mode's
    #: ``creating`` lands on ``trend_scout``.
    phase_routes: Mapping[WorkflowPhase, OrchestratorDestination]

    #: Where a ripple ``reangle`` sends the run: re-analyze the input
    #: (``brief_analyzer``) or re-plan the content (``content_strategist``).
    #: All three ripple routers ask this one question.
    reanalysis_node: ReanalysisDestination

    #: Whether this mode runs the ``viral_matcher -> blogger_scout ->
    #: blogger_gate`` loop. ``False`` means the mode's copy is written from its
    #: input rather than from a selected blogger's notes, which is what makes
    #: ``blogger_gate`` answer ``copywriter`` unconditionally and ``draft_gate``
    #: short-circuit to ``shooting_planner``. That implication is checked
    #: against the plan template's exclusions; the converse deliberately is not,
    #: because a mode could run the loop and still short-circuit a gate for an
    #: unrelated reason, and asserting it would encode a coincidence as an
    #: invariant.
    runs_blogger_selection: bool

    def __post_init__(self) -> None:
        if WorkflowPhase.IDLE not in self.phase_routes:
            raise ValueError(
                f"{str(self.mode)!r} declares no {str(WorkflowPhase.IDLE)!r} route, so its "
                f"entry cannot be derived: {sorted(str(p) for p in self.phase_routes)}"
            )

    @property
    def entry(self) -> OrchestratorDestination:
        """The node a fresh run of this mode goes to.

        Derived from the IDLE route rather than declared a second time: two
        spellings of one fact can drift apart, and ``PLAN_TEMPLATES`` already
        carries an *independent* declaration of this value for ``plan.py``'s
        checker to compare against.
        """
        return self.phase_routes[WorkflowPhase.IDLE]

    def route(self, phase: Any) -> OrchestratorDestination:
        """The node ``phase`` routes to, or :attr:`entry` for anything else."""
        return self.phase_routes.get(phase, self.entry)


#: What an absent or unrecognised mode means. One constant rather than a
#: ``"trend"`` literal at each site: the literal appeared at eight read points
#: plus a response hydrator, a DB row decoder, a DB column default and an inline
#: whitelist, and the only way to see that they were all the same default was to
#: read them all. (The DB column keeps its own ``DEFAULT 'trend'`` because SQL
#: cannot import this; it is the one duplicate that is structural.)
DEFAULT_WORKFLOW_MODE: Final[WorkflowMode] = WorkflowMode.TREND

#: Per-mode declaration, exhaustive over :class:`WorkflowMode` members
#: (asserted by ``mode_registry_complaints``). The phase tables below are the
#: tables ``orchestrator_router`` used to hold inline, one per mode branch.
WORKFLOW_MODES: Final[Mapping[WorkflowMode, ModeSpec]] = MappingProxyType(
    {
        WorkflowMode.TREND: ModeSpec(
            mode=WorkflowMode.TREND,
            initial_phase=WorkflowPhase.SCOUTING,
            phase_routes={
                WorkflowPhase.SCOUTING: "trend_scout",
                WorkflowPhase.PLANNING: "content_strategist",
                WorkflowPhase.ANALYZING: "analyst",
                # Legacy checkpoints may still contain ENGAGING; no interaction
                # node exists anymore, so terminate instead of restarting work.
                WorkflowPhase.ENGAGING: "__end__",
                WorkflowPhase.ERROR: "__end__",
                WorkflowPhase.COMPLETED: "__end__",
                WorkflowPhase.IDLE: "trend_scout",
            },
            reanalysis_node="content_strategist",
            runs_blogger_selection=True,
        ),
        WorkflowMode.BRIEF: ModeSpec(
            mode=WorkflowMode.BRIEF,
            initial_phase=WorkflowPhase.BRIEFING,
            phase_routes={
                WorkflowPhase.BRIEFING: "brief_analyzer",
                WorkflowPhase.PLANNING: "content_strategist",
                WorkflowPhase.CREATING: "copywriter",
                WorkflowPhase.ANALYZING: "analyst",
                # Same legacy note as trend mode.
                WorkflowPhase.ENGAGING: "__end__",
                WorkflowPhase.ERROR: "__end__",
                WorkflowPhase.COMPLETED: "__end__",
                WorkflowPhase.IDLE: "brief_analyzer",
            },
            reanalysis_node="brief_analyzer",
            runs_blogger_selection=False,
        ),
    }
)


def is_known_mode(value: Any) -> bool:
    """Whether ``value`` names a declared mode.

    For the readers that must pass a value through rather than decide on it
    (a stored row, a response field): they need to know whether it is one of
    ours without being willing to raise over it.
    """
    try:
        WorkflowMode(value)
    except ValueError:
        return False
    return True


def get_mode_spec(mode: WorkflowMode | str) -> ModeSpec:
    """The spec for ``mode``, or :class:`UnknownWorkflowModeError`.

    The strict reader, for values that arrived from outside (a request field, a
    stored row) where refusing is both possible and better than guessing.
    """
    try:
        return WORKFLOW_MODES[WorkflowMode(mode)]
    except ValueError as exc:
        raise UnknownWorkflowModeError(mode) from exc


def stored_mode(state: Mapping[str, Any]) -> str | None:
    """The mode a thread carries **as stored**, or ``None`` when it has none.

    For the write-back that keeps a DB row in step with its thread. This one
    must not normalise, unlike every other read here: an unrecognised value is
    still the value the thread was created with, and rewriting it to the
    default would erase the only record that the thread predates the boundary
    (the red line is that stored runs are never rewritten). :func:`mode_spec`
    is the reader for anywhere that is about to *behave* on the mode.
    """
    raw = state.get("workflow_mode")
    if isinstance(raw, str) and raw:
        return str(raw)
    return None


def mode_spec(state: Mapping[str, Any]) -> ModeSpec:
    """The spec for the mode ``state`` carries -- the only reader of the key.

    Total by design; see the module docstring for why this one may not raise
    and :func:`get_mode_spec` may.
    """
    raw = state.get("workflow_mode")
    if raw is None:
        return WORKFLOW_MODES[DEFAULT_WORKFLOW_MODE]
    try:
        return WORKFLOW_MODES[WorkflowMode(raw)]
    except ValueError:
        logger.warning(
            "unknown workflow_mode %r on thread %r: falling back to %r. New runs are "
            "refused at the request boundary instead, so this is a checkpoint written "
            "before that boundary existed.",
            raw,
            state.get("thread_id") or state.get("session_id"),
            str(DEFAULT_WORKFLOW_MODE),
        )
        return WORKFLOW_MODES[DEFAULT_WORKFLOW_MODE]


__all__ = [
    "DEFAULT_WORKFLOW_MODE",
    "WORKFLOW_MODES",
    "ModeSpec",
    "OrchestratorDestination",
    "ReanalysisDestination",
    "UnknownWorkflowModeError",
    "get_mode_spec",
    "is_known_mode",
    "mode_spec",
    "stored_mode",
]
