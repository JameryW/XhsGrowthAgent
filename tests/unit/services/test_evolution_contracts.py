from __future__ import annotations

import pytest

from backend.services.evolution_contracts import (
    CONCEPT_DIMENSIONS,
    BottleneckBranch,
    DecisionNode,
    EvalCase,
    MetaWorkflowEvolver,
    PrerequisiteDAGExperimenter,
    QueryFormerPcvrBridge,
    SharedConceptBottleneck,
    TinyEvalCascade,
    TrajectoryStep,
    assign_horizon_credit,
)


def test_meta_workflow_diagnoses_artifact() -> None:
    diagnosis = MetaWorkflowEvolver().diagnose(artifact_issue=True)
    assert diagnosis.branch is BottleneckBranch.ARTIFACT
    assert diagnosis.score == 1.0
    assert "artifact_issue" in diagnosis.reasons


def test_meta_workflow_diagnoses_harness_and_model() -> None:
    evolver = MetaWorkflowEvolver()
    harness = evolver.diagnose(harness_gap_count=2, min_harness_gap=2)
    assert harness.branch is BottleneckBranch.HARNESS
    model = evolver.diagnose(model_retry_rate=0.5, retry_threshold=0.25)
    assert model.branch is BottleneckBranch.MODEL_ROUTING
    assert any(reason.startswith("retry_rate") for reason in model.reasons)


def test_meta_principles_record_and_filter() -> None:
    evolver = MetaWorkflowEvolver()
    principle = evolver.record(
        scene="travel",
        change="改写标题模板",
        metric="collect_rate",
        delta=0.12,
        won=True,
    )
    assert "胜出" in principle.statement
    assert evolver.principles_for("travel") == (principle,)
    assert evolver.principles_for("food") == ()
    assert evolver.as_dict()["principles"][0]["delta"] == 0.12


def test_prerequisite_group_expands_closure() -> None:
    experimenter = PrerequisiteDAGExperimenter(
        (
            DecisionNode("z1", supplies_properties=("routebook",)),
            DecisionNode("z2", requires_decisions=("z1",)),
            DecisionNode("z3", requires_decisions=("z2",)),
        )
    )
    group = experimenter.group(("z2",))
    assert group.allowed is True
    assert group.decision_ids == ("z1", "z2")
    assert group.violations == ()


def test_prerequisite_group_rejects_unknown_and_cycle() -> None:
    missing = PrerequisiteDAGExperimenter((DecisionNode("a", requires_decisions=("ghost",)),))
    group = missing.group(("a",))
    assert group.allowed is False
    assert "unknown_dependency:a->ghost" in group.violations
    cyclic = PrerequisiteDAGExperimenter(
        (
            DecisionNode("a", requires_decisions=("b",)),
            DecisionNode("b", requires_decisions=("a",)),
        )
    )
    assert any(item.startswith("cycle:") for item in cyclic.validate())
    assert cyclic.group(("a",)).allowed is False


def test_experiment_outcome_hash_is_stable() -> None:
    experimenter = PrerequisiteDAGExperimenter(
        (DecisionNode("a", supplies_properties=("p",)), DecisionNode("b"))
    )
    first = experimenter.record_result("a", expected_metric="collect", observed_delta=0.2)
    second = experimenter.record_result("a", expected_metric="collect", observed_delta=0.2)
    assert first.prerequisite_subgraph_hash == second.prerequisite_subgraph_hash
    assert first.as_dict()["observed_delta"] == 0.2


def test_horizon_credit_full_when_all_steps_good() -> None:
    steps = [
        TrajectoryStep(1, "strategy", q_value=0.9, best_of_n_q=0.9),
        TrajectoryStep(2, "copy", q_value=0.8, best_of_n_q=0.8),
    ]
    assignment = assign_horizon_credit(steps, terminal_return=2.0)
    assert assignment.truncated_at is None
    assert assignment.reason == "full_horizon"
    assert assignment.credits["strategy"] < assignment.credits["copy"]


def test_horizon_credit_truncates_at_suboptimal_downstream() -> None:
    steps = [
        TrajectoryStep(1, "strategy", q_value=0.9, best_of_n_q=0.9),
        TrajectoryStep(2, "publish", q_value=0.2, best_of_n_q=0.8),
        TrajectoryStep(3, "dm", q_value=0.1, best_of_n_q=0.6),
    ]
    assignment = assign_horizon_credit(steps, terminal_return=0.5)
    assert assignment.truncated_at == 2
    assert assignment.reason == "counterfactual_truncation"
    assert assignment.credits["strategy"] == 0.8


def test_horizon_credit_empty() -> None:
    assignment = assign_horizon_credit([], terminal_return=1.0)
    assert assignment.credits == {}
    assert assignment.reason == "empty"


def test_queryformer_prediction_is_bounded_and_normalized() -> None:
    prediction = QueryFormerPcvrBridge(views=4).predict(
        {"hook": 1.0, "dm_intent": 0.8},
        ({"hook": 1.0}, {"hook": 0.2}),
    )
    assert 0.0 <= prediction.p_collect <= 1.0
    assert 0.0 <= prediction.p_lead <= 1.0
    assert len(prediction.view_scores) == 4
    assert len(prediction.attention) == 8
    assert prediction.attention[0] + prediction.attention[1] == pytest.approx(1.0, abs=1e-3)


def test_queryformer_sequence_changes_prediction() -> None:
    bridge = QueryFormerPcvrBridge()
    low = bridge.predict({"hook": 1.0}, ({"hook": 0.0},))
    high = bridge.predict({"hook": 1.0}, ({"hook": 1.0},))
    assert high.p_collect > low.p_collect


def test_tiny_eval_cascade_stage1_reject() -> None:
    cascade = TinyEvalCascade(
        [EvalCase("a", "policy", stage1_violations=1), EvalCase("b", "quality")]
    )
    result = cascade.run()
    assert result.passed is False
    assert result.stage == 1
    assert result.estimated_calls_saved == 1.0


def test_tiny_eval_cascade_stage2_and_full_suite() -> None:
    cases = [
        EvalCase(f"c{index}", "quality", stage2_score=0.8, full_score=0.8, discrimination=index)
        for index in range(10)
    ]
    cascade = TinyEvalCascade(
        cases,
        anchor_count=5,
        baseline_stage2=0.5,
        baseline_full=0.5,
    )
    failed = cascade.run({case.case_id: 0.1 for case in cases})
    assert failed.stage == 2
    assert failed.estimated_calls_saved == 0.5
    passed = cascade.run({case.case_id: 0.9 for case in cases})
    assert passed.passed is True
    assert passed.stage == 3


def test_shared_concept_bottleneck_decomposition() -> None:
    bottleneck = SharedConceptBottleneck()
    result = bottleneck.decompose(
        "mimo-v2.6-flash",
        {CONCEPT_DIMENSIONS[0]: 1.0, "unknown": 9.0},
        {CONCEPT_DIMENSIONS[0]: 0.0},
    )
    assert len(result.shared) == 16
    assert result.shared[CONCEPT_DIMENSIONS[0]] == 0.5
    assert result.private_residual[CONCEPT_DIMENSIONS[0]] == 0.5
    assert all(0.0 <= value <= 1.0 for value in result.aligned.values())


def test_shared_concept_requires_dimensions() -> None:
    with pytest.raises(ValueError):
        SharedConceptBottleneck(())
