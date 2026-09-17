"""A run's intent, as one value.

``POST /start`` used to state what a run was for in three places at once: the
request model, a 24-key dict literal, and a mode-conditional mutation of one of
that literal's keys. Nothing downstream could ask *what is this run for* -- the
request carried the same facts as loose fields, the state held 24 keys of which
20 were empty containers, and a caller had to know which key a brief body belongs
in when the artifact store accepted it and which one when it did not.

:class:`Goal` is that answer as a value, and :meth:`Goal.compile_initial_state` is
the single place that turns it into the mapping a run starts from.

Two facts about a run became answerable here, and only here
-----------------------------------------------------------

* **Where it starts.** The start phase is the *mode's*
  (:attr:`~backend.state.modes.ModeSpec.initial_phase`), never the caller's. The
  graph's entry is always ``orchestrator`` (``backend/graph/builder.py``) and that
  node unconditionally writes the mode's phase, so a caller-supplied phase never
  decided where a run went -- it only made the DB row and the ``/start`` response
  name a phase the graph was not in. ``WorkflowStartRequest`` no longer accepts
  one; see :attr:`Goal.start_phase`.
* **Whether it has to wait.** Brief mode with no body parks the run in
  ``awaiting_brief`` and does not start it. That condition is
  :attr:`Goal.waits_for_brief_upload` instead of a comparison spelled out at the
  call site.

What this module deliberately is not
------------------------------------

It does not narrow types beyond what the request boundary already guarantees, and
it never reads state. ``execution_mode`` stays a ``str``: that is the other,
orthogonal axis (``ExecutionMode``), and the ticket that owns this slice ruled it
out of scope -- see the "拒绝" section of the task's ``prd.md``.

A ``Goal`` is an *input*. It is never written into the state mapping, so no
checkpoint schema changes and no stored thread has to be rewritten.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from backend.state.enums import WorkflowMode, WorkflowPhase
from backend.state.modes import ModeSpec, get_mode_spec

__all__ = ["BriefInput", "Goal"]


@dataclass(frozen=True, slots=True)
class BriefInput:
    """The body of a brief run, and where that body ended up.

    ``ref`` is the artifact-store receipt when the store took the body. The
    ``PUT`` is best-effort and a run must never hold a ref to something that was
    never written, so a store that declined keeps the body inline instead. One
    value with two destinations, rather than two dict shapes decided by an ``if``
    at the call site.
    """

    body: Mapping[str, Any]
    ref: Mapping[str, Any] | None = None

    @property
    def is_stored(self) -> bool:
        """Whether the artifact store took the body (``ref`` holds the receipt)."""
        return self.ref is not None

    def as_state_fragment(self) -> dict[str, Any]:
        """The keys this brief contributes to a run's initial state."""
        if self.ref is not None:
            return {"artifacts": {"brief_content": dict(self.ref)}}
        return {"brief_content": dict(self.body)}


@dataclass(frozen=True, slots=True)
class Goal:
    """What a run is for: its mode, its target, its switches, and its start phase."""

    account_id: str
    thread_id: str
    mode: WorkflowMode
    topic: str | None
    niche: str
    niche_resolution: Mapping[str, Any]
    #: ``ExecutionMode`` value (``single`` / ``continuous``), kept as a ``str``
    #: because this slice does not own that axis -- see the module docstring.
    execution_mode: str
    dry_run: bool
    auto_publish: bool
    #: ``None`` for a run with no brief at all (trend mode, or a brief run whose
    #: text arrives later by upload).
    brief: BriefInput | None
    created_at: str

    @property
    def spec(self) -> ModeSpec:
        """The declaration of this run's mode (``backend/state/modes.py``)."""
        return get_mode_spec(self.mode)

    @property
    def start_phase(self) -> WorkflowPhase:
        """The phase this run starts in -- the mode's, never a caller's.

        Always a concrete :class:`WorkflowPhase`, so the two ``isinstance``
        guards this replaced (the key could hold a bare string) are gone.
        """
        return self.spec.initial_phase

    @property
    def waits_for_brief_upload(self) -> bool:
        """Whether this run parks until a brief arrives instead of starting."""
        return self.mode is WorkflowMode.BRIEF and self.brief is None

    def compile_initial_state(self) -> dict[str, Any]:
        """The mapping a run starts from -- the only place in the repository it is built.

        Every key is seeded explicitly, including the empty containers: the state
        schema declares them, and an absent key reads the same as an empty one to
        a reducer but not to a reader that asks whether the key exists.
        """
        state: dict[str, Any] = {
            "phase": self.start_phase,
            "current_agent": "orchestrator",
            "error": None,
            "retry_count": 0,
            "execution_mode": self.execution_mode,
            "workflow_mode": self.mode,
            "trend_data": {},
            "content_plan": {},
            "copy_content": {},
            "visual_plan": {},
            "publish_result": {},
            "analytics": {},
            "engagement_actions": [],
            "human_feedback": {},
            # No "performance_log" seed: P1a-S2 moved telemetry to the Event
            # store, and seeding the key would mark a new thread as legacy for
            # the inline-passthrough branch of the telemetry reader.
            "account_id": self.account_id,
            "session_id": self.thread_id,
            "thread_id": self.thread_id,
            "topic": self.topic,
            "niche": self.niche,
            "niche_resolution": dict(self.niche_resolution),
            "dry_run": self.dry_run,
            "auto_publish": self.auto_publish,
            "created_at": self.created_at,
            "updated_at": self.created_at,
        }
        if self.brief is not None:
            state.update(self.brief.as_state_fragment())
        return state
