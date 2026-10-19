"""Signal inventory — the read side of the observe-only slices.

Six slices now write into one timeline: node/llm telemetry (P1a), effect
refusals and publish decisions (P0-B / P2a), verification verdicts (P1-B),
progress signals (P0-A, retry loop and revision loop), context recall (P1b).
Every one of them was added as "observe before adapting" — and until now there
was no way to *read the observations as a whole*. Answering "did this run
stall", "which verification tier did it take", "how many actions were refused"
meant parsing raw JSON by hand, which in practice means the policy the slices
were supposed to inform never gets decided.

This module is that reader. It is deliberately a **lookup, not an analysis**:

- It counts what the timeline contains, by kind and by reason.
- It does not score, rank, or recommend. A count is a fact; "the loop is too
  slow" is a judgement that needs a baseline this module does not have.
- It never invents a zero: a run with no events reports ``has_data=False``
  rather than 0 stalls, because "none observed" and "not observed" are
  different facts and only one of them is evidence.

Three honesty rules carried over from the node latency report:

1. **Kindless entries are node entries.** Entries from before the S2 migration
   carry no ``kind``; every reader in this repo treats absent as ``node``. They
   are counted *and* reported separately — silently folding them in would hide
   how much of the timeline predates the vocabulary.
2. **Unknown kinds are surfaced, not dropped.** A kind that is not in
   ``EVENT_KINDS`` means an emitter and the declaration have drifted (the #676
   failure). Counting them keeps the drift visible instead of rounding it away.
3. **Malformed entries are counted.** A non-mapping entry in the list is a data
   problem; a report that quietly skips it looks cleaner than the data is.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from backend.db.workflow_events import EVENT_KINDS

__all__ = [
    "SAMPLE_LIMIT",
    "ActionFacts",
    "ProgressFacts",
    "SignalInventory",
    "VerificationFacts",
    "inventory",
]

#: How many progress signals are echoed back verbatim. Enough to recognise the
#: shape of a stall, few enough that a long run does not dump its evidence.
SAMPLE_LIMIT = 3

#: Bucket label for an entry whose ``reason`` field is absent. Not a made-up
#: reason: it says the producer recorded the event without naming one.
UNSPECIFIED = "unspecified"


@dataclass(frozen=True)
class ProgressFacts:
    """``kind:"progress"`` — stall signals (P0-A)."""

    emitted: int = 0
    by_reason: tuple[tuple[str, int], ...] = ()
    windows: tuple[int, ...] = ()
    samples: tuple[Mapping[str, Any], ...] = ()


@dataclass(frozen=True)
class VerificationFacts:
    """``kind:"verification"`` — what the policy decided before a gate (P1-B)."""

    recorded: int = 0
    required: int = 0
    by_tier: tuple[tuple[str, int], ...] = ()
    by_reason: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True)
class ActionFacts:
    """``kind:"action"`` — refusals and their kind (P2a)."""

    refusals: int = 0
    by_action: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True)
class SignalInventory:
    has_data: bool
    total_entries: int = 0
    by_kind: tuple[tuple[str, int], ...] = ()
    kindless_node_entries: int = 0
    unknown_kinds: tuple[str, ...] = ()
    malformed_entries: int = 0
    progress: ProgressFacts = field(default_factory=ProgressFacts)
    verification: VerificationFacts = field(default_factory=VerificationFacts)
    action: ActionFacts = field(default_factory=ActionFacts)


def _ranked(counter: Counter[str]) -> tuple[tuple[str, int], ...]:
    """Deterministic ordering: count desc, then name — two runs must agree."""
    return tuple(sorted(counter.items(), key=lambda item: (-item[1], item[0])))


def _normalise_kind(entry: Mapping[str, Any]) -> tuple[str, bool]:
    """The kind a entry counts under, plus whether it was kindless."""
    raw = entry.get("kind")
    if raw is None or str(raw).strip() == "":
        return "node", True
    return str(raw), False


def _reason_of(entry: Mapping[str, Any]) -> str:
    return str(entry.get("reason") or UNSPECIFIED)


def inventory(
    events: Iterable[Mapping[str, Any] | Any],
    *,
    samples: int = SAMPLE_LIMIT,
) -> SignalInventory:
    """Count a timeline's signals. Read-only; no scoring, no recommendations.

    ``events`` accepts anything iterable — malformed items are counted in
    ``malformed_entries`` instead of raising, because a partial export is still
    evidence (and a crash here would make the export look worthless).
    """
    kinds: Counter[str] = Counter()
    unknown: set[str] = set()
    kindless = 0
    malformed = 0
    total = 0

    progress_reasons: Counter[str] = Counter()
    progress_windows: set[int] = set()
    progress_samples: list[Mapping[str, Any]] = []
    progress_emitted = 0

    verification_recorded = 0
    verification_required = 0
    verification_tiers: Counter[str] = Counter()
    verification_reasons: Counter[str] = Counter()

    action_refusals = 0
    action_names: Counter[str] = Counter()

    for entry in events:
        if not isinstance(entry, Mapping):
            malformed += 1
            continue
        total += 1
        kind, was_kindless = _normalise_kind(entry)
        kinds[kind] += 1
        if was_kindless:
            kindless += 1
        elif kind not in EVENT_KINDS:
            unknown.add(kind)

        if kind == "progress":
            progress_emitted += 1
            progress_reasons[_reason_of(entry)] += 1
            window = entry.get("window")
            if isinstance(window, int) and not isinstance(window, bool):
                progress_windows.add(window)
            if len(progress_samples) < samples:
                raw_evidence = entry.get("evidence")
                sample: dict[str, Any] = {
                    "reason": _reason_of(entry),
                    "window": window if isinstance(window, int) else None,
                    # ``dict(...)`` on a non-mapping (a stray string) would turn
                    # a malformed field into an exception that kills the whole
                    # report — the same trap the malformed-entry rule avoids.
                    "evidence": dict(raw_evidence) if isinstance(raw_evidence, Mapping) else None,
                }
                thread_id = entry.get("thread_id")
                if thread_id:
                    sample["thread_id"] = str(thread_id)
                progress_samples.append(sample)

        elif kind == "verification":
            verification_recorded += 1
            if entry.get("required") is True:
                verification_required += 1
            verification_tiers[str(entry.get("tier") or UNSPECIFIED)] += 1
            verification_reasons[_reason_of(entry)] += 1

        elif kind == "action":
            action_refusals += 1
            action_names[str(entry.get("action") or UNSPECIFIED)] += 1

    if total == 0:
        return SignalInventory(
            has_data=False,
            total_entries=0,
            malformed_entries=malformed,
        )

    return SignalInventory(
        has_data=True,
        total_entries=total,
        by_kind=_ranked(kinds),
        kindless_node_entries=kindless,
        unknown_kinds=tuple(sorted(unknown)),
        malformed_entries=malformed,
        progress=ProgressFacts(
            emitted=progress_emitted,
            by_reason=_ranked(progress_reasons),
            windows=tuple(sorted(progress_windows)),
            samples=tuple(progress_samples),
        ),
        verification=VerificationFacts(
            recorded=verification_recorded,
            required=verification_required,
            by_tier=_ranked(verification_tiers),
            by_reason=_ranked(verification_reasons),
        ),
        action=ActionFacts(
            refusals=action_refusals,
            by_action=_ranked(action_names),
        ),
    )
