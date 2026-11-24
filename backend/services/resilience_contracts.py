"""Phase-14 resilience contracts (ledger schemes 79-84).

Deterministic causal, stress, replanning, bounded-context and chaos helpers.
Standard library only; no runtime wiring.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

__all__ = [
    "BeliefEntropySummaryGate",
    "BeliefProbe",
    "CausalEstimate",
    "ChaosConfig",
    "ChaosReport",
    "ChaosRun",
    "ControlFunctionCausalEstimator",
    "MetamorphicCase",
    "REPLAN_ROUTES",
    "ReplanDecision",
    "StressDecision",
    "SummaryGateResult",
    "ToolEvent",
    "WorkspaceState",
    "build_bounded_context",
    "evaluate_stress_window",
    "pass_power_k",
    "plan_tool_recovery",
    "probe_entropy",
    "render_workspace_state",
    "run_metamorphic_chaos",
]


def _round(value: float) -> float:
    return round(float(value), 4)


def _mean(values: Iterable[float]) -> float:
    items = [float(item) for item in values]
    if not items:
        return 0.0
    return sum(items) / len(items)


def _variance(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = _mean(values)
    return sum((value - mean) ** 2 for value in values) / len(values)


def _covariance(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    left_mean = _mean(left)
    right_mean = _mean(right)
    return sum((a - left_mean) * (b - right_mean) for a, b in zip(left, right, strict=True)) / len(
        left
    )


def _solve_2x2(a: float, b: float, c: float, d: float, e: float, f: float) -> tuple[float, float]:
    determinant = a * d - b * c
    if abs(determinant) < 1e-12:
        raise ValueError("singular normal equations")
    return ((e * d - b * f) / determinant, (a * f - e * c) / determinant)


@dataclass(frozen=True)
class CausalEstimate:
    effect: float
    residual_strength: float
    instrument_strength: float
    observations: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "effect": _round(self.effect),
            "residual_strength": _round(self.residual_strength),
            "instrument_strength": _round(self.instrument_strength),
            "observations": self.observations,
        }


class ControlFunctionCausalEstimator:
    """Two-stage control-function estimate for a single treatment."""

    @staticmethod
    def fit(
        treatments: Sequence[float],
        outcomes: Sequence[float],
        instruments: Sequence[float],
    ) -> CausalEstimate:
        if not (len(treatments) == len(outcomes) == len(instruments)):
            raise ValueError("treatments, outcomes and instruments must align")
        if len(treatments) < 3:
            raise ValueError("at least three observations are required")
        a = [float(item) for item in treatments]
        y = [float(item) for item in outcomes]
        z = [float(item) for item in instruments]
        z_variance = _variance(z)
        if z_variance < 1e-12:
            raise ValueError("instrument has no variance")

        stage1_slope = _covariance(a, z) / z_variance
        stage1_intercept = _mean(a) - stage1_slope * _mean(z)
        residuals = [
            value - (stage1_intercept + stage1_slope * instrument)
            for value, instrument in zip(a, z, strict=True)
        ]

        # Stage 2: y = b0 + b1 * treatment + b2 * residual
        a_mean = _mean(a)
        r_mean = _mean(residuals)
        y_mean = _mean(y)
        s_aa = sum((value - a_mean) ** 2 for value in a)
        s_ar = sum(
            (value - a_mean) * (residual - r_mean)
            for value, residual in zip(a, residuals, strict=True)
        )
        s_rr = sum((residual - r_mean) ** 2 for residual in residuals)
        s_ay = sum((value - a_mean) * (target - y_mean) for value, target in zip(a, y, strict=True))
        s_ry = sum(
            (residual - r_mean) * (target - y_mean)
            for residual, target in zip(residuals, y, strict=True)
        )
        effect, _residual_coefficient = _solve_2x2(s_aa, s_ar, s_ar, s_rr, s_ay, s_ry)

        a_std = math.sqrt(_variance(a))
        z_std = math.sqrt(z_variance)
        correlation = 0.0
        if a_std > 0 and z_std > 0:
            correlation = _covariance(a, z) / (a_std * z_std)
        return CausalEstimate(
            effect=_round(effect),
            residual_strength=_round(math.sqrt(_variance(residuals))),
            instrument_strength=_round(abs(correlation)),
            observations=len(a),
        )


@dataclass(frozen=True)
class BeliefProbe:
    question: str
    answer_logprobs: Mapping[str, float]


@dataclass(frozen=True)
class SummaryGateResult:
    accepted: bool
    entropy: float
    threshold: float
    reasons: tuple[str, ...]
    need_resummarize: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "entropy": _round(self.entropy),
            "threshold": _round(self.threshold),
            "reasons": list(self.reasons),
            "need_resummarize": self.need_resummarize,
        }


def probe_entropy(probe: BeliefProbe) -> float:
    values = [float(item) for item in probe.answer_logprobs.values()]
    if not values:
        return 1.0
    maximum = max(values)
    weights = [math.exp(value - maximum) for value in values]
    total = sum(weights) or 1.0
    probabilities = [weight / total for weight in weights]
    entropy = -sum(probability * math.log(max(probability, 1e-12)) for probability in probabilities)
    normalizer = math.log(len(probabilities)) if len(probabilities) > 1 else 1.0
    return max(0.0, min(1.0, entropy / normalizer))


class BeliefEntropySummaryGate:
    """Reject a compressed summary when it leaves anchor questions uncertain."""

    def __init__(self, *, threshold: float = 0.7) -> None:
        if not 0.0 <= threshold <= 1.0:
            raise ValueError("threshold must be in [0, 1]")
        self._threshold = threshold

    @property
    def threshold(self) -> float:
        return self._threshold

    def evaluate(self, probes: Sequence[BeliefProbe]) -> SummaryGateResult:
        if not probes:
            return SummaryGateResult(
                accepted=False,
                entropy=0.0,
                threshold=self._threshold,
                reasons=("no_probes",),
                need_resummarize=True,
            )
        entropies = [probe_entropy(probe) for probe in probes]
        entropy = _mean(entropies)
        reasons = tuple(
            f"high_entropy:{probe.question}"
            for probe, value in zip(probes, entropies, strict=True)
            if value > self._threshold
        )
        accepted = entropy <= self._threshold and not reasons
        return SummaryGateResult(
            accepted=accepted,
            entropy=entropy,
            threshold=self._threshold,
            reasons=reasons or ("entropy_within_budget",),
            need_resummarize=not accepted,
        )


@dataclass(frozen=True)
class ToolEvent:
    at: float
    ok: bool
    rate_limited: bool = False
    timed_out: bool = False


@dataclass(frozen=True)
class StressDecision:
    lambda_hat: float
    degraded: bool
    disable_reflexion: bool
    mode: str
    retry_policy: str
    reasons: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "lambda_hat": _round(self.lambda_hat),
            "degraded": self.degraded,
            "disable_reflexion": self.disable_reflexion,
            "mode": self.mode,
            "retry_policy": self.retry_policy,
            "reasons": list(self.reasons),
        }


def evaluate_stress_window(
    events: Iterable[ToolEvent],
    *,
    now: float | None = None,
    window_seconds: float = 300.0,
    threshold: float = 0.15,
) -> StressDecision:
    rows = list(events)
    if now is None:
        now = max((event.at for event in rows), default=0.0)
    window = [event for event in rows if float(now) - float(event.at) <= float(window_seconds)]
    if not window:
        return StressDecision(
            lambda_hat=0.0,
            degraded=False,
            disable_reflexion=False,
            mode="reflexion",
            retry_policy="standard",
            reasons=("no_events",),
        )
    failures = sum(
        1 for event in window if (not event.ok) and (event.rate_limited or event.timed_out)
    )
    lambda_hat = failures / len(window)
    degraded = lambda_hat > threshold
    return StressDecision(
        lambda_hat=_round(lambda_hat),
        degraded=degraded,
        disable_reflexion=degraded,
        mode="linear_react" if degraded else "reflexion",
        retry_policy="exponential_backoff_jitter" if degraded else "standard",
        reasons=(
            f"pressure:{_round(lambda_hat)}",
            f"events:{len(window)}",
        ),
    )


REPLAN_ROUTES: dict[str, tuple[str, ...]] = {
    "xhs_trending": ("keyword_monitor_cache", "hy_memory_breakout_pool"),
    "competitor_analyzer": ("keyword_monitor_cache", "stored_competitor_snapshots"),
    "ripple_predict": ("local_oransim_lightgbm", "provider_insights_salvage"),
    "image_prompt_generator": ("template_prompt_fallback", "layout_recommender"),
    "xhs_publisher": ("offline_markdown_bundle", "human_review_copy"),
    "dm_handler": ("offline_reply_template", "human_review_reply"),
}


@dataclass(frozen=True)
class ReplanDecision:
    tool_name: str
    failure_kind: str
    fallbacks: tuple[str, ...]
    action: str
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "failure_kind": self.failure_kind,
            "fallbacks": list(self.fallbacks),
            "action": self.action,
            "reason": self.reason,
        }


def plan_tool_recovery(
    tool_name: str,
    failure_kind: str = "unavailable",
    *,
    retryable: bool = False,
) -> ReplanDecision:
    fallbacks = REPLAN_ROUTES.get(tool_name, ())
    if not tool_name:
        raise ValueError("tool_name must not be empty")
    if retryable:
        return ReplanDecision(
            tool_name=tool_name,
            failure_kind=failure_kind,
            fallbacks=(),
            action="retry",
            reason="transient_failure",
        )
    if not fallbacks:
        return ReplanDecision(
            tool_name=tool_name,
            failure_kind=failure_kind,
            fallbacks=(),
            action="manual_review",
            reason="no_replan_route",
        )
    return ReplanDecision(
        tool_name=tool_name,
        failure_kind=failure_kind,
        fallbacks=fallbacks,
        action="replan",
        reason=f"capability_fallback:{failure_kind}",
    )


@dataclass(frozen=True)
class WorkspaceState:
    active_draft_id: str
    constraints: tuple[str, ...] = ()
    todos: tuple[str, ...] = ()
    competitor_summary: str = ""
    recent_turns: tuple[Mapping[str, str], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "active_draft_id": self.active_draft_id,
            "constraints": list(self.constraints),
            "todos": list(self.todos),
            "competitor_summary": self.competitor_summary,
            "recent_turns": [dict(turn) for turn in self.recent_turns],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> WorkspaceState:
        return cls(
            active_draft_id=str(payload.get("active_draft_id", "")),
            constraints=tuple(str(item) for item in payload.get("constraints", ())),
            todos=tuple(str(item) for item in payload.get("todos", ())),
            competitor_summary=str(payload.get("competitor_summary", "")),
            recent_turns=tuple(
                {str(key): str(value) for key, value in dict(turn).items()}
                for turn in payload.get("recent_turns", ())
            ),
        )

    def to_markdown(self) -> str:
        lines = [
            "# Workspace state",
            f"- active_draft_id: {self.active_draft_id}",
            "## Constraints",
        ]
        lines.extend(f"- {item}" for item in self.constraints)
        lines.append("## TODOs")
        lines.extend(f"- {item}" for item in self.todos)
        lines.append("## Competitor summary")
        lines.append(self.competitor_summary)
        return "\n".join(lines)

    @classmethod
    def from_markdown(cls, text: str) -> WorkspaceState:
        draft_id = ""
        constraints: list[str] = []
        todos: list[str] = []
        competitor: list[str] = []
        section = ""
        for raw in text.splitlines():
            line = raw.strip()
            if line.startswith("- active_draft_id:"):
                draft_id = line.split(":", 1)[1].strip()
            elif line == "## Constraints":
                section = "constraints"
            elif line == "## TODOs":
                section = "todos"
            elif line == "## Competitor summary":
                section = "competitor"
            elif line.startswith("- ") and section == "constraints":
                constraints.append(line[2:].strip())
            elif line.startswith("- ") and section == "todos":
                todos.append(line[2:].strip())
            elif section == "competitor" and line:
                competitor.append(line)
        return cls(
            active_draft_id=draft_id,
            constraints=tuple(constraints),
            todos=tuple(todos),
            competitor_summary="\n".join(competitor),
        )


def render_workspace_state(state: WorkspaceState) -> str:
    return state.to_markdown()


def build_bounded_context(
    state: WorkspaceState,
    recent_messages: Sequence[Mapping[str, str]],
    *,
    max_turns: int = 6,
    max_chars: int = 4000,
) -> dict[str, Any]:
    if max_turns < 0:
        raise ValueError("max_turns must be >= 0")
    if max_chars < 1:
        raise ValueError("max_chars must be >= 1")
    messages = [dict(item) for item in recent_messages[-max_turns:]] if max_turns else []
    rendered = state.to_markdown()
    compact: list[dict[str, str]] = []
    for message in messages:
        candidate = compact + [message]
        payload = (
            rendered
            + "\n"
            + "\n".join(f"{item.get('role', '')}: {item.get('content', '')}" for item in candidate)
        )
        if len(payload) > max_chars and compact:
            break
        compact.append(message)
    return {"state": rendered, "messages": compact}


@dataclass(frozen=True)
class ChaosConfig:
    epsilon: float = 0.2
    lambda_: float = 0.15
    repeats: int = 3
    seed: int = 7

    def as_dict(self) -> dict[str, Any]:
        return {
            "epsilon": _round(self.epsilon),
            "lambda_": _round(self.lambda_),
            "repeats": self.repeats,
            "seed": self.seed,
        }


@dataclass(frozen=True)
class MetamorphicCase:
    case_id: str
    perturbed_input: str
    expected_terminal: Mapping[str, Any]


@dataclass(frozen=True)
class ChaosRun:
    case_id: str
    attempt: int
    injected_fault: str
    terminal: Mapping[str, Any]
    passed: bool


@dataclass(frozen=True)
class ChaosReport:
    pass_power_k: float
    case_pass: Mapping[str, bool]
    runs: tuple[ChaosRun, ...]
    passed: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "pass_power_k": _round(self.pass_power_k),
            "case_pass": dict(self.case_pass),
            "runs": [
                {
                    "case_id": run.case_id,
                    "attempt": run.attempt,
                    "injected_fault": run.injected_fault,
                    "terminal": dict(run.terminal),
                    "passed": run.passed,
                }
                for run in self.runs
            ],
            "passed": self.passed,
        }


def _default_executor(case: MetamorphicCase, fault: str) -> Mapping[str, Any]:
    if fault == "none":
        return dict(case.expected_terminal)
    return {"status": "faulted", "fault": fault}


def run_metamorphic_chaos(
    cases: Sequence[MetamorphicCase],
    *,
    config: Any = None,
    executor: Callable[[MetamorphicCase, str], Mapping[str, Any]] | None = None,
) -> ChaosReport:
    if not cases:
        raise ValueError("cases must not be empty")
    settings = config or ChaosConfig()
    epsilon = float(getattr(settings, "epsilon", 0.2))
    lambda_ = float(getattr(settings, "lambda_", 0.15))
    repeats = int(getattr(settings, "repeats", 3))
    seed = int(getattr(settings, "seed", 7))
    if repeats < 1:
        raise ValueError("repeats must be >= 1")
    handler = executor or _default_executor
    runs: list[ChaosRun] = []
    case_pass: dict[str, bool] = {}
    for case in cases:
        outcomes: list[bool] = []
        for attempt in range(repeats):
            rng = random.Random(f"{seed}:{case.case_id}:{attempt}:{epsilon}")
            fault = "rate_limit" if rng.random() < lambda_ else "none"
            terminal = dict(handler(case, fault))
            passed = terminal == dict(case.expected_terminal)
            outcomes.append(passed)
            runs.append(
                ChaosRun(
                    case_id=case.case_id,
                    attempt=attempt,
                    injected_fault=fault,
                    terminal=terminal,
                    passed=passed,
                )
            )
        case_pass[case.case_id] = all(outcomes)
    rate = sum(1 for value in case_pass.values() if value) / len(case_pass)
    return ChaosReport(
        pass_power_k=_round(rate),
        case_pass=case_pass,
        runs=tuple(runs),
        passed=rate >= 0.95,
    )


def pass_power_k(report: ChaosReport) -> float:
    return report.pass_power_k
