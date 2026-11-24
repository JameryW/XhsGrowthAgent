from __future__ import annotations

import pytest

from backend.services.alignment_contracts import (
    AffToMThreadState,
    ComplianceRule,
    CulturalHint,
    DualProfile,
    GainCtrlEarlyStopper,
    HarnessModule,
    HarnessPatch,
    ProfileChannels,
    RequirementIssue,
    ThreadParticipant,
    accept_profile_update,
    apply_compaction_anchor,
    build_afftom_thread_state,
    channel_homophily,
    compose_afftom_reply,
    cultural_judge_score,
    evaluate_harness_patch,
    plan_compaction_anchor,
    quality_framing_score,
    retrieve_cultural_hints,
)


def test_compaction_keeps_all_rules_out_of_history() -> None:
    rules = [
        ComplianceRule("r1", "禁止站外导流"),
        ComplianceRule("r2", "商单必须报备", severity="critical"),
    ]
    plan = plan_compaction_anchor(rules, max_reanchor_chars=160)
    assert plan.static_prefix == tuple(rules)
    assert plan.policies_in_compaction == ()
    assert plan.reanchor.startswith("<active_rules_reanchor>")
    assert plan.reanchor.endswith("</active_rules_reanchor>")
    assert "禁止站外导流" in plan.reanchor


def test_compaction_anchor_truncates_and_does_not_mutate() -> None:
    plan = plan_compaction_anchor(
        [ComplianceRule("r1", "这是一条非常长的合规规则需要被截断")],
        max_reanchor_chars=60,
    )
    assert len(plan.reanchor) <= 60
    assert plan.reanchor.endswith("</active_rules_reanchor>")
    messages = [{"role": "user", "content": "压缩后的历史"}]
    anchored = apply_compaction_anchor(messages, plan)
    assert messages == [{"role": "user", "content": "压缩后的历史"}]
    assert anchored[-1] == {"role": "system", "content": plan.reanchor}


def test_compaction_requires_valid_limits_and_rules() -> None:
    with pytest.raises(ValueError):
        plan_compaction_anchor([], max_reanchor_chars=0)
    with pytest.raises(ValueError):
        plan_compaction_anchor([ComplianceRule("", "text")])


def test_harness_patch_accepts_zero_token_gain() -> None:
    issue = RequirementIssue("issue-1", "首轮驳回缺少证据", HarnessModule.TOOL_INTERFACE)
    patch = HarnessPatch(
        "patch-1",
        HarnessModule.TOOL_INTERFACE,
        token_delta=0,
        resolves_issue_ids=("issue-1",),
    )
    decision = evaluate_harness_patch(issue, patch)
    assert decision.accepted is True
    assert decision.reasons == ("accepted",)


def test_harness_patch_rejects_regressions_and_bloat() -> None:
    issue = RequirementIssue("issue-1", "规则缺失", HarnessModule.CONTROL)
    mismatch = HarnessPatch("p1", HarnessModule.CONTROL, token_delta=0)
    assert evaluate_harness_patch(issue, mismatch).reasons == ("issue_not_resolved",)
    unsafe = HarnessPatch(
        "p2",
        HarnessModule.CONTROL,
        token_delta=0,
        resolves_issue_ids=("issue-1",),
        fallback_safe=False,
    )
    assert "fallback_unsafe" in evaluate_harness_patch(issue, unsafe).reasons
    bloat = HarnessPatch(
        "p3",
        HarnessModule.CONTROL,
        token_delta=20,
        resolves_issue_ids=("issue-1",),
    )
    assert evaluate_harness_patch(issue, bloat).accepted is False
    assert "token_increase" in evaluate_harness_patch(issue, bloat).reasons


def test_gain_ctrl_continues_on_positive_gain() -> None:
    stopper = GainCtrlEarlyStopper()
    for score in (0.5, 0.6, 0.7):
        stopper.observe(score)
    decision = stopper.decide()
    assert decision.should_stop is False
    assert decision.expected_positive_gain == pytest.approx(0.1)
    assert decision.reason == "continue"


def test_gain_ctrl_stops_on_stagnation_and_marginal_gain() -> None:
    stagnant = GainCtrlEarlyStopper()
    for score in (0.7, 0.7, 0.7):
        stagnant.observe(score)
    assert stagnant.decide().reason == "stagnation"
    marginal = GainCtrlEarlyStopper()
    for score in (0.5, 0.501, 0.5011):
        marginal.observe(score)
    decision = marginal.decide()
    assert decision.should_stop is True
    assert decision.reason == "marginal_gain"
    assert decision.expected_positive_gain < decision.threshold


def test_gain_ctrl_needs_history() -> None:
    stopper = GainCtrlEarlyStopper()
    stopper.observe(0.5)
    decision = stopper.decide()
    assert decision.should_stop is False
    assert decision.reason == "insufficient_history"


def test_channel_homophily_uses_four_channels() -> None:
    profile = ProfileChannels(preference=frozenset({"a", "b"}))
    score = channel_homophily(profile, {"preference": ("a", "c")})
    assert score == pytest.approx(0.0833)
    assert channel_homophily(ProfileChannels(), {}) == 0.0


def test_profile_update_requires_a_channel_gain() -> None:
    current = ProfileChannels()
    proposed = ProfileChannels(preference=frozenset({"a"}))
    accepted = accept_profile_update(current, proposed, {"preference": ("a",)})
    assert accepted.accepted is True
    assert accepted.improved_channels == ("preference",)
    rejected = accept_profile_update(current, proposed, {"preference": ("b",)})
    assert rejected.accepted is False
    assert rejected.reasons == ("no_channel_gain",)
    assert DualProfile("acc", proposed).as_dict()["channels"]["preference"] == ["a"]


def test_afftom_thread_state_builds_three_perspectives() -> None:
    state = build_afftom_thread_state(
        [
            ThreadParticipant("asker", "想确认川西租车价格"),
            ThreadParticipant("challenger", "去年被别家坑过押金"),
            ThreadParticipant("lurker", "担心隐形消费"),
            ThreadParticipant("lurker", "担心车况"),
        ]
    )
    assert state.asker_concern == "想确认川西租车价格"
    assert state.challenger_trigger == "去年被别家坑过押金"
    assert state.lurker_threshold == "担心隐形消费；担心车况"
    assert build_afftom_thread_state([]).as_dict()["asker_concern"] == "未明确"


def test_afftom_reply_orders_empathy_standard_hook() -> None:
    state = AffToMThreadState("问价", "押金被坑", "担心隐形消费")
    reply = compose_afftom_reply(
        state,
        hard_standard="全险免赔写入合同",
        hook="戳主页看档期表",
    )
    assert reply.index("理解") < reply.index("硬标准") < reply.index("戳主页")
    short = compose_afftom_reply(state, hard_standard="全险", hook="戳主页", max_chars=20)
    assert len(short) <= 20
    assert short.endswith("…")


def test_cultural_hints_are_retrieved_and_scored() -> None:
    hints = [
        CulturalHint("川西防滑链实测与高反备氧", source="trend", score=0.8),
        CulturalHint("城市通勤穿搭", source="other", score=0.9),
    ]
    retrieved = retrieve_cultural_hints("川西 防滑链", hints)
    assert [hint.text for hint in retrieved] == ["川西防滑链实测与高反备氧"]
    result = cultural_judge_score(70.0, retrieved)
    assert result.adjusted_score == pytest.approx(71.5)
    assert result.reasons[0] == "cultural_hints:1"


def test_quality_framing_rewards_quality_and_penalizes_price_hooks() -> None:
    quality = quality_framing_score("车龄1.5年 防滑链 氧气瓶 实测路线")
    assert quality == pytest.approx(82.0)
    price = quality_framing_score("全网最低 99元起 绝对便宜")
    assert price == pytest.approx(14.0)
    assert quality > price
