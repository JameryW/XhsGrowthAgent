"""Promotion TTL defaults (票 5z / PRD §9 Q2).

Pins: every registered namespace defaults to ``None`` (never expire); unknown
namespaces also resolve to ``None``; ``ttl_expired_for`` is False when TTL is
null and only compares clocks when a positive TTL is configured; observation
and hy candidate builders fill ``ttl_seconds`` through the single resolve
entry (monkeypatch the table, not call sites).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from backend.context.models import TrustClass
from backend.creator_agent.models import ContentObservation, ContentObservationKind
from backend.memory.promotion import (
    DEFAULT_PROMOTION_POLICY_VERSION,
    PromotionCandidate,
)
from backend.memory.promotion_hy import (
    HyMemoryBatch,
    candidate_from_hy_memory,
    degraded_batch_candidate,
)
from backend.memory.promotion_ledger import PromotionRecord
from backend.memory.promotion_observations import (
    TARGET_NAMESPACE,
    candidate_from_observation,
    source_check_from_observation,
)
from backend.memory.promotion_review import _candidate_from_ledger_body
from backend.memory.promotion_ttl import (
    PROMOTION_TTL_SECONDS,
    resolve_promotion_ttl,
    ttl_expired_for,
)

_OBSERVED = "2026-10-01T00:00:00Z"
_NOW = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)


def _candidate(
    *, ttl_seconds: int | None = None, observed_at: str = _OBSERVED
) -> PromotionCandidate:
    return PromotionCandidate(
        namespace=TARGET_NAMESPACE,
        key="style:style_1",
        body="body",
        trust_class=TrustClass.INTERNAL_FACT,
        source_ref="creative-memory://style/style_1",
        source_version=observed_at,
        observed_at=observed_at,
        evidence_ids=("ev_style_style_1",),
        sample_count=10,
        measured_rate=0.4,
        ttl_seconds=ttl_seconds,
    )


def _style(observed_at: str = _OBSERVED) -> ContentObservation:
    return ContentObservation(
        kind=ContentObservationKind.STYLE,
        source_id="style_1",
        description="治愈/温暖治愈",
        measured_rate=0.4,
        sample_count=10,
        observed_at=observed_at,
    )


class TestResolvePromotionTtl:
    def test_registered_namespaces_default_to_null(self) -> None:
        for namespace in (
            "strategy_notes",
            "audience_preferences",
            "performance_insights",
            "content_history",
        ):
            assert resolve_promotion_ttl(namespace) is None
            assert PROMOTION_TTL_SECONDS[namespace] is None

    def test_unknown_namespace_resolves_to_none_without_raising(self) -> None:
        assert resolve_promotion_ttl("plays") is None
        assert resolve_promotion_ttl("materials") is None
        assert resolve_promotion_ttl("not-a-real-ns") is None


class TestTtlExpiredFor:
    def test_null_ttl_never_expires(self) -> None:
        candidate = _candidate(ttl_seconds=None)
        assert ttl_expired_for(candidate, now=_NOW) is False
        assert ttl_expired_for(candidate, now=_NOW + timedelta(days=3650)) is False

    def test_positive_ttl_not_yet_expired(self) -> None:
        candidate = _candidate(ttl_seconds=86_400)
        assert ttl_expired_for(candidate, now=_NOW) is False

    def test_positive_ttl_expired_at_boundary(self) -> None:
        candidate = _candidate(ttl_seconds=86_400)
        boundary = datetime(2026, 10, 2, 0, 0, 0, tzinfo=UTC)
        assert ttl_expired_for(candidate, now=boundary) is True
        assert ttl_expired_for(candidate, now=boundary - timedelta(seconds=1)) is False

    def test_observed_at_kwarg_overrides_candidate_anchor(self) -> None:
        candidate = _candidate(ttl_seconds=60, observed_at=_OBSERVED)
        # Candidate says Oct 1; override says a minute ago relative to _NOW.
        recent = (_NOW - timedelta(seconds=30)).isoformat().replace("+00:00", "Z")
        assert ttl_expired_for(candidate, now=_NOW, observed_at=recent) is False
        old = (_NOW - timedelta(seconds=120)).isoformat().replace("+00:00", "Z")
        assert ttl_expired_for(candidate, now=_NOW, observed_at=old) is True


class TestCandidateWiring:
    def test_observation_candidate_uses_resolve_entry(self) -> None:
        with patch.dict(
            "backend.memory.promotion_ttl.PROMOTION_TTL_SECONDS",
            {TARGET_NAMESPACE: 3_600},
            clear=False,
        ):
            candidate = candidate_from_observation(_style())
        assert candidate.ttl_seconds == 3_600

    def test_observation_candidate_defaults_to_null(self) -> None:
        assert candidate_from_observation(_style()).ttl_seconds is None

    def test_hy_candidate_uses_resolve_entry(self) -> None:
        memory = {
            "memory_id": "mem_1",
            "content": "用户偏好测评体标题",
            "metadata": {"source_version": _OBSERVED},
        }
        with patch.dict(
            "backend.memory.promotion_ttl.PROMOTION_TTL_SECONDS",
            {TARGET_NAMESPACE: 7_200},
            clear=False,
        ):
            candidate = candidate_from_hy_memory(memory)
        assert candidate.ttl_seconds == 7_200

    def test_hy_candidate_defaults_to_null(self) -> None:
        candidate = candidate_from_hy_memory(
            {"memory_id": "mem_1", "content": "用户偏好测评体标题"}
        )
        assert candidate.ttl_seconds is None

    def test_degraded_batch_candidate_uses_resolve_entry(self) -> None:
        batch = HyMemoryBatch(
            account_id="acc-1",
            scene="default",
            degraded=True,
            error="sdk unavailable",
        )
        with patch.dict(
            "backend.memory.promotion_ttl.PROMOTION_TTL_SECONDS",
            {TARGET_NAMESPACE: 1_800},
            clear=False,
        ):
            assert degraded_batch_candidate(batch).ttl_seconds == 1_800

    def test_human_review_ledger_rebuild_uses_resolve_entry(self) -> None:
        record = PromotionRecord(
            promotion_id="promo_1",
            candidate_id="cand_1",
            namespace=TARGET_NAMESPACE,
            key="hy:deadbeef",
            source_ref="hy-memory://chat/mem_1",
            source_version=_OBSERVED,
            disposition="review",
            reason="needs_human_review",
            dedupe="new",
            verified=True,
            supersedes=(),
            decided_by="machine",
            policy_version=DEFAULT_PROMOTION_POLICY_VERSION,
            recorded_at=_OBSERVED,
            body="一条待人审的 hy 记忆",
        )
        with patch.dict(
            "backend.memory.promotion_ttl.PROMOTION_TTL_SECONDS",
            {TARGET_NAMESPACE: 9_000},
            clear=False,
        ):
            rebuilt = _candidate_from_ledger_body(record)
        assert rebuilt.ttl_seconds == 9_000


class TestSourceCheckWiring:
    def test_null_ttl_keeps_ttl_expired_false(self) -> None:
        check = source_check_from_observation(_style(), now=_NOW)
        assert check.ttl_expired is False

    def test_positive_ttl_marks_expired_when_past(self) -> None:
        with patch.dict(
            "backend.memory.promotion_ttl.PROMOTION_TTL_SECONDS",
            {TARGET_NAMESPACE: 60},
            clear=False,
        ):
            candidate = candidate_from_observation(_style())
            check = source_check_from_observation(
                _style(),
                candidate=candidate,
                now=datetime(2026, 10, 1, 0, 2, 0, tzinfo=UTC),
            )
        assert check.ttl_expired is True

    def test_positive_ttl_not_expired_when_fresh(self) -> None:
        with patch.dict(
            "backend.memory.promotion_ttl.PROMOTION_TTL_SECONDS",
            {TARGET_NAMESPACE: 86_400},
            clear=False,
        ):
            candidate = candidate_from_observation(_style())
            check = source_check_from_observation(_style(), candidate=candidate, now=_NOW)
        assert check.ttl_expired is False


@pytest.mark.parametrize(
    "namespace",
    ["strategy_notes", "audience_preferences", "performance_insights", "content_history"],
)
def test_table_lists_every_memory_manager_namespace(namespace: str) -> None:
    assert namespace in PROMOTION_TTL_SECONDS
