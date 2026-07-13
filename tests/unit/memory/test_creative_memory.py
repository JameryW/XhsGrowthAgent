"""Unit tests for CreativeMemory — style merging, soft-downgrade, cold start, fallback."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.db import creative_memory as cm_db
from backend.memory.creative import (
    DOWNGRADE_FACTOR,
    CreativeMemory,
)
from backend.memory.types import (
    CalibrationPayload,
    ConversionPlay,
    MaterialEntry,
    NicheBenchmark,
    StyleDNA,
)


@pytest.fixture(autouse=True)
def _clear_durable_cm():
    cm_db._reset_memory_store()
    yield
    cm_db._reset_memory_store()


# ── Helpers ──


def _make_store(
    search_results: list[dict] | None = None, get_result: dict | None = None
) -> AsyncMock:
    """Create a mock BaseStore with configurable asearch/aget results."""
    store = AsyncMock()
    if search_results is not None:
        items = []
        for r in search_results:
            item = MagicMock()
            item.value = r
            item.key = r.get("style_id", r.get("play_id", r.get("material_id", "key")))
            items.append(item)
        store.asearch = AsyncMock(return_value=items)
    # aget returns a single item or None
    if get_result is not None:
        item = MagicMock()
        item.value = get_result
        item.key = get_result.get(
            "style_id", get_result.get("play_id", get_result.get("material_id", "key"))
        )
        store.aget = AsyncMock(return_value=item)
    else:
        store.aget = AsyncMock(return_value=None)
    store.aput = AsyncMock()
    return store


def _sample_style(
    tone: str = "治愈",
    visual: str = "温暖治愈",
    rate: float = 0.05,
    n: int = 3,
) -> StyleDNA:
    return StyleDNA(
        style_id=f"style_{tone}",
        tone=tone,
        voice_patterns=["你有没有发现..."],
        visual_style=visual,
        color_palette=["#FFE4E1"],
        layout_preference="拼贴",
        emoji_usage="克制",
        hashtag_style="精准少而美",
        engagement_rate=rate,
        sample_count=n,
        last_used="2026-06-13T00:00:00+00:00",
    )


# ── Cold Start ──


class TestColdStart:
    def test_default_styles_returned_when_no_results(self):
        cm = CreativeMemory("test_acct", store=None)
        defaults = cm._default_styles()
        assert len(defaults) == 3
        assert all("tone" in s for s in defaults)
        assert all(s.get("sample_count") == 0 for s in defaults)

    @pytest.mark.asyncio
    async def test_recall_style_returns_defaults_when_store_none_and_empty(self):
        cm = CreativeMemory("test_acct_empty", store=None)
        result = await cm.recall_style()
        assert len(result) == 3
        assert result[0]["tone"] == "治愈"

    @pytest.mark.asyncio
    async def test_deposit_and_recall_without_store_uses_durable(self):
        """Import/CLI path: store=None still persists style for next creation."""
        cm = CreativeMemory("durable_acct", store=None)
        style = _sample_style(tone="治愈", visual="温暖治愈", rate=0.12, n=4)
        style["style_id"] = "creator_stats_治愈"
        await cm.deposit_style(style)
        # Simulate next creation session — new CreativeMemory, no store
        cm2 = CreativeMemory("durable_acct", store=None)
        styles = await cm2.recall_style(query="content strategy 母婴")
        assert any(s.get("style_id") == "creator_stats_治愈" for s in styles)
        ctx = cm2.build_creative_context(styles, [], [])
        assert "治愈" in ctx
        assert "风格指纹" in ctx

    @pytest.mark.asyncio
    async def test_recall_plays_returns_empty_when_store_none(self):
        cm = CreativeMemory("test_acct_empty2", store=None)
        result = await cm.recall_plays()
        assert result == []

    @pytest.mark.asyncio
    async def test_recall_materials_returns_empty_when_store_none(self):
        cm = CreativeMemory("test_acct_empty3", store=None)
        result = await cm.recall_materials()
        assert result == []

    @pytest.mark.asyncio
    async def test_recall_benchmark_returns_none_when_store_none(self):
        cm = CreativeMemory("test_acct_empty4", store=None)
        result = await cm.recall_benchmark("母婴")
        assert result is None


# ── Graceful Fallback ──


class TestFallback:
    @pytest.mark.asyncio
    async def test_recall_style_falls_back_on_exception(self):
        store = AsyncMock()
        store.asearch = AsyncMock(side_effect=RuntimeError("store unavailable"))
        cm = CreativeMemory("test_acct", store=store)
        result = await cm.recall_style()
        # Should return defaults, not raise
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_deposit_style_silent_on_exception(self):
        store = AsyncMock()
        store.asearch = AsyncMock(side_effect=RuntimeError("store unavailable"))
        cm = CreativeMemory("test_acct", store=store)
        # Should not raise
        await cm.deposit_style(_sample_style())

    @pytest.mark.asyncio
    async def test_deposit_play_silent_on_exception(self):
        store = AsyncMock()
        store.aput = AsyncMock(side_effect=RuntimeError("store unavailable"))
        cm = CreativeMemory("test_acct", store=store)
        await cm.deposit_play(ConversionPlay(play_id="p1", trigger_condition="test"))

    @pytest.mark.asyncio
    async def test_deposit_material_silent_on_exception(self):
        store = AsyncMock()
        store.aput = AsyncMock(side_effect=RuntimeError("store unavailable"))
        cm = CreativeMemory("test_acct", store=store)
        await cm.deposit_material(
            MaterialEntry(material_id="m1", category="标题模板", content="test")
        )


# ── Style Merging ──


class TestStyleMerging:
    def test_merge_averages_engagement_rate(self):
        old = _sample_style(rate=0.05, n=10)
        new = _sample_style(rate=0.07, n=5)
        merged = CreativeMemory._merge_style(old, new)
        # (0.05*10 + 0.07*5) / 15 = 0.05667
        assert abs(merged["engagement_rate"] - 0.0567) < 0.001
        assert merged["sample_count"] == 15

    def test_merge_deduplicates_voice_patterns(self):
        old = _sample_style()
        old["voice_patterns"] = ["你有没有发现...", "今天分享..."]
        new = _sample_style()
        new["voice_patterns"] = ["今天分享...", "姐妹们看这里"]
        merged = CreativeMemory._merge_style(old, new)
        assert "你有没有发现..." in merged["voice_patterns"]
        assert "今天分享..." in merged["voice_patterns"]
        assert "姐妹们看这里" in merged["voice_patterns"]
        # No duplicates
        assert len(merged["voice_patterns"]) == len(set(merged["voice_patterns"]))

    def test_merge_deduplicates_color_palette(self):
        old = _sample_style()
        old["color_palette"] = ["#FFE4E1", "#FFDAB9"]
        new = _sample_style()
        new["color_palette"] = ["#FFDAB9", "#FFFACD"]
        merged = CreativeMemory._merge_style(old, new)
        assert merged["color_palette"] == ["#FFE4E1", "#FFDAB9", "#FFFACD"]

    def test_merge_preserves_style_id(self):
        old = _sample_style()
        old["style_id"] = "existing_id"
        new = _sample_style()
        merged = CreativeMemory._merge_style(old, new)
        assert merged["style_id"] == "existing_id"

    @pytest.mark.asyncio
    async def test_deposit_style_merges_when_similar_exists(self):
        existing = _sample_style(tone="治愈", visual="温暖治愈")
        store = _make_store(search_results=[existing])
        cm = CreativeMemory("test_acct", store=store)
        new = _sample_style(tone="治愈", visual="温暖治愈", rate=0.08, n=2)
        await cm.deposit_style(new)
        # aput should be called with merged result
        store.aput.assert_called_once()
        call_args = store.aput.call_args
        merged = call_args[1]["value"]
        assert merged["sample_count"] == 5  # 3 + 2
        assert merged["engagement_rate"] > 0.05

    @pytest.mark.asyncio
    async def test_deposit_style_creates_new_when_no_similar(self):
        store = _make_store(search_results=[])
        cm = CreativeMemory("test_acct", store=store)
        await cm.deposit_style(_sample_style())
        store.aput.assert_called_once()

    @pytest.mark.asyncio
    async def test_concurrent_deposits_merge_one_style_identity(self):
        """The process lock prevents a concurrent read/merge/write lost update."""
        first = CreativeMemory("concurrent_acct", store=None)
        second = CreativeMemory("concurrent_acct", store=None)
        await asyncio.gather(
            first.deposit_style(_sample_style(rate=0.05, n=3)),
            second.deposit_style(_sample_style(rate=0.08, n=2)),
        )

        styles = await CreativeMemory("concurrent_acct", store=None).recall_style()
        real_styles = [style for style in styles if not style["style_id"].startswith("default_")]
        assert len(real_styles) == 1
        assert real_styles[0]["sample_count"] == 5


class TestDurableStyleMerge:
    @pytest.mark.asyncio
    async def test_style_merge_transaction_uses_postgres_advisory_lock(self):
        """The DB path serializes a tone/visual merge across worker processes."""

        class _AsyncContext:
            def __init__(self, value):
                self.value = value

            async def __aenter__(self):
                return self.value

            async def __aexit__(self, *args):
                return False

        connection = MagicMock()
        connection.execute = AsyncMock()
        connection.transaction.return_value = _AsyncContext(None)
        pool = MagicMock()
        pool.connection.return_value = _AsyncContext(connection)

        with (
            patch("backend.db.creative_memory.is_pool_ready", return_value=True),
            patch("backend.db.creative_memory.get_pool", return_value=pool),
        ):
            async with cm_db.style_merge_transaction("acct", "治愈", "温暖") as conn:
                assert conn is connection

        connection.execute.assert_awaited_once_with(
            "SELECT pg_advisory_xact_lock(hashtext(%s), hashtext(%s))",
            ("acct", "治愈\x1f温暖"),
        )


# ── Material Vault Soft Downgrade ──


class TestSoftDowngrade:
    @pytest.mark.asyncio
    async def test_calibrate_downgrades_low_effectiveness_material(self):
        material = MaterialEntry(
            material_id="m1",
            category="标题模板",
            content="test",
            effectiveness=0.5,
            weight=1.0,
            reuse_count=0,
        )
        store = _make_store(get_result=material)
        cm = CreativeMemory("test_acct", store=store)

        payload = CalibrationPayload(
            account_id="test_acct",
            niche="母婴",
            style_id="",
            actual_engagement_rate=0.02,
            actual_save_rate=0.01,
            play_id="",
            play_success=False,
            material_ids=["m1"],
            material_effectiveness={"m1": 0.2},  # Below threshold
            post_id="p1",
        )
        await cm.calibrate(payload)

        # Check that aput was called with downgraded weight
        aput_calls = store.aput.call_args_list
        vault_calls = [c for c in aput_calls if c[0][0] == cm.vault_ns]
        assert len(vault_calls) == 1
        updated = vault_calls[0][1]["value"]
        assert updated["weight"] == round(1.0 * DOWNGRADE_FACTOR, 4)
        assert updated["effectiveness"] == 0.2
        assert updated["reuse_count"] == 1

    @pytest.mark.asyncio
    async def test_calibrate_does_not_downgrade_high_effectiveness(self):
        material = MaterialEntry(
            material_id="m1",
            category="标题模板",
            content="test",
            effectiveness=0.5,
            weight=0.8,
            reuse_count=2,
        )
        store = _make_store(get_result=material)
        cm = CreativeMemory("test_acct", store=store)

        payload = CalibrationPayload(
            account_id="test_acct",
            niche="母婴",
            style_id="",
            actual_engagement_rate=0.05,
            actual_save_rate=0.03,
            play_id="",
            play_success=True,
            material_ids=["m1"],
            material_effectiveness={"m1": 0.6},  # Above threshold
            post_id="p1",
        )
        await cm.calibrate(payload)

        aput_calls = store.aput.call_args_list
        vault_calls = [c for c in aput_calls if c[0][0] == cm.vault_ns]
        assert len(vault_calls) == 1
        updated = vault_calls[0][1]["value"]
        assert updated["weight"] == 0.8  # Unchanged


# ── Conversion Playbook ──


class TestConversionPlaybook:
    @pytest.mark.asyncio
    async def test_deposit_play_sets_defaults(self):
        store = _make_store(search_results=[])
        cm = CreativeMemory("test_acct", store=store)
        await cm.deposit_play(
            ConversionPlay(
                play_id="p1",
                trigger_condition="新品首发",
            )
        )
        store.aput.assert_called_once()
        value = store.aput.call_args[1]["value"]
        assert value["proven_count"] == 0
        assert "last_proven" in value

    @pytest.mark.asyncio
    async def test_calibrate_increments_proven_count(self):
        play = ConversionPlay(
            play_id="p1",
            trigger_condition="新品首发",
            proven_count=2,
        )
        store = _make_store(get_result=play)
        cm = CreativeMemory("test_acct", store=store)

        payload = CalibrationPayload(
            account_id="test_acct",
            niche="母婴",
            style_id="",
            actual_engagement_rate=0.05,
            actual_save_rate=0.03,
            play_id="p1",
            play_success=True,
            material_ids=[],
            material_effectiveness={},
            post_id="p1",
        )
        await cm.calibrate(payload)

        aput_calls = store.aput.call_args_list
        play_calls = [c for c in aput_calls if c[0][0] == cm.playbook_ns]
        assert len(play_calls) == 1
        updated = play_calls[0][1]["value"]
        assert updated["proven_count"] == 3


# ── Build Creative Context ──


class TestBuildCreativeContext:
    def test_empty_inputs_return_empty_string(self):
        cm = CreativeMemory("test_acct")
        assert cm.build_creative_context([], [], []) == ""

    def test_styles_rendered(self):
        cm = CreativeMemory("test_acct")
        styles = [_sample_style()]
        ctx = cm.build_creative_context(styles, [], [])
        assert "风格指纹" in ctx
        assert "治愈" in ctx
        assert "温暖治愈" in ctx

    def test_plays_rendered(self):
        cm = CreativeMemory("test_acct")
        plays = [
            ConversionPlay(
                play_id="p1",
                trigger_condition="新品首发",
                title_formula="数字+痛点",
                proven_count=3,
            )
        ]
        ctx = cm.build_creative_context([], plays, [])
        assert "转化策略" in ctx
        assert "新品首发" in ctx

    def test_materials_rendered(self):
        cm = CreativeMemory("test_acct")
        materials = [
            MaterialEntry(
                material_id="m1",
                category="标题模板",
                content="5个方法让你的家变美",
                effectiveness=0.8,
            )
        ]
        ctx = cm.build_creative_context([], [], materials)
        assert "优质素材" in ctx
        assert "标题模板" in ctx

    def test_benchmark_rendered(self):
        cm = CreativeMemory("test_acct")
        benchmark = NicheBenchmark(
            niche="母婴",
            trending_formulas=["数字+痛点", "对比+种草"],
            peak_posting_hours=[8, 12, 20],
            top_styles=[{"style_name": "温暖治愈"}],
        )
        ctx = cm.build_creative_context([], [], [], benchmark)
        assert "行业基准" in ctx
        assert "热门标题公式" in ctx


# ── Namespace ──


class TestNamespaces:
    def test_style_dna_ns(self):
        cm = CreativeMemory("acct1")
        assert cm.style_dna_ns == ("accounts", "acct1", "style_dna")

    def test_playbook_ns(self):
        cm = CreativeMemory("acct1")
        assert cm.playbook_ns == ("accounts", "acct1", "conversion_playbook")

    def test_vault_ns(self):
        cm = CreativeMemory("acct1")
        assert cm.vault_ns == ("accounts", "acct1", "material_vault")

    def test_benchmark_ns(self):
        assert CreativeMemory.benchmark_ns("母婴") == ("benchmarks", "母婴")


class TestCalibrateStats:
    """calibrate() returns update stats dict."""

    @pytest.mark.asyncio
    async def test_returns_zero_stats_when_no_store(self):
        cm = CreativeMemory("test", store=None)
        payload = CalibrationPayload(account_id="test")
        stats = await cm.calibrate(payload)
        assert stats == {"styles": 0, "plays": 0, "materials": 0}

    @pytest.mark.asyncio
    async def test_returns_stats_on_style_update(self):
        style = StyleDNA(style_id="s1", tone="治愈", sample_count=1, engagement_rate=0.05)
        store = _make_store(get_result=style)
        cm = CreativeMemory("test_acct", store=store)
        payload = CalibrationPayload(
            account_id="test_acct",
            style_id="s1",
            actual_engagement_rate=0.08,
            actual_save_rate=0.02,
        )
        stats = await cm.calibrate(payload)
        assert stats["styles"] == 1
        assert stats["plays"] == 0
        assert stats["materials"] == 0


# ── Keyword Recall ──


class TestKeywordRecall:
    """Tests for keyword-filtered recall in CreativeMemory."""

    @pytest.mark.asyncio
    async def test_recall_style_with_keywords(self):
        """recall_style filters by keywords."""
        s1 = _sample_style(tone="治愈", visual="温暖治愈")
        s2 = _sample_style(tone="专业", visual="现代简约")
        store = _make_store(search_results=[s1, s2])
        cm = CreativeMemory("test_acct", store=store)

        result = await cm.recall_style(query="style", keywords=["治愈"])
        assert len(result) == 1
        assert result[0]["tone"] == "治愈"

    @pytest.mark.asyncio
    async def test_recall_style_with_filter(self):
        """recall_style passes filter to asearch."""
        s1 = _sample_style(tone="治愈")
        store = _make_store(search_results=[s1])
        cm = CreativeMemory("test_acct", store=store)

        await cm.recall_style(query="style", filter={"tone": "治愈"})
        call = store.asearch.call_args
        assert call.kwargs.get("filter") == {"tone": "治愈"}

    @pytest.mark.asyncio
    async def test_recall_plays_with_keywords(self):
        """recall_plays filters by keywords."""
        p1 = ConversionPlay(play_id="p1", trigger_condition="新品首发", niche="母婴")
        p2 = ConversionPlay(play_id="p2", trigger_condition="节日促销", niche="美妆")
        store = _make_store(search_results=[p1, p2])
        cm = CreativeMemory("test_acct", store=store)

        result = await cm.recall_plays(keywords=["母婴"])
        assert len(result) == 1
        assert result[0]["trigger_condition"] == "新品首发"

    @pytest.mark.asyncio
    async def test_recall_materials_with_keywords(self):
        """recall_materials filters by keywords."""
        m1 = MaterialEntry(material_id="m1", category="标题模板", content="护肤秘籍")
        m2 = MaterialEntry(material_id="m2", category="封面", content="穿搭灵感", weight=1.2)
        store = _make_store(search_results=[m1, m2])
        cm = CreativeMemory("test_acct", store=store)

        result = await cm.recall_materials(keywords=["护肤"])
        assert len(result) == 1
        assert "护肤" in result[0]["content"]

    @pytest.mark.asyncio
    async def test_recall_no_keywords_returns_all(self):
        """recall without keywords returns all results (no filtering)."""
        s1 = _sample_style(tone="治愈")
        s2 = _sample_style(tone="专业")
        store = _make_store(search_results=[s1, s2])
        cm = CreativeMemory("test_acct", store=store)

        result = await cm.recall_style(query="style", limit=3)
        assert len(result) == 2
