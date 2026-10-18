"""Progress Detector — evidence-based stall signals for agent loops (P0-A).

The revise loop (`revise_content`) is currently bounded only by a maximum
number of rounds. Round 3 may mean "the draft is converging" or "the same
failure is repeating"; the two need different handling (continue vs escalate),
but nothing in the system distinguishes them.

This module answers one question from the run's own event timeline:

    Is the loop still producing *new information*, or is it cycling?

Design constraints (deliberate, keep them when extending):

1. **Read-only.** Nothing here is wired into an agent or the graph yet; the
   signal is emitted for observation so the policy can be decided on evidence
   (the same "observe before adapting" order as the Context Compiler baseline).
2. **Evidence over counting.** A stall is "the same error fingerprint twice in
   a row" or "two tool calls returned the same payload", never "N rounds have
   elapsed" — a fast loop that keeps learning is not stalled.
3. **Structural output.** :class:`ProgressSignal` carries the evidence needed
   to act (fingerprints, digests, window), not a bare boolean.

The two acceptance-oriented rules from the design note (budget spent without
acceptance movement, revision without score movement) are intentionally not
implemented here: they need acceptance/score inputs that no caller supplies
yet, and inventing them would make the signal look more informed than it is.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "PROGRESS_EVENT_KIND",
    "ProgressSignal",
    "detect_progress",
    "progress_event",
]

#: Event kind for an emitted signal. Declared here and consumed by
#: ``progress_event`` so the vocabulary and the emitter cannot drift.
PROGRESS_EVENT_KIND = "progress"


@dataclass(frozen=True)
class ProgressSignal:
    """Outcome of one detection pass.

    ``stalled`` is False for an empty or too-short timeline: absence of
    evidence is not evidence of progress, and it is not evidence of a stall
    either — callers must not read False as "healthy", only as "no signal".
    """

    stalled: bool
    reason: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)
    window: int = 0

    def to_event(self, *, account_id: str = "", thread_id: str = "") -> dict[str, Any] | None:
        """The signal as an Event-store entry, or None when not stalled."""
        if not self.stalled:
            return None
        return progress_event(self, account_id=account_id, thread_id=thread_id)


def _fingerprint(value: Any) -> str:
    """Stable short digest for error/output comparison.

    Errors arrive as strings or structured dicts depending on the producer;
    both must fingerprint by content, not by ``repr`` order. Non-JSON values
    fall back to their string form so an exotic payload degrades to a weaker
    comparison instead of raising.
    """
    if isinstance(value, (Mapping, list, tuple)):
        try:
            payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        except (TypeError, ValueError):
            payload = str(value)
    else:
        payload = str(value)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _error_text(entry: Mapping[str, Any]) -> str:
    """The error an entry carries, if any.

    Producers differ: node/llm events use ``error``; tool events may use
    ``error_type`` + ``message``. Missing or empty means "no error", which
    must not participate in the repetition rule.
    """
    error = entry.get("error")
    if isinstance(error, Mapping):
        error = error.get("message") or error.get("type")
    text = str(error or "").strip()
    if text:
        return text
    error_type = str(entry.get("error_type") or "").strip()
    if error_type:
        return f"{error_type}:{entry.get('message') or ''}".strip()
    return ""


def _tool_output(entry: Mapping[str, Any]) -> Any:
    """Payload of a tool event, or a sentinel when the entry is not one."""
    if str(entry.get("kind") or "") != "tool":
        return None
    for key in ("result", "output", "payload", "content"):
        if key in entry:
            return entry[key]
    return None


def detect_progress(
    events: Sequence[Mapping[str, Any]],
    *,
    window: int = 3,
) -> ProgressSignal:
    """Detect a stalled loop from a run's event timeline.

    Two rules, checked in order of specificity:

    - ``same_error_repeated``: the trailing ``window`` events that carry an
      error all share one fingerprint. A window of 3 means three consecutive
      failing attempts with the *same* failure — the canonical "retry that
      cannot succeed" shape.
    - ``tool_output_repeated``: the trailing ``window`` tool events returned
      byte-identical payloads. Evidence gain is zero even though actions are
      being taken.

    ``window`` is clamped to >= 2: a single occurrence cannot be a repetition,
    and silently accepting 1 would make every failure a stall.

    Rule order matters: an error stall is more actionable than an output stall
    (the latter may be a legitimate idempotent read), so it wins when both
    hold.
    """
    window = max(2, int(window))
    if len(events) < window:
        # Below one full window there is no repetition to observe; "not
        # stalled" here means "not enough evidence", not "healthy".
        return ProgressSignal(stalled=False, window=window)

    # Both rules judge the *trailing run of events*, not "the last N events
    # that happen to carry the signal". A success between two failures is new
    # information — the loop got somewhere — so it breaks the run.

    # Rule 1: the trailing `window` events all failed with one fingerprint.
    tail = events[-window:]
    tail_errors = [_error_text(entry) for entry in tail]
    if all(tail_errors):
        prints = [_fingerprint(text) for text in tail_errors]
        if len(set(prints)) == 1:
            return ProgressSignal(
                stalled=True,
                reason="same_error_repeated",
                evidence={
                    "fingerprint": prints[0],
                    "count": window,
                    "last_error": tail_errors[-1],
                },
                window=window,
            )

    # Rule 2: the trailing `window` events are all tool calls returning
    # byte-identical payloads. Only a contiguous tool run counts — an LLM
    # turn in between means the loop is still thinking.
    tail_tools = [_tool_output(entry) for entry in tail]
    if all(value is not None for value in tail_tools):
        digests = [_fingerprint(value) for value in tail_tools]
        if len(set(digests)) == 1:
            return ProgressSignal(
                stalled=True,
                reason="tool_output_repeated",
                evidence={
                    "digest": digests[0],
                    "count": window,
                },
                window=window,
            )

    return ProgressSignal(stalled=False, window=window)


def progress_event(
    signal: ProgressSignal,
    *,
    account_id: str = "",
    thread_id: str = "",
) -> dict[str, Any]:
    """Render a stalled signal as an Event-store entry.

    Same shape discipline as ``action_perf_entry``: reserved keys are written
    last so ``evidence`` cannot spoof them, and free text stays out — the
    evidence is machine-readable identifiers, which is what a timeline is for.
    """
    from datetime import UTC, datetime

    entry: dict[str, Any] = {
        "reason": signal.reason,
        "evidence": dict(signal.evidence),
        "window": signal.window,
        "kind": PROGRESS_EVENT_KIND,
        "account_id": account_id,
        "thread_id": thread_id,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    return entry
