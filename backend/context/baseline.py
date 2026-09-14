"""P1b-S5 acceptance baseline: token cost and layer stability.

The whole P1b migration (S1-S4) exists to make prompt assembly auditable:
static policy sits in stable layers, recalled context is deduped / reranked /
budget-trimmed, and the render order is canonical L0→L5. This module is the
acceptance yardstick for that claim. It is fully offline and deterministic —
no workflow, no store, no LLM call — so it can run inside CI as a gate.

Two axes:

**Token cost** — compare each agent's prompt against the pre-migration
assembly: static layer text + every recalled body appended raw (no dedup,
no rerank, no budget). The delta is what dedup / rerank / budget actually
buy; a negative delta means the compiler removed duplicate or low-value
context.

**Layer stability** — compile the same inputs repeatedly and with shuffled
recall order; the rendered prompt must be byte-identical every time, and a
tightened budget must trim from the tail (L5 first) while leaving the stable
prefix (L0-L3) untouched.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from backend.context.compiler import ContextCompiler
from backend.context.estimator import estimate_tokens
from backend.context.models import (
    LAYER_ORDER,
    ContextItem,
    PromptLayer,
    RetrievalMode,
    RetrievalResult,
    RunContext,
)
from backend.context.segments import parse_system_segments

DEFAULT_PROMPT_DIR = Path(__file__).resolve().parents[1] / "config" / "prompts"
"""Backend prompt YAML directory (agents read the same files at runtime)."""


@dataclass(frozen=True)
class AgentCase:
    """One agent's prompt plus the synthetic recall used to exercise it."""

    name: str
    system_text: str
    user_template: str = ""
    retrievals: tuple[RetrievalResult, ...] = ()


@dataclass(frozen=True)
class CostRow:
    """Token cost of one agent: pre-migration baseline vs compiled."""

    agent: str
    baseline_tokens: int
    compiled_tokens: int
    layer_tokens: dict[str, int]

    @property
    def delta(self) -> int:
        return self.compiled_tokens - self.baseline_tokens

    @property
    def pct(self) -> float:
        if self.baseline_tokens == 0:
            return 0.0
        return (self.delta / self.baseline_tokens) * 100.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "baseline_tokens": self.baseline_tokens,
            "compiled_tokens": self.compiled_tokens,
            "delta": self.delta,
            "pct": round(self.pct, 2),
            "layer_tokens": self.layer_tokens,
        }


@dataclass(frozen=True)
class StabilityRow:
    """Stability checks for one agent (all four must hold)."""

    agent: str
    repeat_ok: bool
    shuffle_ok: bool
    dedup_ok: bool
    budget_ok: bool
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.repeat_ok and self.shuffle_ok and self.dedup_ok and self.budget_ok

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "repeat_ok": self.repeat_ok,
            "shuffle_ok": self.shuffle_ok,
            "dedup_ok": self.dedup_ok,
            "budget_ok": self.budget_ok,
            "ok": self.ok,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class BaselineReport:
    """The full acceptance report."""

    budget: int | None
    costs: tuple[CostRow, ...]
    stability: tuple[StabilityRow, ...]
    scenario: str = "default"

    @property
    def ok(self) -> bool:
        return all(row.ok for row in self.stability)

    @property
    def total_baseline(self) -> int:
        return sum(row.baseline_tokens for row in self.costs)

    @property
    def total_compiled(self) -> int:
        return sum(row.compiled_tokens for row in self.costs)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario,
            "budget": self.budget,
            "ok": self.ok,
            "totals": {
                "baseline_tokens": self.total_baseline,
                "compiled_tokens": self.total_compiled,
                "delta": self.total_compiled - self.total_baseline,
                "pct": (
                    round(
                        ((self.total_compiled - self.total_baseline) / self.total_baseline) * 100.0,
                        2,
                    )
                    if self.total_baseline
                    else 0.0
                ),
            },
            "costs": [row.to_dict() for row in self.costs],
            "stability": [row.to_dict() for row in self.stability],
        }


def synthetic_retrievals(
    *,
    niche: str,
    now: datetime | None = None,
    stress: bool = False,
) -> tuple[RetrievalResult, ...]:
    """Deterministic recall fixture shared by every agent case.

    Bodies are distinct and carry a strict total order (distinct timestamps
    *and* confidences), so shuffling the input must not change the reranked
    output — that is exactly what the shuffle check asserts.

    ``stress=True`` models the messy real-world recall the compiler exists
    for: every item arrives twice (duplicate store hits) and a long tail of
    low-value observations inflates L5. The baseline counts all of it, so the
    delta shows what dedup + budget actually save.
    """
    base = now or datetime(2026, 9, 14, tzinfo=UTC)
    specs: tuple[tuple[str, str, int, float, PromptLayer], ...] = (
        ("- 辅食食谱（互动率: 4.2%）", "content_history", 10, 0.9, PromptLayer.L4_MEMORY),
        ("- 早教游戏（互动率: 3.1%）", "content_history", 20, 0.8, PromptLayer.L4_MEMORY),
        ("- 亲子露营（互动率: 2.4%）", "content_history", 30, 0.7, PromptLayer.L4_MEMORY),
        ("偏好：实用清单式内容", "audience_preferences", 40, 0.6, PromptLayer.L4_MEMORY),
        ("近期同类笔记完播率偏低", "performance_insights", 50, 0.5, PromptLayer.L5_OBSERVATION),
        ("评论区高频提问：安全座椅", "performance_insights", 60, 0.4, PromptLayer.L5_OBSERVATION),
    )
    if stress:
        specs += (
            ("- 辅食食谱（互动率: 4.2%）", "content_history", 10, 0.9, PromptLayer.L4_MEMORY),
            ("- 早教游戏（互动率: 3.1%）", "content_history", 20, 0.8, PromptLayer.L4_MEMORY),
            ("偏好：实用清单式内容", "audience_preferences", 40, 0.6, PromptLayer.L4_MEMORY),
            (
                "评论区高频提问：安全座椅",
                "performance_insights",
                60,
                0.4,
                PromptLayer.L5_OBSERVATION,
            ),
            ("话题热度：换季护理上升", "performance_insights", 70, 0.3, PromptLayer.L5_OBSERVATION),
            ("竞品笔记密集发布", "performance_insights", 80, 0.2, PromptLayer.L5_OBSERVATION),
        )
    grouped: dict[tuple[str, PromptLayer], list[ContextItem]] = {}
    for body, source, offset, confidence, layer in specs:
        item = ContextItem(
            body=body,
            source=source,
            timestamp=base - timedelta(minutes=offset),
            confidence=confidence,
            priority=0,
        )
        grouped.setdefault((source, layer), []).append(item)

    return tuple(
        RetrievalResult(
            namespace=source,
            layer=layer,
            items=tuple(items),
            mode=RetrievalMode.HIT,
        )
        for (source, layer), items in grouped.items()
    )


def _system_context(niche: str) -> RunContext:
    return RunContext(
        thread_id="baseline-thread",
        account_id="baseline-account",
        niche=niche,
        values={"niche": niche},
    )


def load_agent_cases(
    prompt_dir: Path | str = DEFAULT_PROMPT_DIR,
    *,
    retrievals: tuple[RetrievalResult, ...] | None = None,
    niche: str = "母婴",
    stress: bool = False,
) -> tuple[AgentCase, ...]:
    """Load every agent prompt YAML as a baseline case.

    Skips non-agent files (``tools/`` subdir, ``__init__.py``). The read is
    plain ``yaml.safe_load`` — same files the runtime loads.
    """
    directory = Path(prompt_dir)
    cases: list[AgentCase] = []
    for path in sorted(directory.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        system_text = data.get("system", "")
        if not isinstance(system_text, str) or not system_text.strip():
            continue
        cases.append(
            AgentCase(
                name=path.stem,
                system_text=system_text,
                user_template=str(data.get("user_template", "") or ""),
                retrievals=retrievals if retrievals is not None else (),
            )
        )
    # Shared synthetic recall (built once so every agent sees identical input)
    shared = (
        retrievals if retrievals is not None else synthetic_retrievals(niche=niche, stress=stress)
    )
    return tuple(
        AgentCase(
            name=case.name,
            system_text=case.system_text,
            user_template=case.user_template,
            retrievals=shared,
        )
        for case in cases
    )


def _baseline_text(case: AgentCase) -> str:
    """Pre-migration equivalent: static text + every recalled body, raw.

    Markers are not part of the semantic text (the parser drops them), so the
    baseline joins the parsed static sections — otherwise the comparison would
    charge the compiler for marker lines it never emits.
    """
    sections = parse_system_segments(case.system_text)
    if case.user_template:
        existing = sections.get(PromptLayer.L3_TASK, "")
        sections[PromptLayer.L3_TASK] = "\n\n".join(
            part for part in (existing, case.user_template) if part
        )
    static = "\n\n".join(sections[layer] for layer in LAYER_ORDER if sections.get(layer))
    bodies = "\n".join(item.body for result in case.retrievals for item in result.items)
    return "\n".join(part for part in (static, bodies) if part)


def measure_cost(
    case: AgentCase,
    compiler: ContextCompiler | None = None,
    *,
    budget: int | None = None,
    niche: str = "母婴",
) -> CostRow:
    """Token cost of one agent: pre-migration baseline vs compiled."""
    engine = compiler or ContextCompiler()
    compiled = engine.compile_prompt(
        _system_context(niche),
        case.system_text,
        case.user_template,
        case.retrievals,
        budget=budget,
    )
    layer_tokens = {layer.value: estimate_tokens(text) for layer, text in compiled.layers.items()}
    return CostRow(
        agent=case.name,
        baseline_tokens=estimate_tokens(_baseline_text(case)),
        compiled_tokens=estimate_tokens(compiled.render()),
        layer_tokens=layer_tokens,
    )


def _shuffled(retrievals: Sequence[RetrievalResult]) -> tuple[RetrievalResult, ...]:
    """Reverse every ordering the compiler is allowed to see as unstable.

    Reverses the result list and each result's items; a deterministic rerank
    must still produce the same rendered prompt.
    """
    return tuple(
        RetrievalResult(
            namespace=result.namespace,
            layer=result.layer,
            items=tuple(reversed(result.items)),
            mode=result.mode,
            error=result.error,
        )
        for result in reversed(retrievals)
    )


def _with_duplicates(retrievals: Sequence[RetrievalResult]) -> tuple[RetrievalResult, ...]:
    """Duplicate every item in place — dedup must absorb it (no token growth)."""
    return tuple(
        RetrievalResult(
            namespace=result.namespace,
            layer=result.layer,
            items=result.items + result.items,
            mode=result.mode,
            error=result.error,
        )
        for result in retrievals
    )


def _stable_prefix(compiled_text_layers: Mapping[PromptLayer, str]) -> str:
    return "\n\n".join(
        compiled_text_layers[layer]
        for layer in (
            PromptLayer.L0_SYSTEM,
            PromptLayer.L1_TOOL_SCHEMA,
            PromptLayer.L2_ACCOUNT,
            PromptLayer.L3_TASK,
        )
        if layer in compiled_text_layers
    )


def measure_stability(
    case: AgentCase,
    compiler: ContextCompiler | None = None,
    *,
    repeats: int = 3,
    budget: int | None = None,
    niche: str = "母婴",
) -> StabilityRow:
    """Compile the same case repeatedly / shuffled / duplicated / budgeted."""
    engine = compiler or ContextCompiler()
    ctx = _system_context(niche)
    detail = ""

    renders = [
        engine.compile_prompt(
            ctx, case.system_text, case.user_template, case.retrievals, budget=budget
        ).render()
        for _ in range(max(2, repeats))
    ]
    repeat_ok = len(set(renders)) == 1

    shuffled = engine.compile_prompt(
        ctx, case.system_text, case.user_template, _shuffled(case.retrievals), budget=budget
    ).render()
    shuffle_ok = shuffled == renders[0]

    dedup_render = engine.compile_prompt(
        ctx,
        case.system_text,
        case.user_template,
        _with_duplicates(case.retrievals),
        budget=budget,
    ).render()
    dedup_ok = dedup_render == renders[0]

    # Budget gate: tighten until something is trimmed; the stable prefix
    # (L0-L3) must survive intact and trimming must start from the tail.
    full = engine.compile_prompt(ctx, case.system_text, case.user_template, case.retrievals)
    full_prefix = _stable_prefix(full.layers)
    tight_budget = max(1, full.total_token_cost // 2)
    tight = engine.compile_prompt(
        ctx, case.system_text, case.user_template, case.retrievals, budget=tight_budget
    )
    tight_prefix = _stable_prefix(tight.layers)
    budget_ok = tight_prefix == full_prefix and tight.total_token_cost <= full.total_token_cost
    if full.total_token_cost and tight.total_token_cost < full.total_token_cost:
        # Something was actually trimmed: L5 must go before L4 is reduced.
        l5_full = full.layers.get(PromptLayer.L5_OBSERVATION, "")
        l5_tight = tight.layers.get(PromptLayer.L5_OBSERVATION, "")
        budget_ok = budget_ok and len(l5_tight) <= len(l5_full)
    if not repeat_ok:
        detail = "repeat: renders differ across identical compiles"
    elif not shuffle_ok:
        detail = "shuffle: recall order changed the rendered prompt"
    elif not dedup_ok:
        detail = "dedup: duplicated items changed the rendered prompt"
    elif not budget_ok:
        detail = "budget: tightening changed the stable prefix or trimmed head-first"

    return StabilityRow(
        agent=case.name,
        repeat_ok=repeat_ok,
        shuffle_ok=shuffle_ok,
        dedup_ok=dedup_ok,
        budget_ok=budget_ok,
        detail=detail,
    )


def run_baseline(
    prompt_dir: Path | str = DEFAULT_PROMPT_DIR,
    *,
    budget: int | None = None,
    repeats: int = 3,
    niche: str = "母婴",
    stress: bool = False,
    cases: Iterable[AgentCase] | None = None,
) -> BaselineReport:
    """Run both axes over every agent prompt (offline, deterministic).

    ``stress=True`` feeds duplicated recall + a long observation tail, which
    is where dedup and the L5-first budget allocator pay off.
    """
    engine = ContextCompiler()
    resolved = (
        tuple(cases)
        if cases is not None
        else load_agent_cases(prompt_dir, niche=niche, stress=stress)
    )
    costs = tuple(measure_cost(case, engine, budget=budget, niche=niche) for case in resolved)
    stability = tuple(
        measure_stability(case, engine, repeats=repeats, budget=budget, niche=niche)
        for case in resolved
    )
    return BaselineReport(
        budget=budget,
        costs=costs,
        stability=stability,
        scenario="stress" if stress else "default",
    )
