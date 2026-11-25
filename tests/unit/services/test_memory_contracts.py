from __future__ import annotations

import pytest

from backend.services.memory_contracts import (
    EpicPreferenceIndex,
    ForkMessage,
    MemoryScope,
    PearlGramState,
    PreferenceEntry,
    RecallCandidate,
    SensitiveAttribute,
    StreamingMemoryAction,
    TrajectoryMetrics,
    build_presupposition_safe_reply,
    evaluate_stream_event,
    evaluate_visual_trajectory,
    isolate_fork_context,
    remind_compound_recall,
    scan_presuppositions,
)


def test_pearl_decays_only_residual_dimensions() -> None:
    state = PearlGramState(residual_threshold=0.25, decay=0.5, floor=0.05)
    state.observe({"winter_route": 1.0, "persona": 1.0})
    result = state.register_residual({"winter_route": 0.4, "persona": 0.05})
    assert result.decayed_dimensions == ("winter_route",)
    assert result.kept_dimensions == ("persona",)
    assert result.detection_delay == 1
    assert state.confidence("winter_route") == 0.5
    assert state.confidence("persona") == 1.0


def test_pearl_respects_floor_and_validates_params() -> None:
    state = PearlGramState(residual_threshold=0.1, decay=0.5, floor=0.05)
    state.observe({"drift": 0.01})
    state.register_residual({"drift": 1.0})
    assert state.confidence("drift") == 0.05
    assert state.dimensions() == ("drift",)
    with pytest.raises(ValueError):
        PearlGramState(decay=0.0)
    with pytest.raises(ValueError):
        PearlGramState(residual_threshold=-0.1)
    with pytest.raises(ValueError):
        state.observe({"drift": 1.0}, weight=0.0)


def test_stream_event_priority_conflict_over_supplement() -> None:
    decision = evaluate_stream_event(
        "本次合作车行贴纸已经露出，封面用了荧光绿",
        forbidden_terms=("合作车行",),
        supplement_terms=("荧光绿",),
        scope=MemoryScope.PROJECT_VALUE,
    )
    assert decision.action is StreamingMemoryAction.PRE_COMMIT_INTERVENTION
    assert decision.scope is MemoryScope.PROJECT_VALUE
    assert decision.matched_terms == ("合作车行",)
    assert decision.as_dict()["reason"] == "forbidden_term_conflict"


def test_stream_event_supplement_and_silence() -> None:
    supplement = evaluate_stream_event(
        "封面用了荧光绿",
        forbidden_terms=("合作车行",),
        supplement_terms=("荧光绿",),
    )
    assert supplement.action is StreamingMemoryAction.SUPPLEMENT
    assert supplement.scope is MemoryScope.TOPIC_GRAPH
    silent = evaluate_stream_event("普通草稿正文")
    assert silent.action is StreamingMemoryAction.SILENCE
    assert silent.matched_terms == ()


def test_compound_recall_walks_three_hops_to_sufficiency() -> None:
    candidates = [
        RecallCandidate("m1", "川西高海拔路线 SOP 需备氧气瓶", 0.9),
        RecallCandidate("m2", "高反氧气瓶赠品话术", 0.7),
        RecallCandidate("m3", "国庆旺季异地还车押金规则", 0.6),
    ]
    result = remind_compound_recall(
        candidates,
        "国庆川西7天自驾攻略",
        required_slots=("氧气瓶", "押金"),
    )
    assert result.stop_reason == "sufficient"
    assert [item.memory_id for item in result.selected] == ["m1", "m2", "m3"]
    assert len(result.hops) == 3
    assert result.hops[0].selected == ("m1",)
    assert "氧气" in result.hops[0].added_terms
    assert result.as_dict()["stop_reason"] == "sufficient"


def test_compound_recall_stops_on_exhaustion_and_max_hops() -> None:
    candidates = [RecallCandidate("m1", "川西高海拔路线", 0.9)]
    exhausted = remind_compound_recall(candidates, "川西", required_slots=("押金",))
    assert exhausted.stop_reason == "exhausted"
    assert exhausted.hops[0].added_terms == ()
    capped = remind_compound_recall(
        [
            RecallCandidate("m1", "川西高海拔路线", 0.9),
            RecallCandidate("m2", "川西押金规则", 0.8),
        ],
        "川西",
        required_slots=("押金",),
        max_hops=1,
    )
    assert capped.stop_reason == "max_hops"
    assert len(capped.selected) == 1
    filtered = remind_compound_recall(candidates, "川西", min_score=0.95)
    assert filtered.stop_reason == "exhausted"
    assert filtered.selected == ()
    with pytest.raises(ValueError):
        remind_compound_recall(candidates, "川西", max_hops=0)


def test_presupposition_scan_flags_unmentioned_attributes() -> None:
    draft = "看您上次带老人小孩预算比较紧，这次还选经济型吗？"
    attributes = [
        SensitiveAttribute("family", ("老人", "小孩")),
        SensitiveAttribute("budget", ("预算比较紧",), severity="medium"),
    ]
    findings = scan_presuppositions(draft, attributes)
    assert [(item.label, item.term) for item in findings] == [
        ("family", "老人"),
        ("family", "小孩"),
        ("budget", "预算比较紧"),
    ]
    assert findings[2].severity == "medium"


def test_presupposition_safe_reply_drops_offending_clauses() -> None:
    draft = "看您上次带老人小孩预算比较紧，这次还选经济型吗？"
    attributes = [
        SensitiveAttribute("family", ("老人", "小孩")),
        SensitiveAttribute("budget", ("预算比较紧",), severity="medium"),
    ]
    report = build_presupposition_safe_reply(draft, attributes)
    assert report.blocked is True
    assert report.removed_clauses == 1
    assert report.safe_draft == "这次还选经济型吗？"
    allowed = build_presupposition_safe_reply(
        draft,
        attributes,
        mentioned_terms=("老人", "小孩"),
    )
    assert [item.label for item in allowed.findings] == ["budget"]
    permissive = build_presupposition_safe_reply(draft, attributes, allowed_labels=("family",))
    assert [item.label for item in permissive.findings] == ["budget"]


def test_fork_isolation_drops_failures_and_keeps_constraints() -> None:
    history = [
        ForkMessage("system", "你是小红书运营助手"),
        ForkMessage(
            "failed_attempt",
            "Traceback (most recent call last):\n避免使用排比总结句",
        ),
        ForkMessage("assistant", "初稿正文"),
        ForkMessage("rejected_draft", "被驳回的草稿\n不要堆砌感叹号"),
        ForkMessage("user", "Error: 上游超时"),
    ]
    context = isolate_fork_context(history)
    assert [item.role for item in context.messages] == ["system", "assistant"]
    assert context.negative_constraints == ("避免使用排比总结句", "不要堆砌感叹号")
    assert context.removed_messages == 3
    assert context.removed_chars == sum(
        len(item.content) for item in history if item.role != "system" and item.role != "assistant"
    )
    limited = isolate_fork_context(history, max_negative_constraints=1)
    assert limited.negative_constraints == ("避免使用排比总结句",)


def test_epic_index_budget_and_query() -> None:
    index = EpicPreferenceIndex(byte_budget=64)
    assert index.add(PreferenceEntry("p1", "标题不超过20字")) is True
    assert index.add(PreferenceEntry("p2", "正文避免排比句")) is True
    assert (
        index.add(
            PreferenceEntry(
                "p3", "这是一条非常长的偏好指令用来测试字节预算上限是否会正确拒绝写入" * 2
            )
        )
        is False
    )
    assert index.add(PreferenceEntry("p4", "未对齐的日志原文", aligned=False)) is False
    stats = index.stats()
    assert stats.entries == 2
    assert stats.bytes_estimate == len(("标题不超过20字" + "正文避免排比句").encode("utf-8"))
    assert stats.latency_ms == pytest.approx(5.31)
    assert stats.under_budget is True
    assert [entry.entry_id for entry in index.query("标题")] == ["p1"]
    assert [entry.entry_id for entry in index.query("排比")] == ["p2"]
    assert index.query("") == ()
    assert index.remove("p1") is True
    assert index.remove("p1") is False


def test_visual_trajectory_without_anchors_matches_text() -> None:
    text = TrajectoryMetrics(0.7, 0.7, 0.7, 0.7)
    score = evaluate_visual_trajectory(text)
    assert score.adjusted_score == 0.7
    assert score.visual_bonus == 0.0
    assert score.reason == "no_visual_anchors"
    assert score.text_only_tie is False


def test_visual_trajectory_rewards_visual_anchor() -> None:
    text = TrajectoryMetrics(0.7, 0.7, 0.7, 0.7)
    visual = TrajectoryMetrics(0.9, 0.85, 0.8, 0.85)
    score = evaluate_visual_trajectory(text, visual, has_visual_anchors=True)
    assert score.text_score == 0.7
    assert score.visual_score == 0.85
    assert score.adjusted_score == pytest.approx(0.7375)
    assert score.visual_bonus == pytest.approx(0.0375)
    assert score.reason == "visual_anchored"
    equivalent = evaluate_visual_trajectory(text, text, has_visual_anchors=True)
    assert equivalent.reason == "visual_equivalent"
    assert equivalent.text_only_tie is True
    with pytest.raises(ValueError):
        evaluate_visual_trajectory(text, visual, has_visual_anchors=True, visual_weight=1.5)
