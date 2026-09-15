"""Contract tests for the P1b-S5 acceptance baseline.

The baseline is a CI gate, so it needs tests of its own: it must load real
agent prompts, produce sane token numbers, hold the stability invariants —
and (negative cases) actually *fail* when an invariant is broken. A gate
that can only ever be green is worthless.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from backend.context.baseline import (
    DEFAULT_PROMPT_DIR,
    AgentCase,
    BaselineReport,
    CostRow,
    Snapshot,
    build_snapshot,
    check_prompt_coverage,
    compare_snapshot,
    load_agent_cases,
    load_recall_samples,
    measure_cost,
    measure_stability,
    run_baseline,
    scan_declared_prompts,
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


def _fake_report(scenario: str, tokens: dict[str, int]) -> BaselineReport:
    return BaselineReport(
        budget=None,
        costs=tuple(
            CostRow(agent=name, baseline_tokens=tok, compiled_tokens=tok, layer_tokens={})
            for name, tok in tokens.items()
        ),
        stability=(),
        scenario=scenario,
    )


class TestRecallSamples:
    def _write(self, tmp_path: Path, payload) -> Path:
        path = tmp_path / "samples.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def test_loads_real_recall(self, tmp_path: Path):
        path = self._write(
            tmp_path,
            [
                {
                    "namespace": "content_history",
                    "layer": "l4_memory",
                    "mode": "hit",
                    "items": [
                        {
                            "body": "- 真实召回条目",
                            "source": "content_history",
                            "timestamp": "2026-09-10T08:00:00Z",
                            "confidence": 0.9,
                        }
                    ],
                }
            ],
        )
        results = load_recall_samples(path)
        assert len(results) == 1
        assert results[0].namespace == "content_history"
        assert results[0].layer is PromptLayer.L4_MEMORY
        assert results[0].mode is RetrievalMode.HIT
        assert results[0].items[0].body == "- 真实召回条目"
        assert results[0].items[0].timestamp is not None

    def test_optional_fields_default(self, tmp_path: Path):
        """A minimal export (body only) must still load: mode defaults to
        hit, layer to L4, timestamp to None."""
        path = self._write(tmp_path, [{"namespace": "ns", "items": [{"body": "x"}]}])
        results = load_recall_samples(path)
        assert results[0].mode is RetrievalMode.HIT
        assert results[0].layer is PromptLayer.L4_MEMORY
        assert results[0].items[0].timestamp is None
        assert results[0].items[0].confidence == 1.0

    def test_rejects_non_list_payload(self, tmp_path: Path):
        path = self._write(tmp_path, {"namespace": "ns"})
        with pytest.raises(ValueError, match="JSON list"):
            load_recall_samples(path)

    def test_rejects_unknown_layer(self, tmp_path: Path):
        path = self._write(tmp_path, [{"namespace": "ns", "layer": "l9_nope", "items": []}])
        with pytest.raises(ValueError):
            load_recall_samples(path)

    def test_duplicates_in_real_recall_are_still_deduped(self, tmp_path: Path):
        """The whole point of feeding real recall: duplicates that actually
        occur in the store must show up as savings, not silently inflate."""
        path = self._write(
            tmp_path,
            [
                {
                    "namespace": "content_history",
                    "items": [
                        {"body": "- 重复条目", "source": "content_history", "confidence": 0.9},
                        {"body": "- 重复条目", "source": "content_history", "confidence": 0.9},
                    ],
                }
            ],
        )
        report = run_baseline(
            DEFAULT_PROMPT_DIR, retrievals=load_recall_samples(path), scenario="samples"
        )
        assert report.scenario == "samples"
        assert report.ok
        assert report.total_compiled < report.total_baseline


class TestPromptCoverage:
    def test_every_declared_prompt_exists(self):
        """A typo'd prompt_file compiles an empty system prompt — the gate
        must catch that, since BaseAgent degrades silently."""
        report = check_prompt_coverage(DEFAULT_PROMPT_DIR)
        assert report.declared, "AST scan found no prompt_file declarations"
        assert report.missing == ()
        assert report.ok

    def test_no_orphan_prompts(self):
        report = check_prompt_coverage(DEFAULT_PROMPT_DIR)
        assert report.orphaned == ()

    def test_coverage_matches_loaded_cases(self):
        """The gate's agent count and the coverage scan must agree —
        otherwise the gate is measuring a different set than it reports."""
        report = check_prompt_coverage(DEFAULT_PROMPT_DIR)
        cases = load_agent_cases(DEFAULT_PROMPT_DIR)
        assert {f"{case.name}.yaml" for case in cases} == set(report.present)

    def test_scan_reads_sources_without_importing(self, tmp_path: Path):
        """AST scan: a module with import-time side effects must still be
        readable (a gate must never execute agent modules)."""
        module = tmp_path / "boom.py"
        module.write_text(
            "raise RuntimeError('importing this must never happen')\n",
            encoding="utf-8",
        )
        agent = tmp_path / "ok.py"
        agent.write_text("class DummyAgent:\n    prompt_file = 'dummy.yaml'\n", encoding="utf-8")
        assert scan_declared_prompts(tmp_path) == ("dummy.yaml",)

    def test_missing_declaration_is_reported(self, tmp_path: Path):
        (tmp_path / "prompts").mkdir()
        (tmp_path / "prompts" / "ghost.yaml").write_text("system: hi\n", encoding="utf-8")
        (tmp_path / "agents").mkdir()
        (tmp_path / "agents" / "a.py").write_text(
            "class A:\n    prompt_file = 'absent.yaml'\n", encoding="utf-8"
        )
        report = check_prompt_coverage(tmp_path / "prompts", tmp_path / "agents")
        assert report.missing == ("absent.yaml",)
        assert report.orphaned == ("ghost.yaml",)
        assert not report.ok


class TestSnapshotDrift:
    def test_snapshot_roundtrip(self):
        snapshot = build_snapshot([_fake_report("default", {"a": 100, "b": 200})])
        restored = Snapshot.from_dict(snapshot.to_dict())
        assert restored.scenarios == snapshot.scenarios
        assert restored.scenarios["default"]["a"] == 100

    def test_no_drift_is_ok(self):
        snapshot = build_snapshot([_fake_report("default", {"a": 100})])
        drift = compare_snapshot([_fake_report("default", {"a": 100})], snapshot)
        assert drift.ok
        assert not drift.breaches

    def test_within_threshold_is_ok(self):
        snapshot = build_snapshot([_fake_report("default", {"a": 100})])
        drift = compare_snapshot([_fake_report("default", {"a": 104})], snapshot, threshold_pct=5.0)
        assert drift.ok
        assert drift.rows[0].pct == pytest.approx(4.0)

    def test_drift_beyond_threshold_fails(self):
        """A prompt that grew must break the gate — not silently ship."""
        snapshot = build_snapshot([_fake_report("default", {"a": 100})])
        drift = compare_snapshot([_fake_report("default", {"a": 150})], snapshot, threshold_pct=5.0)
        assert not drift.ok
        assert len(drift.breaches) == 1
        assert drift.breaches[0].pct == pytest.approx(50.0)

    def test_shrink_beyond_threshold_also_fails(self):
        """Starved context is as much a regression as inflated context."""
        snapshot = build_snapshot([_fake_report("default", {"a": 100})])
        drift = compare_snapshot([_fake_report("default", {"a": 50})], snapshot, threshold_pct=5.0)
        assert not drift.ok
        assert drift.breaches[0].pct == pytest.approx(-50.0)

    def test_missing_agent_is_reported(self):
        snapshot = build_snapshot([_fake_report("default", {"a": 100, "b": 200})])
        drift = compare_snapshot([_fake_report("default", {"a": 100})], snapshot)
        assert not drift.ok
        assert "default:b" in drift.missing

    def test_real_prompts_match_committed_snapshot(self):
        """Guard against a stale snapshot: the committed numbers must still
        describe the current prompts."""
        snapshot_path = (
            Path(DEFAULT_PROMPT_DIR).parents[2]
            / "scripts"
            / "benchmarks"
            / "baseline_snapshot.json"
        )
        if not snapshot_path.exists():
            pytest.skip("no committed snapshot")
        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
        reports = [run_baseline(DEFAULT_PROMPT_DIR), run_baseline(DEFAULT_PROMPT_DIR, stress=True)]
        drift = compare_snapshot(reports, Snapshot.from_dict(payload), threshold_pct=5.0)
        assert drift.ok, [row.to_dict() for row in drift.breaches]
