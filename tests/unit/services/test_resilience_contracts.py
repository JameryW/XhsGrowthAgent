from __future__ import annotations

import pytest

from backend.services.resilience_contracts import (
    BeliefEntropySummaryGate,
    BeliefProbe,
    ChaosConfig,
    ControlFunctionCausalEstimator,
    MetamorphicCase,
    ToolEvent,
    WorkspaceState,
    build_bounded_context,
    evaluate_stress_window,
    pass_power_k,
    plan_tool_recovery,
    probe_entropy,
    run_metamorphic_chaos,
)


def test_control_function_recovers_effect() -> None:
    instruments = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]
    confounders = [1.0, -1.0, 0.0, 2.0, -2.0, 1.0]
    treatments = [
        2.0 * value + error for value, error in zip(instruments, confounders, strict=True)
    ]
    outcomes = [
        3.0 * value + 2.0 * error for value, error in zip(treatments, confounders, strict=True)
    ]
    estimate = ControlFunctionCausalEstimator.fit(treatments, outcomes, instruments)
    assert estimate.effect == pytest.approx(3.0, abs=0.1)
    assert estimate.observations == 6
    assert 0.0 <= estimate.instrument_strength <= 1.0


def test_control_function_rejects_bad_inputs() -> None:
    with pytest.raises(ValueError):
        ControlFunctionCausalEstimator.fit([1.0], [1.0], [1.0])
    with pytest.raises(ValueError):
        ControlFunctionCausalEstimator.fit([1.0, 2.0], [1.0], [1.0, 2.0])
    with pytest.raises(ValueError):
        ControlFunctionCausalEstimator.fit([1.0, 2.0, 3.0], [1.0, 2.0, 3.0], [1.0, 1.0, 1.0])


def test_probe_entropy_uniform_and_confident() -> None:
    uniform = BeliefProbe("q", {"a": 0.0, "b": 0.0, "c": 0.0, "d": 0.0})
    confident = BeliefProbe("q", {"a": 0.0, "b": -100.0})
    assert probe_entropy(uniform) == pytest.approx(1.0)
    assert probe_entropy(confident) < 0.01


def test_summary_gate_rejects_high_entropy_and_empty() -> None:
    gate = BeliefEntropySummaryGate(threshold=0.7)
    result = gate.evaluate([BeliefProbe("硬约束槽位", {"a": 0.0, "b": 0.0, "c": 0.0})])
    assert result.accepted is False
    assert result.need_resummarize is True
    assert any(reason.startswith("high_entropy:") for reason in result.reasons)
    empty = gate.evaluate([])
    assert empty.accepted is False
    assert empty.reasons == ("no_probes",)


def test_summary_gate_accepts_low_entropy() -> None:
    gate = BeliefEntropySummaryGate(threshold=0.7)
    result = gate.evaluate(
        [
            BeliefProbe("硬约束槽位", {"7座四驱": 0.0, "其他": -10.0}),
            BeliefProbe("账号禁区", {"禁止导流": 0.0, "其他": -10.0}),
        ]
    )
    assert result.accepted is True
    assert result.need_resummarize is False


def test_stress_window_degrades_above_threshold() -> None:
    events = [
        ToolEvent(at=float(index), ok=index >= 3, rate_limited=index < 3) for index in range(10)
    ]
    decision = evaluate_stress_window(events, now=9.0)
    assert decision.lambda_hat == 0.3
    assert decision.degraded is True
    assert decision.disable_reflexion is True
    assert decision.mode == "linear_react"
    assert decision.retry_policy == "exponential_backoff_jitter"


def test_stress_window_normal_and_empty() -> None:
    events = [ToolEvent(at=1.0, ok=True), ToolEvent(at=2.0, ok=True)]
    normal = evaluate_stress_window(events, now=2.0)
    assert normal.degraded is False
    assert normal.mode == "reflexion"
    empty = evaluate_stress_window([], now=10.0)
    assert empty.reasons == ("no_events",)


def test_plan_tool_recovery_replans_and_retries() -> None:
    replan = plan_tool_recovery("ripple_predict", "timeout")
    assert replan.action == "replan"
    assert replan.fallbacks == ("local_oransim_lightgbm", "provider_insights_salvage")
    retry = plan_tool_recovery("xhs_trending", "rate_limit", retryable=True)
    assert retry.action == "retry"
    unknown = plan_tool_recovery("unknown_tool")
    assert unknown.action == "manual_review"


def test_workspace_snapshot_markdown_roundtrip() -> None:
    state = WorkspaceState(
        active_draft_id="draft-1",
        constraints=("标题不超过20字", "禁止站外导流"),
        todos=("补充图2路线表",),
        competitor_summary="竞品多用三段式清单",
    )
    restored = WorkspaceState.from_markdown(state.to_markdown())
    assert restored.active_draft_id == "draft-1"
    assert restored.constraints == state.constraints
    assert restored.todos == state.todos
    assert restored.competitor_summary == state.competitor_summary


def test_bounded_context_limits_turns() -> None:
    state = WorkspaceState(active_draft_id="draft-1")
    messages = [{"role": "user", "content": f"消息 {index}"} for index in range(10)]
    payload = build_bounded_context(state, messages, max_turns=3, max_chars=4000)
    assert len(payload["messages"]) == 3
    assert payload["messages"][-1]["content"] == "消息 9"
    assert "draft-1" in payload["state"]


def test_chaos_zero_lambda_passes_and_full_lambda_fails() -> None:
    cases = [
        MetamorphicCase("publish", "发帖", {"status": "ok"}),
        MetamorphicCase("dm", "私信", {"status": "ok"}),
    ]
    clean = run_metamorphic_chaos(cases, config=ChaosConfig(lambda_=0.0))
    assert clean.passed is True
    assert clean.pass_power_k == 1.0
    broken = run_metamorphic_chaos(cases, config=ChaosConfig(lambda_=1.0))
    assert broken.passed is False
    assert pass_power_k(broken) == 0.0


def test_chaos_executor_can_recover_faults() -> None:
    cases = [MetamorphicCase("publish", "发帖", {"status": "ok"})]

    def executor(case: MetamorphicCase, fault: str) -> dict[str, str]:
        return dict(case.expected_terminal)

    report = run_metamorphic_chaos(cases, config=ChaosConfig(lambda_=0.5), executor=executor)
    assert report.passed is True
    assert report.case_pass["publish"] is True


def test_chaos_requires_cases() -> None:
    with pytest.raises(ValueError):
        run_metamorphic_chaos([])
