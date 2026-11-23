"""Unit tests for Phase-9 recovery contracts (ledger schemes 49-54)."""

from __future__ import annotations

import pytest

from backend.services.recovery_contracts import (
    MemoryCandidate,
    MemoryKind,
    MemoryRecord,
    ModelFamily,
    OutlineCandidate,
    RevisionEntry,
    TrajectoryError,
    build_revision_chain,
    check_input_integrity,
    classify_error_lifecycle,
    collect_source_closure,
    combined_uncertainty,
    compose_memories,
    delete_memory_closure,
    locate_critical_error,
    rank_outlines,
    render_revision_diffs,
    resolve_current_facts,
    select_harness_card,
    select_primary_outline,
)


def test_revision_chain_keeps_latest_limit_and_renders_diffs() -> None:
    revisions = [
        RevisionEntry("r1", "t1", "title", "旧标题", "新标题", "太机械"),
        RevisionEntry("r2", "t2", "body", "旧正文", "新正文", "补价格"),
        RevisionEntry("r3", "t3", "body", "新正文", "终稿", "再短一点"),
        RevisionEntry("r4", "t4", "title", "新标题", "终稿标题", "更具体"),
    ]
    chain = build_revision_chain("fact-1", "规则", revisions, limit=2)
    assert [item.revision_id for item in chain.revisions] == ["r3", "r4"]
    diffs = render_revision_diffs(chain)
    assert diffs[0]["old"] == "新正文"
    assert diffs[1]["operator_comment"] == "更具体"
    assert chain.as_dict()["fact_id"] == "fact-1"


def test_resolve_current_facts_folds_supersedes_chain() -> None:
    facts = [
        {"fact_id": "f1", "text": "旧价 399", "supersedes": ""},
        {"fact_id": "f2", "text": "新价 499", "supersedes": "f1", "reason": "旺季"},
        {"fact_id": "f3", "text": "免押", "supersedes": ""},
    ]
    current = resolve_current_facts(facts)
    assert [item["fact_id"] for item in current] == ["f2", "f3"]
    assert current[0]["reason"] == "旺季"


def test_error_lifecycle_and_critical_rollback() -> None:
    errors = [
        TrajectoryError(1, "trend_scout", "空列表", "local", is_critical=False),
        TrajectoryError(3, "content_strategist", "缺少实测证据", "critical", is_critical=True),
        TrajectoryError(4, "copywriter", "措辞问题", "local", is_critical=False),
        TrajectoryError(
            5, "review_gate", "已修复", "local", is_critical=False, downstream_recovered=True
        ),
    ]
    buckets = classify_error_lifecycle(errors)
    assert buckets["critical"] == (3,)
    assert buckets["dormant"] == (1, 4)
    assert buckets["self_healed"] == (5,)
    plan = locate_critical_error(errors, ["trend_scout", "content_strategist", "copywriter"])
    assert plan is not None
    assert plan.critical_step == 3
    assert plan.node == "content_strategist"
    assert plan.preserved_steps == (1,)
    assert "NEEDS" not in plan.directive
    assert locate_critical_error([errors[0]]) is None


def test_harness_selection_and_input_integrity() -> None:
    assert select_harness_card("magpie-mimo-v2.6-flash").family is ModelFamily.MIMO
    deepseek = select_harness_card("deepseek-v4.1-flash")
    assert deepseek.family is ModelFamily.DEEPSEEK
    assert "NEEDS_UPSTREAM_REPAIR" in deepseek.system_suffix
    other = select_harness_card("unknown-model")
    assert other.family is ModelFamily.OTHER
    report = check_input_integrity(
        {"title": "ok", "body": "...", "price": "", "_conflicts": {"price": "two values"}},
        ["title", "body", "price", "poi"],
    )
    assert report.missing == ("poi", "price")
    assert report.truncated == ("body",)
    assert report.contradictory == ("price",)
    assert report.needs_upstream_repair is True
    clean = check_input_integrity({"title": "ok"}, ["title"])
    assert clean.needs_upstream_repair is False


def test_combined_uncertainty_and_outline_selection() -> None:
    assert (
        combined_uncertainty(
            evidence_alignment=1.0,
            persona_coherence=1.0,
            estimated_repair_cost=0.0,
        )
        == 0.0
    )
    worst = combined_uncertainty(
        evidence_alignment=0.0,
        persona_coherence=0.0,
        estimated_repair_cost=1.0,
    )
    assert worst == 1.0
    ranked = rank_outlines(
        [
            OutlineCandidate("weak", 0.2, 0.2, 0.8),
            OutlineCandidate("strong", 0.9, 0.9, 0.1),
        ]
    )
    assert ranked[0].candidate.outline_id == "strong"
    selected = select_primary_outline([item.candidate for item in ranked])
    assert selected.candidate.outline_id == "strong"
    with pytest.raises(ValueError):
        select_primary_outline([])


def test_memcut_transitive_closure_deletion() -> None:
    records = [
        MemoryRecord("r1", ("t1",), "fact", "手机号 13800138000"),
        MemoryRecord("r2", ("t1", "t2"), "summary", "客户预算"),
        MemoryRecord("r3", ("t2", "t3"), "trail", "同行人数"),
        MemoryRecord("r4", ("t9",), "fact", "无关"),
    ]
    assert collect_source_closure(records, ["t1"]) == {"r1", "r2", "r3"}
    result = delete_memory_closure(records, ["t1"])
    assert result.deleted_ids == ("r1", "r2", "r3")
    assert result.retained_ids == ("r4",)
    assert result.expanded_turns == ("t2", "t3")
    assert result.residual_recovery_rate == 0.0
    empty = delete_memory_closure(records, [])
    assert empty.deleted_ids == ()
    assert len(empty.retained_ids) == 4


def test_empty_inputs_are_stable() -> None:
    assert rank_outlines([]) == []
    assert resolve_current_facts([]) == []
    assert compose_memories([]).selected == ()
    assert delete_memory_closure([], ["t1"]).deleted_ids == ()
    assert check_input_integrity({}, []).needs_upstream_repair is False


def test_memcomposer_topology_budget_and_epsilon() -> None:
    candidates = [
        MemoryCandidate(
            "m1", "场景", MemoryKind.SCENE_PATTERN, relevance=0.9, utility=1, tokens=100
        ),
        MemoryCandidate("m2", "合规", MemoryKind.COMPLIANCE, relevance=0.5, utility=1, tokens=100),
        MemoryCandidate("m3", "改稿", MemoryKind.HUMAN_DIFF, relevance=0.9, utility=1, tokens=100),
        MemoryCandidate("m4", "噪声", MemoryKind.OTHER, relevance=0.01, utility=0.01, tokens=100),
        MemoryCandidate("m5", "人设", MemoryKind.PERSONA, relevance=0.9, utility=1, tokens=100),
    ]
    composed = compose_memories(candidates, max_tokens=300, max_items=3)
    assert [item.memory_id for item in composed.selected] == ["m2", "m5", "m1"]
    assert composed.total_tokens == 300
    assert "m4" in composed.omitted_ids
    assert 0.0 <= composed.estimated_savings <= 1.0
    tight = compose_memories(candidates, max_tokens=150, max_items=3)
    assert len(tight.selected) == 1
    empty = compose_memories([])
    assert empty.selected == ()
    assert empty.total_tokens == 0
