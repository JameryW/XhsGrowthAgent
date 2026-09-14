"""Contract tests for the P1b-S5 acceptance baseline.

The baseline is a CI gate, so it needs tests of its own: it must load real
agent prompts, produce sane token numbers, hold the stability invariants —
and (negative cases) actually *fail* when an invariant is broken. A gate
that can only ever be green is worthless.
"""

from datetime import UTC, datetime

from backend.context.baseline import (
    DEFAULT_PROMPT_DIR,
    AgentCase,
    load_agent_cases,
    measure_cost,
    measure_stability,
    run_baseline,
    synthetic_retrievals,
)
from backend.context.models import ContextItem, PromptLayer, RetrievalMode, RetrievalResult


def _case_from_bodies(bodies: tuple[str, ...], **item_kwargs) -> AgentCase:
    """Minimal single-namespace case; items share one namespace/layer."""
    base = datetime(2026, 9, 14, tzinfo=UTC)
    items = tuple(
        ContextItem(
            body=body,
            source="content_history",
            timestamp=base.replace(minute=index),
            confidence=0.9 - index * 0.1,
            **(item_kwargs or {}),
        )
        for index, body in enumerate(bodies)
    )
    retrieval = RetrievalResult(
        namespace="content_history",
        layer=PromptLayer.L4_MEMORY,
        items=items,
        mode=RetrievalMode.HIT,
    )
    return AgentCase(name="synthetic", system_text="你是内容助手。", retrievals=(retrieval,))


class TestLoadAgentCases:
    def test_loads_real_prompt_yamls(self):
        cases = load_agent_cases(DEFAULT_PROMPT_DIR)
        names = {case.name for case in cases}
        # The migrated agents must all be covered by the gate.
        for expected in ("copywriter", "trend_scout", "analyst", "evaluator"):
            assert expected in names
        assert len(cases) >= 10

    def test_every_case_has_recall(self):
        cases = load_agent_cases(DEFAULT_PROMPT_DIR)
        assert all(case.retrievals for case in cases)

    def test_stress_adds_duplicates_and_tail(self):
        base = synthetic_retrievals(niche="母婴")
        stress = synthetic_retrievals(niche="母婴", stress=True)
        base_bodies = [item.body for r in base for item in r.items]
        stress_bodies = [item.body for r in stress for item in r.items]
        assert len(stress_bodies) > len(base_bodies)
        assert len(set(stress_bodies)) < len(stress_bodies)  # duplicates present


class TestCost:
    def test_cost_is_positive_and_layered(self):
        case = load_agent_cases(DEFAULT_PROMPT_DIR)[0]
        row = measure_cost(case)
        assert row.baseline_tokens > 0
        assert row.compiled_tokens > 0
        assert row.layer_tokens
        assert row.delta == row.compiled_tokens - row.baseline_tokens

    def test_stress_saves_tokens_via_dedup(self):
        """Duplicated recall: the compiler must not pay for it twice."""
        cases = load_agent_cases(DEFAULT_PROMPT_DIR, stress=True)
        rows = [measure_cost(case) for case in cases]
        saved = [row for row in rows if row.delta < 0]
        assert len(saved) == len(rows), "every agent must save tokens under stress"

    def test_clean_recall_costs_essentially_the_same(self):
        """No duplicates ⇒ dedup has nothing to remove; only join overhead."""
        cases = load_agent_cases(DEFAULT_PROMPT_DIR)
        for case in cases:
            row = measure_cost(case)
            assert abs(row.pct) < 2.0, f"{case.name}: unexpected {row.pct:.1f}% delta"

    def test_budget_trims_from_the_tail(self):
        case = _case_from_bodies(("一" * 400, "二" * 400, "三" * 400))
        tight = measure_cost(case, budget=120)
        assert tight.compiled_tokens < measure_cost(case).compiled_tokens
        assert PromptLayer.L0_SYSTEM.value in tight.layer_tokens


class TestStability:
    def test_invariants_hold_for_real_prompts(self):
        for case in load_agent_cases(DEFAULT_PROMPT_DIR):
            row = measure_stability(case)
            assert row.ok, f"{case.name}: {row.detail}"

    def test_invariants_hold_under_stress(self):
        for case in load_agent_cases(DEFAULT_PROMPT_DIR, stress=True):
            row = measure_stability(case)
            assert row.ok, f"{case.name}: {row.detail}"

    def test_negative_shuffle_instability_is_detected(self):
        """Two items with an identical sort key: reversing recall order must
        flip them — the gate has to catch that, not rubber-stamp it."""
        base = datetime(2026, 9, 14, tzinfo=UTC)
        items = tuple(
            ContextItem(
                body=body,
                source="content_history",
                timestamp=base,
                confidence=0.5,  # identical key ⇒ stable sort keeps input order
            )
            for body in ("AAA", "BBB")
        )
        case = AgentCase(
            name="unstable",
            system_text="你是内容助手。",
            retrievals=(
                RetrievalResult(
                    namespace="content_history",
                    layer=PromptLayer.L4_MEMORY,
                    items=items,
                    mode=RetrievalMode.HIT,
                ),
            ),
        )
        row = measure_stability(case)
        assert not row.shuffle_ok
        assert not row.ok
        assert "shuffle" in row.detail

    def test_dedup_keys_on_source_and_body(self):
        """Dedup is keyed on ``(source, body)``: the same body recalled from
        two different namespaces is NOT a duplicate and must both survive."""
        from backend.context.compiler import ContextCompiler
        from backend.context.models import RunContext

        base = datetime(2026, 9, 14, tzinfo=UTC)
        items = tuple(
            ContextItem(body="同一条内容", source=source, timestamp=base, confidence=0.5)
            for source in ("content_history", "audience_preferences")
        )
        case = AgentCase(
            name="cross-source",
            system_text="你是内容助手。",
            retrievals=(
                RetrievalResult(
                    namespace="mixed",
                    layer=PromptLayer.L4_MEMORY,
                    items=items,
                    mode=RetrievalMode.HIT,
                ),
            ),
        )
        ctx = RunContext(thread_id="t", account_id="a", niche="母婴")
        rendered = (
            ContextCompiler().compile_prompt(ctx, case.system_text, "", case.retrievals).render()
        )
        assert rendered.count("同一条内容") == 2

        # Same source + same body IS a duplicate: dedup keeps one.
        dup = RetrievalResult(
            namespace="content_history",
            layer=PromptLayer.L4_MEMORY,
            items=(items[0], items[0]),
            mode=RetrievalMode.HIT,
        )
        rendered_dup = ContextCompiler().compile_prompt(ctx, case.system_text, "", (dup,)).render()
        assert rendered_dup.count("同一条内容") == 1


class TestReport:
    def test_run_baseline_default_is_ok(self):
        report = run_baseline(DEFAULT_PROMPT_DIR)
        assert report.scenario == "default"
        assert report.ok
        assert report.total_baseline > 0
        assert report.total_compiled > 0
        payload = report.to_dict()
        assert payload["ok"] is True
        assert len(payload["costs"]) == len(report.costs)

    def test_run_baseline_stress_saves_tokens(self):
        base_report = run_baseline(DEFAULT_PROMPT_DIR)
        stress_report = run_baseline(DEFAULT_PROMPT_DIR, stress=True)
        assert stress_report.scenario == "stress"
        assert stress_report.ok
        assert stress_report.total_compiled - stress_report.total_baseline < 0
        # Stress feeds strictly more raw context than the clean scenario.
        assert stress_report.total_baseline > base_report.total_baseline

    def test_run_baseline_with_budget(self):
        report = run_baseline(DEFAULT_PROMPT_DIR, budget=500, stress=True)
        assert report.ok
        assert report.budget == 500
        assert report.total_compiled < run_baseline(DEFAULT_PROMPT_DIR, stress=True).total_compiled
