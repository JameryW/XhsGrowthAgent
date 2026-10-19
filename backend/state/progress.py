"""Progress Detector — evidence-based stall signals for agent loops (P0-A).

The revise loop (`revise_content`) is currently bounded only by a maximum
number of rounds. Round 3 may mean "the draft is converging" or "the same
failure is repeating"; the two need different handling (continue vs escalate),
but nothing in the system distinguishes them.

This module answers one question from the run's own event timeline:

    Is the loop still producing *new information*, or is it cycling?

Design constraints (deliberate, keep them when extending):

1. **Observe before acting.** The signal is emitted (event + log) but never
   routes: the retry loop's budget still decides whether to retry (#675) and
   the revision loop's ``max_revision_count`` still decides whether to stop.
   Policy comes after the evidence has been collected from real runs.
2. **Evidence over counting.** A stall is "the same error fingerprint twice in
   a row" or "two tool calls returned the same payload", never "N rounds have
   elapsed" — a fast loop that keeps learning is not stalled.
3. **Structural output.** :class:`ProgressSignal` carries the evidence needed
   to act (fingerprints, digests, window), not a bare boolean.

Two inputs answer the same question at different granularity:

- :func:`detect_progress` reads a run's **event timeline** — one node's
  internal retry loop (LLM correction rejected twice the same way).
- :func:`detect_revision_stall` reads the **round records** of the
  evaluator→copywriter loop — "round 3 is converging" vs "round 3 is the same
  complaint again". The records come from :func:`revision_record`, which the
  revise node appends; scores/hints exist only there, which is why the
  acceptance-oriented rules had no input until now.

``budget_without_acceptance`` remains unimplemented: it needs a run-level
budget on state, which does not exist (§8 F7 is a recorded SKIP for the same
reason). Inventing one would make the signal look better informed than it is.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "PROGRESS_EVENT_KIND",
    "REVISION_NO_IMPROVEMENT",
    "REVISION_SAME_HINTS",
    "ProgressSignal",
    "detect_progress",
    "detect_revision_stall",
    "progress_event",
    "revision_record",
]

#: Event kind for an emitted signal. Declared here and consumed by
#: ``progress_event`` so the vocabulary and the emitter cannot drift.
PROGRESS_EVENT_KIND = "progress"

#: The evaluator asked for the same fix again: the writer was told "X" in round
#: N and the panel returned "X" after round N+1's rewrite.
REVISION_SAME_HINTS = "same_hints_repeated"

#: Rounds were spent but the panel's overall score did not move. Distinct from
#: the rule above: the complaints may differ (the writer changed *something*)
#: while the result is equally unacceptable — "revising" without "improving".
REVISION_NO_IMPROVEMENT = "revised_without_improvement"


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


def revision_record(
    round_no: int,
    evaluation: Mapping[str, Any] | None,
    *,
    max_hints: int = 40,
) -> dict[str, Any] | None:
    """Compact record of the verdict that is about to cost one revision round.

    Returns ``None`` when there is no verdict to record (no evaluation yet, or
    a caller that reaches the revise node without one — the human
    ``needs_revision`` path). Absence of a verdict must not fabricate a record:
    a neutral filler would look like "no change" and manufacture stalls.

    What is stored, and what is not:

    - ``hints_digest`` is a fingerprint of the *sorted* revision hints, not the
      hint text. The text already lives in ``evaluation_result``; duplicating
      it into an append-only history would grow the checkpoint for every round
      and could not be redacted (the same reason node latency uses counts).
    - ``score`` is ``None`` when the panel degraded (no usable judgement).
      A degraded round carries no evidence either way, so the score rule
      ignores it rather than reading it as "no improvement".
    - ``round`` is the *revision* number this verdict triggered. The revise
      node derives it from ``revision_count``, which the human-triggered
      ``revise`` resume resets to 0 — so round numbers restart there, and
      :func:`detect_revision_stall` treats the reset as an epoch boundary
      instead of comparing across it.
    """
    if not evaluation:
        return None

    raw_score = evaluation.get("overall_score")
    score: float | None = None
    if isinstance(raw_score, (int, float)) and not isinstance(raw_score, bool):
        score = float(raw_score)

    hints = [str(hint) for hint in (evaluation.get("revision_hints") or []) if str(hint).strip()]
    digest = _fingerprint(sorted(hints[:max_hints])) if hints else ""

    decision = evaluation.get("decision")
    return {
        "round": int(round_no),
        "score": score,
        "hints_digest": digest,
        "decision": getattr(decision, "value", str(decision or "")),
        "degraded": bool(evaluation.get("degraded"))
        or str(evaluation.get("status") or "") == "degraded",
    }


def _current_epoch(rounds: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """The trailing run of rounds that belong to one revision budget.

    Round numbers are assigned from ``revision_count``, which a human-triggered
    ``revise`` resume resets to 0. A decrease (or a gap) is that reset, not a
    failure: comparing pre-reset rounds against post-reset ones would report a
    stall for a loop the operator deliberately restarted with a fresh budget.
    Only the suffix is dropped — the history itself is append-only telemetry.
    """
    epoch: list[Mapping[str, Any]] = []
    expected: int | None = None
    for entry in reversed(rounds):
        try:
            number = int(entry.get("round"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            break
        if expected is not None and number != expected:
            break
        epoch.append(entry)
        expected = number - 1
    epoch.reverse()
    return epoch


def detect_revision_stall(
    rounds: Sequence[Mapping[str, Any]],
    *,
    window: int = 2,
    min_gain: float = 1.0,
) -> ProgressSignal:
    """Is the evaluator→copywriter loop still producing *new* outcomes?

    ``rounds`` are :func:`revision_record` entries in chronological order. Two
    rules, in order of specificity:

    - ``same_hints_repeated``: the trailing ``window`` verdicts asked for the
      same fix (identical hint digest, non-empty). The writer complied and the
      panel disagreed with the result the same way — the canonical "retry that
      cannot succeed" shape.
    - ``revised_without_improvement``: the panel's score gained less than
      ``min_gain`` across the trailing ``window`` verdicts. Different
      complaints, same verdict — rounds are being spent without moving the
      number that decides the gate.

    ``min_gain`` defaults to one point on the panel's 0-100 scale: a rounding
    wobble is not progress. Rounds whose score is ``None`` (degraded panel) are
    skipped by the score rule, and a window with fewer than two usable scores
    returns no signal — "not enough evidence" is not "stalled".
    """
    window = max(2, int(window))
    cleaned = [entry for entry in rounds if isinstance(entry, Mapping)]
    epoch = _current_epoch(cleaned)
    if len(epoch) < window:
        return ProgressSignal(stalled=False, window=window)

    tail = epoch[-window:]

    digests = [str(entry.get("hints_digest") or "") for entry in tail]
    if all(digests) and len(set(digests)) == 1:
        return ProgressSignal(
            stalled=True,
            reason=REVISION_SAME_HINTS,
            evidence={
                "hints_digest": digests[0],
                "count": window,
                "rounds": [entry.get("round") for entry in tail],
            },
            window=window,
        )

    scores = [
        entry.get("score") if isinstance(entry.get("score"), (int, float)) else None
        for entry in tail
    ]
    if all(score is not None for score in scores):
        usable = [float(score) for score in scores]  # type: ignore[arg-type]
        gain = usable[-1] - usable[0]
        if gain < min_gain:
            return ProgressSignal(
                stalled=True,
                reason=REVISION_NO_IMPROVEMENT,
                evidence={
                    "scores": usable,
                    "gain": gain,
                    "min_gain": min_gain,
                    "rounds": [entry.get("round") for entry in tail],
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
