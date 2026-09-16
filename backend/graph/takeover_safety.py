"""Which nodes an automatic takeover may resume.

S1 recorded who is running a thread and S2 made that record the answer
``/status`` gives, but neither let the lease *cause* anything: a ``kill -9``
still left the DB row saying "running" forever, and only a person hitting
``/recover`` moved it. S3 adds the loop that closes that gap -- a scan that
finds a lease whose owner stopped renewing and resumes the thread from its
checkpoint. Done reflexively that would re-run whatever the dead process was
in the middle of, and some of those nodes must not be re-run: ``publisher``
posts to Xiaohongshu.

Red line 2 ("never automatically re-run a node that already produced a side
effect") and ruling 3 ("a takeover may restore the execution loop, never make
a person's decision for them") both need a per-node answer, so this module
gives one.

The registry is exhaustive the same way ``RETRY_POLICIES`` is
(``backend/graph/error_handling.py``): every node ``build_graph()`` installs
must appear here, and an unknown name raises ``KeyError``. That direction
matters -- falling back to a default would answer "safe" for a node nobody
classified, which is the one wrong answer available here.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum

__all__ = [
    "TAKEOVER_HAZARDS",
    "TakeoverHazard",
    "takeover_hazard",
    "takeover_verdict",
]


class TakeoverHazard(StrEnum):
    """What resuming a node risks when nobody asked for it."""

    #: Re-running it repeats computation or a read. No external act.
    SAFE = "safe"
    #: It parks on ``interrupt()``. Advancing it means answering for a person.
    NEEDS_HUMAN = "needs_human"
    #: It performs an external, non-idempotent act. Never resume it silently.
    IRREVERSIBLE = "irreversible"


# A verdict names the most severe node it saw, so order the classes once here
# rather than at each call site.
_SEVERITY: dict[TakeoverHazard, int] = {
    TakeoverHazard.SAFE: 0,
    TakeoverHazard.NEEDS_HUMAN: 1,
    TakeoverHazard.IRREVERSIBLE: 2,
}

TAKEOVER_HAZARDS: dict[str, TakeoverHazard] = {
    # ── SAFE: computation and reads ──
    # These either call an LLM or read from XHS. Repeating them costs money and
    # time, which is why a takeover is worth logging, but nothing outside the
    # process changes state.
    "orchestrator": TakeoverHazard.SAFE,
    "trend_scout": TakeoverHazard.SAFE,
    "content_strategist": TakeoverHazard.SAFE,
    "copywriter": TakeoverHazard.SAFE,
    "visual_designer": TakeoverHazard.SAFE,
    "analyst": TakeoverHazard.SAFE,
    "revise_content": TakeoverHazard.SAFE,
    "viral_matcher": TakeoverHazard.SAFE,
    "blogger_scout": TakeoverHazard.SAFE,
    "content_analyzer": TakeoverHazard.SAFE,
    "version_generator": TakeoverHazard.SAFE,
    "brief_analyzer": TakeoverHazard.SAFE,
    "shooting_planner": TakeoverHazard.SAFE,
    # ── NEEDS_HUMAN: the node itself is where a person answers ──
    # Seven of these call interrupt() in their body. Resuming one with a bare
    # ainvoke(None) hands the gate None as the answer -- i.e. the scan would
    # answer on the person's behalf, which is exactly what ruling 3 forbids.
    "review_gate": TakeoverHazard.NEEDS_HUMAN,
    "choice_gate": TakeoverHazard.NEEDS_HUMAN,
    "draft_gate": TakeoverHazard.NEEDS_HUMAN,
    "brief_gate": TakeoverHazard.NEEDS_HUMAN,
    "ripple_gate": TakeoverHazard.NEEDS_HUMAN,
    "blogger_gate": TakeoverHazard.NEEDS_HUMAN,
    "publish_gate": TakeoverHazard.NEEDS_HUMAN,
    "ripple_finalize": TakeoverHazard.NEEDS_HUMAN,
    "ripple_late_recheck": TakeoverHazard.NEEDS_HUMAN,
    # The evaluator parks a thread on purpose (PAUSE_REASON_EVALUATOR_FAIL_CLOSED,
    # the P0-W5 continuation channel). Restarting that loop is a person's call.
    "evaluator_gate": TakeoverHazard.NEEDS_HUMAN,
    # ── IRREVERSIBLE ──
    # A real Xiaohongshu post. P0-W3 already refuses it framework-level auto
    # retry for this reason; the takeover must not become the retry path that
    # decision ruled out. Its retry channel is /publish-retry, which carries an
    # idempotency key and reconciles an unknown outcome before re-posting.
    "publisher": TakeoverHazard.IRREVERSIBLE,
}


def takeover_hazard(node_name: str) -> TakeoverHazard:
    """Hazard class for one node.

    Unknown names raise ``KeyError`` -- the same contract as
    ``get_retry_policy``, and for the same reason.
    """
    return TAKEOVER_HAZARDS[node_name]


def takeover_verdict(node_names: Iterable[str]) -> tuple[bool, TakeoverHazard | None]:
    """Whether the pending nodes may be resumed, plus the worst one if not.

    ``(True, None)`` means every pending node is :attr:`TakeoverHazard.SAFE` --
    ruling 3's condition read literally: the work still to be done carries no
    external side effect and asks nobody's permission.

    Only the *pending* nodes are classified, not everything reachable from
    them. That is sufficient rather than merely convenient, because the sole
    edge into ``publisher`` comes from ``publish_gate`` (see the
    ``publish_gate_outcome`` mapping in ``backend/graph/builder.py`` and the
    ``evaluator_gate`` routing above it), and ``publish_gate`` is itself
    NEEDS_HUMAN. A resume that would end in a re-post therefore has to park on
    a gate first, and the gate stops it.
    """
    worst: TakeoverHazard | None = None
    for name in node_names:
        hazard = takeover_hazard(name)
        if hazard is TakeoverHazard.SAFE:
            continue
        if worst is None or _SEVERITY[hazard] > _SEVERITY[worst]:
            worst = hazard
    return (worst is None), worst
