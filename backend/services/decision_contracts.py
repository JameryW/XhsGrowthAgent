"""Phase-10 decision contracts (ledger schemes 55-60).

Pure deterministic helpers for the Decision/Action layer.  Nothing in this
module calls an LLM, a browser, the database, or the network; callers pass the
outcome of those systems in as plain mappings and receive an auditable report
that can be written to ``workflow_events``.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

__all__ = [
    "ActionClaim",
    "ChecklistItem",
    "DEFAULT_HANDOFF_FIELDS",
    "DecisionGateReport",
    "PHASE10_ROLLOUT",
    "PolicyCheckResult",
    "PolicyQuestion",
    "PolishDecision",
    "PolishStage",
    "QuestionLogprob",
    "QuestionScore",
    "RolloutWeek",
    "SimCandidate",
    "SensitivityReport",
    "ToolReceipt",
    "TraceReplayDecision",
    "TraceReplayPlan",
    "UITraceStep",
    "UITraceTemplate",
    "UnusableReplyReport",
    "build_rollout_plan",
    "evaluate_handoff_checklist",
    "evaluate_polish_acceptance",
    "evaluate_question_logprobs",
    "evaluate_stage0_skip",
    "extract_action_claims",
    "filter_unusable_reply",
    "jev_decision_gate",
    "perturb_utility",
    "replay_ui_trace",
    "risk_aware_polish_gate",
    "sim_decision_sensitivity_gate",
]


_DEFAULT_REQUIRED_FIELDS = ("account_id", "title", "body")
_HOLLOW_MARKERS = (
    "亲亲",
    "稍等",
    "稍后回复",
    "私信您啦",
    "私信您",
    "马上回复",
    "在的",
    "您好呀",
)
_ACTION_VERBS = (
    "查好",
    "查询",
    "查到",
    "确认",
    "锁定",
    "登记",
    "预约",
    "安排",
    "发送",
    "发过",
    "提交",
    "预定",
    "保留",
)
_COMPLETION_RE = re.compile(r"(?<!自)已|完成|成功|搞定|好了|好啦")


def _as_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if value is None:
        return ""
    return str(value).strip()


def _number(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        result = float(value)
        return result if math.isfinite(result) else default
    try:
        result = float(str(value).strip())
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _clip(value: Any, low: float = 0.0, high: float = 1.0) -> float:
    return min(high, max(low, _number(value, low)))


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _texts(values: Iterable[Any] | None) -> tuple[str, ...]:
    if values is None:
        return ()
    result: list[str] = []
    for value in values:
        text = _as_text(value)
        if text and text not in result:
            result.append(text)
    return tuple(result)


def _round(value: float, digits: int = 4) -> float:
    return round(float(value), digits)


@dataclass(frozen=True)
class PolicyQuestion:
    """One closed-form yes/no policy question for the single-pass judge."""

    question_id: str
    prompt: str
    violation_if_yes: bool = True
    weight: float = 1.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id,
            "prompt": self.prompt,
            "violation_if_yes": self.violation_if_yes,
            "weight": _round(max(0.0, _number(self.weight, 1.0))),
        }


@dataclass(frozen=True)
class QuestionLogprob:
    """Raw ``log P(Yes)`` / ``log P(No)`` for one policy question."""

    question_id: str
    yes_logprob: float
    no_logprob: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id,
            "yes_logprob": _round(self.yes_logprob),
            "no_logprob": _round(self.no_logprob),
        }


@dataclass(frozen=True)
class QuestionScore:
    question_id: str
    yes_probability: float
    violation_confidence: float
    weight: float
    known: bool
    blocked: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id,
            "yes_probability": _round(self.yes_probability),
            "violation_confidence": _round(self.violation_confidence),
            "weight": _round(self.weight),
            "known": self.known,
            "blocked": self.blocked,
        }


@dataclass(frozen=True)
class PolicyCheckResult:
    name: str
    passed: bool
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "passed": self.passed, "detail": self.detail}


@dataclass(frozen=True)
class ChecklistItem:
    name: str
    required: bool = True
    settled: bool = False
    evidence: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "required": self.required,
            "settled": self.settled,
            "evidence": self.evidence,
        }


@dataclass(frozen=True)
class DecisionGateReport:
    code_checks: tuple[PolicyCheckResult, ...]
    question_scores: tuple[QuestionScore, ...]
    checklist: tuple[ChecklistItem, ...]
    blocked: bool
    reasons: tuple[str, ...]
    max_violation: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "code_checks": [item.as_dict() for item in self.code_checks],
            "question_scores": [item.as_dict() for item in self.question_scores],
            "checklist": [item.as_dict() for item in self.checklist],
            "blocked": self.blocked,
            "reasons": list(self.reasons),
            "max_violation": _round(self.max_violation),
        }


DEFAULT_HANDOFF_FIELDS: tuple[str, ...] = (
    "date",
    "duration",
    "item_tier",
    "budget",
    "pickup_region",
)


def _softmax_yes(yes_logprob: float, no_logprob: float) -> float:
    if not math.isfinite(yes_logprob) and not math.isfinite(no_logprob):
        return 0.5
    if not math.isfinite(yes_logprob):
        return 0.0
    if not math.isfinite(no_logprob):
        return 1.0
    pivot = max(yes_logprob, no_logprob)
    yes = math.exp(yes_logprob - pivot)
    no = math.exp(no_logprob - pivot)
    return _clip(yes / (yes + no), 0.0, 1.0)


def evaluate_question_logprobs(
    logprobs: Iterable[QuestionLogprob | Mapping[str, Any]] | None,
    questions: Iterable[PolicyQuestion | Mapping[str, Any]] | None = None,
    *,
    threshold: float = 0.7,
) -> tuple[QuestionScore, ...]:
    """Turn log probabilities into calibrated violation scores.

    A missing or non-finite pair is marked ``known=False`` and is never used to
    block a decision; the gate reports it separately instead of guessing.
    """

    question_map: dict[str, PolicyQuestion] = {}
    for item in questions or ():
        if isinstance(item, PolicyQuestion):
            question_map[item.question_id] = item
        else:
            data = _mapping(item)
            question_id = _as_text(data.get("question_id") or data.get("id"))
            if question_id:
                question_map[question_id] = PolicyQuestion(
                    question_id=question_id,
                    prompt=_as_text(data.get("prompt") or data.get("text")),
                    violation_if_yes=bool(data.get("violation_if_yes", True)),
                    weight=_number(data.get("weight"), 1.0),
                )

    scores: list[QuestionScore] = []
    for logprob_item in logprobs or ():
        if isinstance(logprob_item, QuestionLogprob):
            question_id = logprob_item.question_id
            yes = logprob_item.yes_logprob
            no = logprob_item.no_logprob
        else:
            data = _mapping(logprob_item)
            question_id = _as_text(data.get("question_id") or data.get("id"))
            yes = _number(data.get("yes_logprob"), math.nan)
            no = _number(data.get("no_logprob"), math.nan)
        if not question_id:
            continue
        question = question_map.get(question_id) or PolicyQuestion(
            question_id=question_id,
            prompt=question_id,
        )
        known = math.isfinite(yes) and math.isfinite(no)
        yes_probability = _softmax_yes(yes, no) if known else 0.0
        violation = yes_probability if question.violation_if_yes else 1.0 - yes_probability
        scores.append(
            QuestionScore(
                question_id=question_id,
                yes_probability=yes_probability,
                violation_confidence=violation if known else 0.0,
                weight=max(0.0, _number(question.weight, 1.0)),
                known=known,
                blocked=known and violation >= _clip(threshold, 0.0, 1.0),
            )
        )
    return tuple(scores)


def evaluate_handoff_checklist(
    items: Iterable[ChecklistItem | Mapping[str, Any]] | None,
    *,
    required_names: Iterable[str] | None = None,
) -> tuple[ChecklistItem, ...]:
    """Normalise a hand-off checklist and add missing required placeholders."""

    result: list[ChecklistItem] = []
    seen: set[str] = set()
    for item in items or ():
        if isinstance(item, ChecklistItem):
            entry = item
        else:
            data = _mapping(item)
            name = _as_text(data.get("name") or data.get("field"))
            if not name:
                continue
            entry = ChecklistItem(
                name=name,
                required=bool(data.get("required", True)),
                settled=bool(data.get("settled", False)),
                evidence=_as_text(data.get("evidence")),
            )
        if entry.name in seen:
            continue
        seen.add(entry.name)
        result.append(entry)
    for name in _texts(required_names):
        if name not in seen:
            result.append(ChecklistItem(name=name, required=True, settled=False))
            seen.add(name)
    return tuple(result)


def _check_required_fields(
    payload: Mapping[str, Any], required_fields: Iterable[str]
) -> tuple[PolicyCheckResult, ...]:
    checks: list[PolicyCheckResult] = []
    for field_name in _texts(required_fields):
        value = payload.get(field_name)
        if isinstance(value, str):
            present = bool(value.strip())
        elif isinstance(value, (list, tuple, set, dict)):
            present = bool(value)
        else:
            present = value is not None
        checks.append(
            PolicyCheckResult(
                name=f"required_field:{field_name}",
                passed=present,
                detail="" if present else f"missing required field {field_name}",
            )
        )
    return tuple(checks)


def jev_decision_gate(
    payload: Mapping[str, Any] | None,
    *,
    required_fields: Iterable[str] = _DEFAULT_REQUIRED_FIELDS,
    question_logprobs: Iterable[QuestionLogprob | Mapping[str, Any]] | None = None,
    policy_questions: Iterable[PolicyQuestion | Mapping[str, Any]] | None = None,
    checklist: Iterable[ChecklistItem | Mapping[str, Any]] | None = None,
    handoff: bool = False,
    handoff_fields: Iterable[str] = DEFAULT_HANDOFF_FIELDS,
    violation_threshold: float = 0.7,
) -> DecisionGateReport:
    """Run the deterministic part of the JevAct gate.

    Code checks and the hand-off checklist are fully deterministic.  Policy
    questions use only the caller-supplied log probabilities; unanswered
    questions are reported as unknown and never silently pass as safe.
    """

    data = _mapping(payload)
    checks = list(_check_required_fields(data, required_fields))
    scores = evaluate_question_logprobs(
        question_logprobs,
        policy_questions,
        threshold=violation_threshold,
    )
    checklist_items = evaluate_handoff_checklist(
        checklist,
        required_names=handoff_fields if handoff else (),
    )

    reasons: list[str] = []
    for check in checks:
        if not check.passed:
            reasons.append(f"{check.name}:{check.detail}" if check.detail else check.name)
    for score in scores:
        if score.blocked:
            reasons.append(f"policy_violation:{score.question_id}")
    if handoff:
        for item in checklist_items:
            if item.required and not item.settled:
                reasons.append(f"handoff_unsettled:{item.name}")
    for score in scores:
        if not score.known:
            reasons.append(f"policy_unknown:{score.question_id}")

    blocking_reasons = tuple(
        reason for reason in reasons if not reason.startswith("policy_unknown:")
    )
    max_violation = max((score.violation_confidence for score in scores), default=0.0)
    return DecisionGateReport(
        code_checks=tuple(checks),
        question_scores=scores,
        checklist=checklist_items,
        blocked=bool(blocking_reasons),
        reasons=tuple(reasons),
        max_violation=max_violation,
    )


class PolishStage(StrEnum):
    STAGE0 = "stage0"
    STAGE1 = "stage1"


@dataclass(frozen=True)
class PolishDecision:
    action: str
    reason: str
    human_prob_delta: float = 0.0
    lost_semantic_ids: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "reason": self.reason,
            "human_prob_delta": _round(self.human_prob_delta),
            "lost_semantic_ids": list(self.lost_semantic_ids),
        }


def _stage_text(stage: Mapping[str, Any] | None) -> tuple[str, str]:
    data = _mapping(stage)
    return _as_text(data.get("title")), _as_text(data.get("body"))


def evaluate_stage0_skip(
    stage0: Mapping[str, Any] | None,
    *,
    plad_human_prob: float,
    banned_word_count: int = 0,
    required_sections: Sequence[str] = (),
) -> PolishDecision:
    """Decide whether the stage-0 draft is good enough to skip polishing."""

    title, body = _stage_text(stage0)
    sections = _texts(required_sections)
    missing_sections = [name for name in sections if name not in body]
    if not title or not body:
        return PolishDecision("polish", "stage0_missing_content")
    if missing_sections:
        return PolishDecision(
            "polish",
            "stage0_missing_sections:" + ",".join(missing_sections),
        )
    if _number(banned_word_count, 0.0) > 0:
        return PolishDecision("polish", "stage0_banned_words")
    if _clip(plad_human_prob) < 0.82:
        return PolishDecision("polish", "stage0_plad_below_skip_threshold")
    return PolishDecision("skip", "stage0_already_human_like")


def evaluate_polish_acceptance(
    stage0: Mapping[str, Any] | None,
    stage1: Mapping[str, Any] | None,
    *,
    stage0_human_prob: float,
    stage1_human_prob: float,
    stage0_semantic_ids: Iterable[str] | None = None,
    stage1_semantic_ids: Iterable[str] | None = None,
    min_gain: float = 0.03,
) -> PolishDecision:
    """Accept a polished draft only when it is a Pareto improvement."""

    title1, body1 = _stage_text(stage1)
    if not title1 or not body1:
        return PolishDecision("revert", "stage1_missing_content")
    ids0 = set(_texts(stage0_semantic_ids))
    ids1 = set(_texts(stage1_semantic_ids))
    lost = tuple(sorted(ids0 - ids1))
    delta = _clip(stage1_human_prob) - _clip(stage0_human_prob)
    if lost:
        return PolishDecision(
            "revert",
            "stage1_lost_semantic_ids",
            human_prob_delta=delta,
            lost_semantic_ids=lost,
        )
    if delta < min_gain:
        return PolishDecision(
            "revert",
            "stage1_no_significant_human_gain",
            human_prob_delta=delta,
        )
    return PolishDecision(
        "accept",
        "stage1_pareto_improvement",
        human_prob_delta=delta,
    )


def risk_aware_polish_gate(
    stage0: Mapping[str, Any] | None,
    stage1: Mapping[str, Any] | None = None,
    *,
    plad_human_prob: float,
    banned_word_count: int = 0,
    required_sections: Sequence[str] = (),
    stage1_human_prob: float | None = None,
    stage0_semantic_ids: Iterable[str] | None = None,
    stage1_semantic_ids: Iterable[str] | None = None,
    min_gain: float = 0.03,
) -> PolishDecision:
    """Gate the optional stage-1 polish call."""

    skip = evaluate_stage0_skip(
        stage0,
        plad_human_prob=plad_human_prob,
        banned_word_count=banned_word_count,
        required_sections=required_sections,
    )
    if skip.action == "skip":
        return skip
    if stage1 is None:
        return PolishDecision("polish", f"polish_required:{skip.reason}")
    human1 = _clip(stage1_human_prob) if stage1_human_prob is not None else _clip(plad_human_prob)
    return evaluate_polish_acceptance(
        stage0,
        stage1,
        stage0_human_prob=plad_human_prob,
        stage1_human_prob=human1,
        stage0_semantic_ids=stage0_semantic_ids,
        stage1_semantic_ids=stage1_semantic_ids,
        min_gain=min_gain,
    )


@dataclass(frozen=True)
class UITraceStep:
    step_id: str
    action: str
    selector: str = ""
    slot: str = ""
    postcheck: str = ""
    required_modal: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "action": self.action,
            "selector": self.selector,
            "slot": self.slot,
            "postcheck": self.postcheck,
            "required_modal": self.required_modal,
        }


@dataclass(frozen=True)
class UITraceTemplate:
    name: str
    steps: tuple[UITraceStep, ...]
    dom_fingerprint: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "dom_fingerprint": self.dom_fingerprint,
            "steps": [step.as_dict() for step in self.steps],
        }


@dataclass(frozen=True)
class TraceReplayDecision:
    step_id: str
    action: str
    reason: str
    needs_vlm: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "action": self.action,
            "reason": self.reason,
            "needs_vlm": self.needs_vlm,
        }


@dataclass(frozen=True)
class TraceReplayPlan:
    template_name: str
    decisions: tuple[TraceReplayDecision, ...]
    blocked_step: str
    needs_vlm: bool
    reuse_ratio: float
    estimated_token_savings: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "template_name": self.template_name,
            "decisions": [item.as_dict() for item in self.decisions],
            "blocked_step": self.blocked_step,
            "needs_vlm": self.needs_vlm,
            "reuse_ratio": _round(self.reuse_ratio),
            "estimated_token_savings": _round(self.estimated_token_savings),
        }


def _selector_evidence(evidence: Mapping[str, Any] | Sequence[Any] | None) -> tuple[set[str], str]:
    data = _mapping(evidence)
    selectors: set[str] = set()
    modal = _as_text(data.get("modal"))
    raw = data.get("selectors")
    if isinstance(raw, Mapping):
        for key, value in raw.items():
            if value:
                selectors.add(_as_text(key))
    elif isinstance(raw, (list, tuple, set)):
        selectors.update(_texts(raw))
    elif evidence is not None and not isinstance(evidence, Mapping):
        selectors.update(_texts(evidence))
    for key in ("selector", "selectors_hit", "visible"):
        value = data.get(key)
        if isinstance(value, str):
            selectors.add(value)
        elif isinstance(value, (list, tuple, set)):
            selectors.update(_texts(value))
    return selectors, modal


def replay_ui_trace(
    template: UITraceTemplate | Mapping[str, Any] | None,
    evidence: Mapping[str, Any] | Sequence[Any] | None,
    params: Mapping[str, str] | None = None,
    *,
    unknown_modal: bool = False,
) -> TraceReplayPlan:
    """Replay a saved graph-text UI trace with per-step reuse/rewrite/reject."""

    if isinstance(template, UITraceTemplate):
        name = template.name
        steps = template.steps
    else:
        data = _mapping(template)
        name = _as_text(data.get("name"))
        raw_steps = data.get("steps")
        steps = tuple(
            UITraceStep(
                step_id=_as_text(item.get("step_id") or item.get("id")),
                action=_as_text(item.get("action")),
                selector=_as_text(item.get("selector")),
                slot=_as_text(item.get("slot")),
                postcheck=_as_text(item.get("postcheck")),
                required_modal=_as_text(item.get("required_modal")),
            )
            for item in (raw_steps if isinstance(raw_steps, (list, tuple)) else ())
            if isinstance(item, Mapping)
        )
    selectors, modal = _selector_evidence(evidence)
    values = {str(key): _as_text(value) for key, value in _mapping(params).items()}
    decisions: list[TraceReplayDecision] = []
    blocked = ""
    needs_vlm = False
    reusable = 0
    for step in steps:
        if not step.step_id:
            continue
        if unknown_modal or (step.required_modal and modal and modal != step.required_modal):
            decisions.append(
                TraceReplayDecision(
                    step_id=step.step_id,
                    action="reject",
                    reason="unknown_modal",
                    needs_vlm=True,
                )
            )
            blocked = blocked or step.step_id
            needs_vlm = True
            break
        if step.selector and step.selector not in selectors:
            decisions.append(
                TraceReplayDecision(
                    step_id=step.step_id,
                    action="reject",
                    reason="selector_missing",
                    needs_vlm=True,
                )
            )
            blocked = blocked or step.step_id
            needs_vlm = True
            break
        if step.slot:
            if not values.get(step.slot):
                decisions.append(
                    TraceReplayDecision(
                        step_id=step.step_id,
                        action="reject",
                        reason="missing_slot_value",
                        needs_vlm=True,
                    )
                )
                blocked = blocked or step.step_id
                needs_vlm = True
                break
            decisions.append(
                TraceReplayDecision(
                    step_id=step.step_id,
                    action="rewrite",
                    reason="slot_rewrite_with_postcheck",
                )
            )
            reusable += 1
            continue
        decisions.append(
            TraceReplayDecision(
                step_id=step.step_id,
                action="reuse",
                reason="selector_evidence_present",
            )
        )
        reusable += 1
    total = max(1, len(decisions))
    ratio = reusable / total
    return TraceReplayPlan(
        template_name=name,
        decisions=tuple(decisions),
        blocked_step=blocked,
        needs_vlm=needs_vlm,
        reuse_ratio=ratio,
        estimated_token_savings=0.8 * ratio,
    )


@dataclass(frozen=True)
class SimCandidate:
    candidate_id: str
    utility: float
    features: Mapping[str, float] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "utility": _round(self.utility),
            "features": {
                str(key): _round(_number(value)) for key, value in _mapping(self.features).items()
            },
        }


@dataclass(frozen=True)
class SensitivityReport:
    candidate_a: str
    candidate_b: str
    samples: int
    rank_flip_rate: float
    order_preserving: bool
    decision: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "candidate_a": self.candidate_a,
            "candidate_b": self.candidate_b,
            "samples": self.samples,
            "rank_flip_rate": _round(self.rank_flip_rate),
            "order_preserving": self.order_preserving,
            "decision": self.decision,
        }


def perturb_utility(
    candidate: SimCandidate,
    delta: Mapping[str, float] | None,
    sensitivity: Mapping[str, float] | None = None,
) -> float:
    """Apply a controlled feature perturbation to a simulated utility."""

    features = _mapping(candidate.features)
    weights = _mapping(sensitivity)
    change = 0.0
    for key, value in _mapping(delta).items():
        weight = _number(weights.get(key), 1.0)
        feature_value = _number(features.get(key), 1.0)
        change += weight * feature_value * _number(value)
    return _number(candidate.utility) + change


def _perturbations_for(
    candidates: Sequence[SimCandidate],
    epsilon: float,
) -> tuple[dict[str, float], ...]:
    keys: set[str] = set()
    for candidate in candidates:
        keys.update(str(key) for key in _mapping(candidate.features))
    if not keys:
        keys.add("__utility__")
    result: list[dict[str, float]] = []
    for key in sorted(keys):
        result.append({key: epsilon})
        result.append({key: -epsilon})
    return tuple(result)


def sim_decision_sensitivity_gate(
    candidate_a: SimCandidate,
    candidate_b: SimCandidate,
    *,
    sensitivity: Mapping[str, float] | None = None,
    perturbations: Iterable[Mapping[str, float]] | None = None,
    epsilon: float = 0.1,
    flip_threshold: float = 0.25,
) -> SensitivityReport:
    """Test whether a simulator's ranking survives controlled perturbations."""

    deltas = (
        tuple(perturbations)
        if perturbations is not None
        else _perturbations_for((candidate_a, candidate_b), epsilon)
    )
    base_delta = _number(candidate_a.utility) - _number(candidate_b.utility)
    flips = 0
    for delta in deltas:
        value_a = perturb_utility(candidate_a, delta, sensitivity)
        value_b = perturb_utility(candidate_b, delta, sensitivity)
        perturbed_delta = value_a - value_b
        if base_delta == 0.0:
            flips += 1 if perturbed_delta != 0.0 else 0
        elif (perturbed_delta > 0.0) != (base_delta > 0.0):
            flips += 1
    samples = len(deltas)
    rate = flips / samples if samples else 1.0
    order_preserving = rate <= _clip(flip_threshold)
    if not order_preserving or base_delta == 0.0:
        decision = "escalate"
    elif base_delta > 0.0:
        decision = "lock_a"
    else:
        decision = "lock_b"
    return SensitivityReport(
        candidate_a=candidate_a.candidate_id,
        candidate_b=candidate_b.candidate_id,
        samples=samples,
        rank_flip_rate=rate,
        order_preserving=order_preserving,
        decision=decision,
    )


@dataclass(frozen=True)
class ActionClaim:
    claim_id: str
    text: str
    action: str

    def as_dict(self) -> dict[str, Any]:
        return {"claim_id": self.claim_id, "text": self.text, "action": self.action}


@dataclass(frozen=True)
class ToolReceipt:
    action: str
    status: str
    entity_id: str = ""
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "status": self.status,
            "entity_id": self.entity_id,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class UnusableReplyReport:
    blocked: bool
    claims: tuple[ActionClaim, ...]
    missing_receipts: tuple[str, ...]
    hollow: bool
    reasons: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "blocked": self.blocked,
            "claims": [claim.as_dict() for claim in self.claims],
            "missing_receipts": list(self.missing_receipts),
            "hollow": self.hollow,
            "reasons": list(self.reasons),
        }


def _sentences(text: str) -> tuple[str, ...]:
    parts = re.split(r"[。！？!?；;，,\n]+", text)
    return tuple(part.strip() for part in parts if part.strip())


def extract_action_claims(text: str) -> tuple[ActionClaim, ...]:
    """Find sentences that claim a tool action already completed."""

    claims: list[ActionClaim] = []
    for _index, sentence in enumerate(_sentences(text)):
        if not _COMPLETION_RE.search(sentence):
            continue
        for verb in _ACTION_VERBS:
            if verb in sentence:
                claims.append(
                    ActionClaim(
                        claim_id=f"claim-{len(claims) + 1}",
                        text=sentence,
                        action=verb,
                    )
                )
                break
    return tuple(claims)


def _is_success_receipt(receipt: ToolReceipt) -> bool:
    return receipt.status.strip().lower() in {
        "succeeded",
        "success",
        "ok",
        "completed",
        "done",
    } and bool(receipt.entity_id.strip() or receipt.detail.strip())


def _is_hollow_reply(text: str, customer_question: str, min_chars: int) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    if len(stripped) >= min_chars and re.search(r"\d", stripped):
        return False
    condensed = re.sub(r"[\s，。！？、,.!?~～…]+", "", stripped)
    if not condensed:
        return True
    for marker in _HOLLOW_MARKERS:
        condensed = condensed.replace(marker, "")
    return not condensed


def filter_unusable_reply(
    text: str,
    *,
    receipts: Iterable[ToolReceipt | Mapping[str, Any]] | None = None,
    customer_question: str = "",
    min_chars: int = 12,
) -> UnusableReplyReport:
    """Block completion claims without receipts and content-free replies."""

    claims_list = extract_action_claims(text)
    receipts_list: list[ToolReceipt] = []
    for item in receipts or ():
        if isinstance(item, ToolReceipt):
            receipts_list.append(item)
        else:
            data = _mapping(item)
            receipts_list.append(
                ToolReceipt(
                    action=_as_text(data.get("action") or data.get("kind")),
                    status=_as_text(data.get("status")),
                    entity_id=_as_text(data.get("entity_id") or data.get("id")),
                    detail=_as_text(data.get("detail")),
                )
            )
    successful = [receipt for receipt in receipts_list if _is_success_receipt(receipt)]
    missing: list[str] = []
    for claim in claims_list:
        matched = any(
            bool(receipt.action)
            and (claim.action in receipt.action or receipt.action in claim.action)
            for receipt in successful
        )
        if not matched:
            missing.append(claim.claim_id)
    hollow = _is_hollow_reply(text, customer_question, min_chars)
    reasons: list[str] = []
    if missing:
        reasons.append("action_claim_without_receipt")
    if hollow:
        reasons.append("hollow_reply")
    return UnusableReplyReport(
        blocked=bool(missing or hollow),
        claims=claims_list,
        missing_receipts=tuple(missing),
        hollow=hollow,
        reasons=tuple(reasons),
    )


@dataclass(frozen=True)
class RolloutWeek:
    week: int
    theme: str
    plan_ids: tuple[str, ...]
    exit_criteria: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "week": self.week,
            "theme": self.theme,
            "plan_ids": list(self.plan_ids),
            "exit_criteria": self.exit_criteria,
        }


PHASE10_ROLLOUT: tuple[RolloutWeek, ...] = (
    RolloutWeek(
        week=1,
        theme="安全、状态一致性与防错发底座",
        plan_ids=("#43", "#39", "#5", "#19", "#16", "#36", "#53"),
        exit_criteria="跨账号审批零错发、排水零重复发布、公开回放零隐私残留",
    ),
    RolloutWeek(
        week=2,
        theme="推荐/搜索核心算法与质量门禁",
        plan_ids=("#3", "#1", "#31", "#2", "#55", "#32", "#33", "#37"),
        exit_criteria="收藏优先排序可用、曝光限流可诊断、双层质量门可回滚",
    ),
    RolloutWeek(
        week=3,
        theme="双模型协同、记忆演化链与错误回滚",
        plan_ids=("#25", "#26", "#27", "#28", "#29", "#30", "#49", "#50", "#51", "#56"),
        exit_criteria="异构评审稳定、压缩后规则不漂移、错误可定点回滚",
    ),
    RolloutWeek(
        week=4,
        theme="私信增益、矩阵防碰撞、GUI 轨迹复用与 CI 基准",
        plan_ids=("#11", "#44", "#59", "#38", "#45", "#46", "#57", "#41", "#47", "#42"),
        exit_criteria="私信配额按增益分配、矩阵零撞题、离线基准门禁全绿",
    ),
)


def build_rollout_plan() -> tuple[RolloutWeek, ...]:
    """Return the immutable four-week phase-10 rollout plan."""

    return PHASE10_ROLLOUT
