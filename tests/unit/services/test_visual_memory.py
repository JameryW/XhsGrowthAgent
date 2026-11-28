"""Account visual memory (ledger #45): anchor freezing, drift and feedback."""

from __future__ import annotations

from typing import Any

import pytest

from backend.services.visual_memory import (
    VISUAL_MEMORY_ENV,
    apply_directive,
    build_directive,
    directive_prompt,
    ensure_dna,
    feedback_score,
    load_bank,
    load_dna,
    load_scenes,
    record_scene_feedback,
    record_scene_feedback_if_enabled,
    scene_for,
    visual_memory_enabled,
)


class _Item:
    def __init__(self, value: Any) -> None:
        self.value = value


class FakeStore:
    def __init__(self) -> None:
        self.data: dict[tuple[tuple[str, ...], str], dict[str, Any]] = {}
        self.writes = 0

    async def aget(self, namespace: Any, key: str) -> _Item | None:
        value = self.data.get((tuple(namespace), key))
        return _Item(value) if value is not None else None

    async def aput(self, namespace: Any, key: str, value: dict[str, Any]) -> None:
        self.writes += 1
        self.data[(tuple(namespace), key)] = value


class BrokenStore:
    async def aget(self, namespace: Any, key: str) -> Any:
        raise RuntimeError("store down")

    async def aput(self, namespace: Any, key: str, value: Any) -> None:
        raise RuntimeError("store down")


class TestSwitch:
    def test_defaults_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(VISUAL_MEMORY_ENV, raising=False)
        assert visual_memory_enabled() is False

    @pytest.mark.parametrize("value", ["1", "true", "yes", "on", " ON "])
    def test_truthy(self, monkeypatch: pytest.MonkeyPatch, value: str) -> None:
        monkeypatch.setenv(VISUAL_MEMORY_ENV, value)
        assert visual_memory_enabled() is True

    def test_other_values_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(VISUAL_MEMORY_ENV, "0")
        assert visual_memory_enabled() is False


class TestSceneFor:
    def test_travel_niche(self) -> None:
        assert scene_for(niche="川西自驾旅行") == "travel"

    def test_food_niche(self) -> None:
        assert scene_for(niche="城市美食探店") == "food"

    def test_content_type_fallback(self) -> None:
        assert scene_for(niche="", content_type="OOTD 穿搭") == "outfit"

    def test_unknown_niche_is_lifestyle(self) -> None:
        assert scene_for(niche="冷门赛道") == "lifestyle"

    def test_reads_and_writes_agree(self) -> None:
        # The same helper is the only scene resolver, so a write path and a read
        # path can never land on different scenes for the same niche.
        assert scene_for(niche="健身减脂") == scene_for(niche="健身减脂")


class TestDna:
    @pytest.mark.asyncio
    async def test_first_run_freezes_anchors(self) -> None:
        store = FakeStore()
        dna, created = await ensure_dna(
            store,
            "acc",
            palette=["#F5E6D3", "#2B2B2B", "#D94F3D"],
            title_weight_ratio=1.8,
            subject_tokens=["车队实拍"],
            negative_tokens=["荧光绿"],
        )
        assert created is True
        assert dna.primary_color == "#F5E6D3"
        assert dna.title_weight_ratio == pytest.approx(1.8)
        assert dna.subject_tokens == ("车队实拍",)

    @pytest.mark.asyncio
    async def test_second_run_never_overwrites(self) -> None:
        store = FakeStore()
        await ensure_dna(store, "acc", palette=["#111111"], title_weight_ratio=1.8)
        dna, created = await ensure_dna(store, "acc", palette=["#FFFFFF"], title_weight_ratio=1.1)
        assert created is False
        assert dna.primary_color == "#111111"
        assert dna.title_weight_ratio == pytest.approx(1.8)

    @pytest.mark.asyncio
    async def test_dna_persists_across_reads(self) -> None:
        store = FakeStore()
        await ensure_dna(store, "acc", palette=["#123456"])
        loaded = await load_dna(store, "acc")
        assert loaded is not None
        assert loaded.primary_color == "#123456"

    @pytest.mark.asyncio
    async def test_missing_dna_is_none(self) -> None:
        assert await load_dna(FakeStore(), "acc") is None

    @pytest.mark.asyncio
    async def test_broken_store_reads_empty(self) -> None:
        assert await load_dna(BrokenStore(), "acc") is None
        bank = await load_bank(BrokenStore(), "acc")
        assert bank.get_dna("acc").primary_color == "#FFFFFF"


class TestDirective:
    @pytest.mark.asyncio
    async def test_fresh_account_is_not_bootstrapped(self) -> None:
        directive = await build_directive(FakeStore(), "acc", "travel")
        assert directive["bootstrapped"] is False
        assert "路线地图" in "".join(directive["preferred_layouts"])

    @pytest.mark.asyncio
    async def test_anchors_flow_into_directive(self) -> None:
        store = FakeStore()
        await ensure_dna(
            store,
            "acc",
            palette=["#F5E6D3", "#2B2B2B", "#D94F3D"],
            title_weight_ratio=1.8,
            subject_tokens=["车队实拍"],
        )
        directive = await build_directive(store, "acc", "travel")
        assert directive["bootstrapped"] is True
        assert directive["palette"]["primary"] == "#F5E6D3"
        assert directive["subject_tokens"] == ["车队实拍"]

    @pytest.mark.asyncio
    async def test_prompt_names_anchors_only_when_bootstrapped(self) -> None:
        store = FakeStore()
        fresh_prompt = directive_prompt(await build_directive(store, "acc", "travel"))
        assert "首篇视觉方案" in fresh_prompt
        await ensure_dna(store, "acc", palette=["#F5E6D3"])
        frozen_prompt = directive_prompt(await build_directive(store, "acc", "travel"))
        assert "#F5E6D3" in frozen_prompt
        assert "不得更改" in frozen_prompt


class TestApplyDirective:
    def _directive(self, **overrides: Any) -> dict[str, Any]:
        directive: dict[str, Any] = {
            "scene": "travel",
            "scene_weight": 1.0,
            "bootstrapped": True,
            "palette": {"primary": "#F5E6D3", "secondary": "#2B2B2B", "accent": "#D94F3D"},
            "title_weight_ratio": 1.8,
            "preferred_layouts": ["路线地图 + 实景拼图 + 费用清单"],
            "subject_tokens": ["车队实拍"],
            "negative_tokens": ["荧光绿"],
        }
        directive.update(overrides)
        return directive

    def test_first_run_fills_nothing(self) -> None:
        plan: dict[str, Any] = {"cover_prompt": "cover"}
        report = apply_directive(plan, self._directive(bootstrapped=False))
        assert report["filled"] == []
        assert report["drift"] == []
        assert "color_palette" not in plan
        assert plan["visual_memory"]["bootstrapped"] is False

    def test_fills_gaps_from_anchors(self) -> None:
        plan: dict[str, Any] = {"cover_prompt": "cover"}
        report = apply_directive(plan, self._directive())
        assert plan["color_palette"] == ["#F5E6D3", "#2B2B2B", "#D94F3D"]
        assert plan["title_weight_ratio"] == pytest.approx(1.8)
        assert plan["layout_preference"].startswith("路线地图")
        assert set(report["filled"]) == {"color_palette", "title_weight_ratio", "layout_preference"}
        assert report["drift"] == []

    def test_palette_conflict_is_drift_not_rewrite(self) -> None:
        plan: dict[str, Any] = {"color_palette": ["#000000", "#FFFFFF"]}
        report = apply_directive(plan, self._directive())
        assert report["drift"] == ["palette_off_anchor"]
        assert plan["color_palette"] == ["#000000", "#FFFFFF"]

    def test_partial_palette_overlap(self) -> None:
        plan: dict[str, Any] = {"color_palette": ["#F5E6D3", "#999999"]}
        report = apply_directive(plan, self._directive())
        assert report["drift"] == ["palette_partial"]

    def test_title_weight_drift(self) -> None:
        plan: dict[str, Any] = {
            "color_palette": ["#F5E6D3", "#2B2B2B", "#D94F3D"],
            "title_weight_ratio": 1.0,
        }
        report = apply_directive(plan, self._directive())
        assert "title_weight_off_anchor" in report["drift"]
        assert plan["title_weight_ratio"] == pytest.approx(1.0)


class TestFeedbackScore:
    def test_no_baseline_is_zero(self) -> None:
        assert feedback_score(collect_ratio=None, view_ratio=None) == 0.0

    def test_collect_dominates(self) -> None:
        assert feedback_score(collect_ratio=1.2, view_ratio=1.0) == pytest.approx(0.14)

    def test_view_only(self) -> None:
        assert feedback_score(collect_ratio=None, view_ratio=0.8) == pytest.approx(-0.2)

    def test_extremes_are_clipped(self) -> None:
        # collect +1.0 and view -1.0 → (0.7*1 - 0.3*1) / 1.0
        assert feedback_score(collect_ratio=50.0, view_ratio=0.0) == pytest.approx(0.4, abs=1e-6)


class TestRecordFeedback:
    @pytest.mark.asyncio
    async def test_no_baseline_writes_nothing(self) -> None:
        store = FakeStore()
        profile = await record_scene_feedback(
            store, "acc", "travel", collect_ratio=None, view_ratio=None, sample_size=10
        )
        assert profile is None
        assert store.writes == 0

    @pytest.mark.asyncio
    async def test_thin_sample_writes_nothing(self) -> None:
        store = FakeStore()
        profile = await record_scene_feedback(
            store, "acc", "travel", collect_ratio=2.0, view_ratio=1.0, sample_size=2
        )
        assert profile is None
        assert store.writes == 0

    @pytest.mark.asyncio
    async def test_baseline_moves_weight(self) -> None:
        store = FakeStore()
        profile = await record_scene_feedback(
            store, "acc", "travel", collect_ratio=1.2, view_ratio=1.0, sample_size=5
        )
        assert profile is not None
        assert profile.scene == "travel"
        assert profile.weight == pytest.approx(1.014, abs=1e-3)
        scenes = await load_scenes(store, "acc")
        assert scenes["travel"].weight == pytest.approx(1.014, abs=1e-3)

    @pytest.mark.asyncio
    async def test_weight_is_bounded(self) -> None:
        store = FakeStore()
        for _ in range(20):
            profile = await record_scene_feedback(
                store, "acc", "travel", collect_ratio=9.0, view_ratio=1.0, sample_size=5
            )
        assert profile is not None
        assert profile.weight == pytest.approx(2.0)

    @pytest.mark.asyncio
    async def test_switch_off_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(VISUAL_MEMORY_ENV, raising=False)
        store = FakeStore()
        profile = await record_scene_feedback_if_enabled(
            store, "acc", "travel", collect_ratio=2.0, view_ratio=1.0, sample_size=9
        )
        assert profile is None
        assert store.writes == 0
