"""Phase-13 evolution contracts (ledger schemes 73-78).

Deterministic, standard-library-only helpers for the Creator Agent evolution
loop.  Nothing here is wired into the default workflow: callers pass plain
models and receive plain reports.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

__all__ = [
    "BottleneckBranch",
    "BottleneckDiagnosis",
    "CascadeResult",
    "CONCEPT_DIMENSIONS",
    "ConceptDecomposition",
    "CreditAssignment",
    "DecisionNode",
    "EvalCase",
    "ExperimentGroup",
    "ExperimentOutcome",
    "MetaPrinciple",
    "MetaWorkflowEvolver",
    "PcvrPrediction",
    "PrerequisiteDAGExperimenter",
    "QueryFormerPcvrBridge",
    "SharedConceptBottleneck",
    "TinyEvalCascade",
    "TrajectoryStep",
    "assign_horizon_credit",
]


def _round(value: float) -> float:
    return round(float(value), 4)


def _unit(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _mean(values: Iterable[float]) -> float:
    items = [float(item) for item in values]
    if not items:
        return 0.0
    return sum(items) / len(items)


def _sigmoid(value: float) -> float:
    if value >= 0:
        exp = math.exp(-value)
        return 1.0 / (1.0 + exp)
    exp = math.exp(value)
    return exp / (1.0 + exp)


def _tokens(text: str) -> set[str]:
    return {token for token in re.split(r"[\s,，。;；:：/|]+", text) if token}


class BottleneckBranch(StrEnum):
    """Three improvement workflows from RSIFlow."""

    ARTIFACT = "artifact"
    HARNESS = "harness"
    MODEL_ROUTING = "model_routing"


@dataclass(frozen=True)
class BottleneckDiagnosis:
    branch: BottleneckBranch
    score: float
    reasons: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "branch": self.branch.value,
            "score": _round(self.score),
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class MetaPrinciple:
    scene: str
    change: str
    metric: str
    delta: float
    won: bool

    @property
    def statement(self) -> str:
        direction = "提升" if self.delta >= 0 else "下降"
        outcome = "胜出" if self.won else "败北"
        return (
            f"在 {self.scene} 场景，{self.change} 使 {self.metric} "
            f"{direction} {abs(_round(self.delta))}，该轮{outcome}"
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "scene": self.scene,
            "change": self.change,
            "metric": self.metric,
            "delta": _round(self.delta),
            "won": self.won,
            "statement": self.statement,
        }


class MetaWorkflowEvolver:
    """Route weak performance to artifact, harness or model/routing work."""

    def __init__(self) -> None:
        self._principles: list[MetaPrinciple] = []

    def diagnose(
        self,
        *,
        artifact_issue: bool = False,
        harness_gap_count: int = 0,
        model_retry_rate: float = 0.0,
        model_format_failures: int = 0,
        min_harness_gap: int = 2,
        retry_threshold: float = 0.25,
    ) -> BottleneckDiagnosis:
        artifact_score = 1.0 if artifact_issue else 0.0
        harness_score = 0.0
        if min_harness_gap > 0:
            harness_score = _unit(float(harness_gap_count) / float(min_harness_gap))
        retry_score = 0.0
        if retry_threshold > 0:
            retry_score = _unit(float(model_retry_rate) / float(retry_threshold))
        format_score = _unit(float(model_format_failures) / 3.0)
        model_score = max(retry_score, format_score)

        scores = {
            BottleneckBranch.ARTIFACT: artifact_score,
            BottleneckBranch.HARNESS: harness_score,
            BottleneckBranch.MODEL_ROUTING: model_score,
        }
        branch = max(scores, key=lambda item: scores[item])
        reasons: list[str] = []
        if artifact_score:
            reasons.append("artifact_issue")
        if harness_gap_count >= max(1, min_harness_gap):
            reasons.append(f"harness_gap:{harness_gap_count}")
        if retry_score:
            reasons.append(f"retry_rate:{_round(model_retry_rate)}")
        if format_score:
            reasons.append(f"format_failures:{model_format_failures}")
        if not reasons:
            reasons.append("no_dominant_signal")
        return BottleneckDiagnosis(branch=branch, score=scores[branch], reasons=tuple(reasons))

    def record(
        self,
        *,
        scene: str,
        change: str,
        metric: str,
        delta: float,
        won: bool,
    ) -> MetaPrinciple:
        principle = MetaPrinciple(
            scene=scene, change=change, metric=metric, delta=_round(delta), won=won
        )
        self._principles.append(principle)
        return principle

    @property
    def principles(self) -> tuple[MetaPrinciple, ...]:
        return tuple(self._principles)

    def principles_for(self, scene: str) -> tuple[MetaPrinciple, ...]:
        return tuple(item for item in self._principles if item.scene == scene)

    def as_dict(self) -> dict[str, Any]:
        return {"principles": [item.as_dict() for item in self._principles]}


@dataclass(frozen=True)
class DecisionNode:
    decision_id: str
    requires_decisions: tuple[str, ...] = ()
    supplies_properties: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExperimentGroup:
    decision_ids: tuple[str, ...]
    allowed: bool
    violations: tuple[str, ...]
    missing_properties: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision_ids": list(self.decision_ids),
            "allowed": self.allowed,
            "violations": list(self.violations),
            "missing_properties": list(self.missing_properties),
        }


@dataclass(frozen=True)
class ExperimentOutcome:
    decision_id: str
    prerequisite_subgraph_hash: str
    expected_metric: str
    observed_delta: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "prerequisite_subgraph_hash": self.prerequisite_subgraph_hash,
            "expected_metric": self.expected_metric,
            "observed_delta": _round(self.observed_delta),
        }


class PrerequisiteDAGExperimenter:
    """Keep prerequisite decisions attached to every experiment group."""

    def __init__(self, nodes: Iterable[DecisionNode]) -> None:
        self._nodes: dict[str, DecisionNode] = {}
        for node in nodes:
            if not node.decision_id:
                raise ValueError("decision_id must not be empty")
            self._nodes[node.decision_id] = node

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        for node in self._nodes.values():
            for dependency in node.requires_decisions:
                if dependency not in self._nodes:
                    errors.append(f"unknown_dependency:{node.decision_id}->{dependency}")
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node_id: str) -> None:
            if node_id in visiting:
                errors.append(f"cycle:{node_id}")
                return
            if node_id in visited:
                return
            visiting.add(node_id)
            for dependency in self._nodes[node_id].requires_decisions:
                if dependency in self._nodes:
                    visit(dependency)
            visiting.discard(node_id)
            visited.add(node_id)

        for node_id in self._nodes:
            visit(node_id)
        return tuple(dict.fromkeys(errors))

    def _closure(self, decision_ids: Iterable[str]) -> tuple[str, ...]:
        ordered: list[str] = []
        seen: set[str] = set()
        visiting: set[str] = set()

        def add(node_id: str) -> None:
            if node_id in seen or node_id in visiting or node_id not in self._nodes:
                return
            visiting.add(node_id)
            for dependency in self._nodes[node_id].requires_decisions:
                add(dependency)
            visiting.discard(node_id)
            seen.add(node_id)
            ordered.append(node_id)

        for decision_id in decision_ids:
            add(decision_id)
        return tuple(ordered)

    def group(self, decision_ids: Iterable[str]) -> ExperimentGroup:
        requested = tuple(dict.fromkeys(str(item) for item in decision_ids if str(item)))
        violations = [f"unknown_decision:{item}" for item in requested if item not in self._nodes]
        if self.validate():
            violations.extend(self.validate())
        expanded = self._closure(requested)
        supplied: set[str] = set()
        for node_id in expanded:
            supplied.update(self._nodes[node_id].supplies_properties)
        missing: list[str] = []
        for node_id in expanded:
            for property_name in self._nodes[node_id].supplies_properties:
                if property_name not in supplied:
                    missing.append(f"{node_id}:{property_name}")
        return ExperimentGroup(
            decision_ids=expanded,
            allowed=not violations,
            violations=tuple(dict.fromkeys(violations)),
            missing_properties=tuple(dict.fromkeys(missing)),
        )

    def record_result(
        self,
        decision_id: str,
        *,
        expected_metric: str,
        observed_delta: float,
        group: ExperimentGroup | None = None,
    ) -> ExperimentOutcome:
        if decision_id not in self._nodes:
            raise ValueError(f"unknown decision: {decision_id}")
        selected = group.decision_ids if group is not None else self._closure((decision_id,))
        digest = hashlib.sha256("|".join(sorted(selected)).encode("utf-8")).hexdigest()[:12]
        return ExperimentOutcome(
            decision_id=decision_id,
            prerequisite_subgraph_hash=digest,
            expected_metric=expected_metric,
            observed_delta=_round(observed_delta),
        )


@dataclass(frozen=True)
class TrajectoryStep:
    step: int
    node: str
    q_value: float
    best_of_n_q: float


@dataclass(frozen=True)
class CreditAssignment:
    credits: Mapping[str, float]
    truncated_at: int | None
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "credits": {key: _round(value) for key, value in self.credits.items()},
            "truncated_at": self.truncated_at,
            "reason": self.reason,
        }


def assign_horizon_credit(
    steps: Sequence[TrajectoryStep],
    terminal_return: float,
    *,
    discount: float = 0.9,
    tolerance: float = 0.05,
) -> CreditAssignment:
    """Truncate multi-step credit at the first clearly suboptimal downstream step."""

    ordered = sorted(steps, key=lambda item: item.step)
    if not ordered:
        return CreditAssignment(credits={}, truncated_at=None, reason="empty")
    if not 0.0 < discount <= 1.0:
        raise ValueError("discount must be in (0, 1]")

    truncated_index: int | None = None
    for index, item in enumerate(ordered):
        threshold = float(item.best_of_n_q) * (1.0 - max(0.0, tolerance))
        if float(item.q_value) < threshold:
            truncated_index = index
            break

    total = len(ordered)
    credits: dict[str, float] = {}
    if truncated_index is None:
        for index, item in enumerate(ordered):
            credits[item.node] = _round(float(terminal_return) * discount ** (total - 1 - index))
        return CreditAssignment(credits=credits, truncated_at=None, reason="full_horizon")

    counterfactual = max(
        float(terminal_return),
        float(ordered[truncated_index].best_of_n_q),
    )
    for index, item in enumerate(ordered):
        if index < truncated_index:
            credits[item.node] = _round(counterfactual)
        else:
            credits[item.node] = _round(float(terminal_return) * discount ** (total - 1 - index))
    return CreditAssignment(
        credits=credits,
        truncated_at=ordered[truncated_index].step,
        reason="counterfactual_truncation",
    )


@dataclass(frozen=True)
class PcvrPrediction:
    p_collect: float
    p_lead: float
    attention: tuple[float, ...]
    view_scores: tuple[float, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "p_collect": _round(self.p_collect),
            "p_lead": _round(self.p_lead),
            "attention": [_round(item) for item in self.attention],
            "view_scores": [_round(item) for item in self.view_scores],
        }


class QueryFormerPcvrBridge:
    """A tiny deterministic stand-in for QueryFormer's cross-attention pCVR head."""

    def __init__(self, *, views: int = 4) -> None:
        if views < 1:
            raise ValueError("views must be >= 1")
        self._views = views

    def predict(
        self,
        static_features: Mapping[str, float],
        self_sequence: Sequence[Mapping[str, float]],
        niche_sequence: Sequence[Mapping[str, float]] = (),
    ) -> PcvrPrediction:
        keys = sorted(static_features)
        static = [float(static_features[key]) for key in keys]
        sequences = [self_sequence, niche_sequence]
        attention_values: list[float] = []
        view_scores: list[float] = []
        weighted_total = 0.0

        for view in range(1, self._views + 1):
            scores: list[float] = []
            for domain, sequence in enumerate(sequences):
                for position, item in enumerate(sequence):
                    dot = 0.0
                    for index, key in enumerate(keys):
                        weight = 0.5 + 0.5 * (((index + 1) * view) % 7) / 6.0
                        dot += static[index] * float(item.get(key, 0.0)) * weight
                    position_decay = 1.0 / (1.0 + 0.15 * position)
                    domain_weight = 1.0 if domain == 0 else 0.6
                    scores.append(dot * position_decay * domain_weight)
            if not scores:
                view_scores.append(0.0)
                continue
            maximum = max(scores)
            exps = [math.exp(score - maximum) for score in scores]
            normalizer = sum(exps) or 1.0
            attention = [value / normalizer for value in exps]
            weighted = sum(score * weight for score, weight in zip(scores, attention, strict=True))
            weighted_total += weighted
            view_scores.append(_round(weighted))
            attention_values.extend(attention)

        mean_score = weighted_total / self._views
        dm_signal = float(static_features.get("dm_intent", 0.0))
        p_collect = _sigmoid(2.2 * mean_score + 0.4 * dm_signal - 0.8)
        p_lead = _sigmoid(2.6 * mean_score + 1.4 * dm_signal - 1.2)
        return PcvrPrediction(
            p_collect=_unit(p_collect),
            p_lead=_unit(p_lead),
            attention=tuple(_round(item) for item in attention_values),
            view_scores=tuple(view_scores),
        )


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    category: str
    stage1_violations: int = 0
    stage2_score: float = 0.0
    full_score: float = 0.0
    discrimination: float = 0.0


@dataclass(frozen=True)
class CascadeResult:
    passed: bool
    stage: int
    reason: str
    stage1_violations: int
    stage2_score: float
    estimated_calls_saved: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "stage": self.stage,
            "reason": self.reason,
            "stage1_violations": self.stage1_violations,
            "stage2_score": _round(self.stage2_score),
            "estimated_calls_saved": _round(self.estimated_calls_saved),
        }


class TinyEvalCascade:
    """Three-stage evaluation: deterministic, five anchors, then the full suite."""

    def __init__(
        self,
        cases: Iterable[EvalCase],
        *,
        anchor_count: int = 5,
        baseline_stage2: float = 0.0,
        baseline_full: float = 0.0,
    ) -> None:
        self._cases = tuple(cases)
        if not self._cases:
            raise ValueError("cases must not be empty")
        if anchor_count < 1:
            raise ValueError("anchor_count must be >= 1")
        self._anchor_count = min(anchor_count, len(self._cases))
        self._baseline_stage2 = float(baseline_stage2)
        self._baseline_full = float(baseline_full)

    def anchors(self) -> tuple[EvalCase, ...]:
        ranked = sorted(
            self._cases,
            key=lambda item: (-float(item.discrimination), -float(item.stage2_score)),
        )
        return tuple(ranked[: self._anchor_count])

    def run(self, candidate_scores: Mapping[str, float] | None = None) -> CascadeResult:
        violations = sum(max(0, int(case.stage1_violations)) for case in self._cases)
        if violations:
            return CascadeResult(
                passed=False,
                stage=1,
                reason="policy_violation",
                stage1_violations=violations,
                stage2_score=0.0,
                estimated_calls_saved=1.0,
            )
        scores = candidate_scores or {case.case_id: case.stage2_score for case in self._cases}
        anchors = self.anchors()
        stage2 = _mean(float(scores.get(case.case_id, case.stage2_score)) for case in anchors)
        if stage2 < self._baseline_stage2:
            saved = 1.0 - len(anchors) / len(self._cases)
            return CascadeResult(
                passed=False,
                stage=2,
                reason="anchor_regression",
                stage1_violations=0,
                stage2_score=stage2,
                estimated_calls_saved=max(0.0, saved),
            )
        full = _mean(float(scores.get(case.case_id, case.full_score)) for case in self._cases)
        passed = full >= self._baseline_full
        return CascadeResult(
            passed=passed,
            stage=3 if passed else 0,
            reason="full_suite_pass" if passed else "full_suite_regression",
            stage1_violations=0,
            stage2_score=stage2,
            estimated_calls_saved=0.0,
        )


CONCEPT_DIMENSIONS: tuple[str, ...] = (
    "首段结论直接度",
    "价格参数透明度",
    "多卡递进留存力",
    "地域POI锚定度",
    "人设口癖自然度",
    "证据可核验性",
    "痛点具象度",
    "视觉信息密度",
    "行动号召清晰度",
    "评论区互动钩子",
    "搜索长尾覆盖",
    "情绪起伏度",
    "场景代入感",
    "风险提示完备度",
    "商单披露合规",
    "收藏清单价值",
)


@dataclass(frozen=True)
class ConceptDecomposition:
    model_id: str
    shared: Mapping[str, float]
    private_residual: Mapping[str, float]
    aligned: Mapping[str, float]

    def as_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "shared": {key: _round(value) for key, value in self.shared.items()},
            "private_residual": {
                key: _round(value) for key, value in self.private_residual.items()
            },
            "aligned": {key: _round(value) for key, value in self.aligned.items()},
        }


class SharedConceptBottleneck:
    """Split model scores into a shared concept vector and private residuals."""

    def __init__(self, concept_dimensions: Sequence[str] = CONCEPT_DIMENSIONS) -> None:
        if not concept_dimensions:
            raise ValueError("concept_dimensions must not be empty")
        self._dimensions = tuple(concept_dimensions)

    @property
    def dimensions(self) -> tuple[str, ...]:
        return self._dimensions

    def decompose(
        self,
        model_id: str,
        scores: Mapping[str, float],
        shared_baseline: Mapping[str, float] | None = None,
    ) -> ConceptDecomposition:
        baseline = shared_baseline or {}
        shared: dict[str, float] = {}
        private: dict[str, float] = {}
        aligned: dict[str, float] = {}
        for dimension in self._dimensions:
            score = _unit(float(scores.get(dimension, 0.0)))
            base = _unit(float(baseline.get(dimension, 0.5)))
            shared_value = 0.5 * score + 0.5 * base
            shared[dimension] = _round(shared_value)
            private[dimension] = _round(score - shared_value)
            aligned[dimension] = shared[dimension]
        residuals = list(private.values())
        bias = _mean(residuals)
        if residuals:
            aligned = {key: _round(_unit(value + 0.5 * bias)) for key, value in shared.items()}
        return ConceptDecomposition(
            model_id=model_id,
            shared=shared,
            private_residual=private,
            aligned=aligned,
        )
