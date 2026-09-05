"""Pure read projection for the Creator Agent Decision Dataset."""

from __future__ import annotations

from collections.abc import Iterable

from backend.creator_agent.models import (
    DecisionDatasetEntry,
    DecisionDatasetPage,
    DecisionRecord,
    DecisionStatus,
    FeedbackOutcome,
    LearningSignal,
    decode_decision_dataset_cursor,
    encode_decision_dataset_cursor,
)


def build_decision_dataset_page(
    decisions: Iterable[DecisionRecord],
    signals: Iterable[LearningSignal],
    *,
    audience_id: str | None = None,
    status: DecisionStatus | None = None,
    feedback_outcome: FeedbackOutcome | None = None,
    has_feedback: bool | None = None,
    cursor: str | None = None,
    limit: int = 20,
) -> DecisionDatasetPage:
    """Assemble a deterministic page from immutable decision/signal snapshots.

    Filtering occurs before ``total`` and cursor traversal.  This function is
    intentionally storage-independent so the memory fallback and Postgres
    adapter share exactly the same projection semantics.
    """

    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")

    decoded_cursor = decode_decision_dataset_cursor(cursor) if cursor is not None else None
    normalized_audience = audience_id.strip() if audience_id is not None else None
    if normalized_audience == "":
        raise ValueError("audience_id cannot be empty")

    signal_ids_by_decision: dict[tuple[str, str], list[str]] = {}
    for signal in signals:
        key = (signal.account_id, signal.decision_id)
        signal_ids_by_decision.setdefault(key, []).append(signal.signal_id)
    for signal_ids in signal_ids_by_decision.values():
        signal_ids.sort()

    filtered: list[DecisionRecord] = []
    for decision in decisions:
        if normalized_audience is not None and decision.audience_id != normalized_audience:
            continue
        if status is not None and decision.status != status:
            continue
        feedback = decision.feedback
        if feedback_outcome is not None and not any(
            item.outcome == feedback_outcome for item in feedback
        ):
            continue
        if has_feedback is not None and bool(feedback) is not has_feedback:
            continue
        filtered.append(decision)

    filtered.sort(key=lambda item: (item.created_at, item.decision_id), reverse=True)
    total = len(filtered)
    if decoded_cursor is not None:
        cursor_created_at, cursor_decision_id = decoded_cursor
        filtered = [
            decision
            for decision in filtered
            if (
                decision.created_at < cursor_created_at
                or (
                    decision.created_at == cursor_created_at
                    and decision.decision_id < cursor_decision_id
                )
            )
        ]

    selected = filtered[: limit + 1]
    has_next = len(selected) > limit
    entries = [
        DecisionDatasetEntry(
            decision=decision.model_copy(deep=True),
            learning_signal_ids=list(
                signal_ids_by_decision.get((decision.account_id, decision.decision_id), [])
            ),
        )
        for decision in selected[:limit]
    ]
    next_cursor = (
        encode_decision_dataset_cursor(
            entries[-1].decision.created_at,
            entries[-1].decision.decision_id,
        )
        if has_next and entries
        else None
    )
    return DecisionDatasetPage(
        items=entries,
        total=total,
        limit=limit,
        next_cursor=next_cursor,
    )


# This alias mirrors the repository method's terminology for callers that
# want to use the pure projection without importing the longer function name.
project_decision_dataset = build_decision_dataset_page


__all__ = [
    "build_decision_dataset_page",
    "decode_decision_dataset_cursor",
    "encode_decision_dataset_cursor",
    "project_decision_dataset",
]
