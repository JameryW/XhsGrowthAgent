"""Pipeline skeleton tests: dedup, rerank, budget trim, layered compile."""

from datetime import UTC, datetime

from backend.context.compiler import ContextCompiler, dedup_items, rerank_items
from backend.context.models import (
    ContextItem,
    PromptLayer,
    RetrievalMode,
    RetrievalResult,
    RunContext,
)


def _item(
    body: str,
    source: str = "memory:performance_insights",
    *,
    priority: int = 0,
    confidence: float = 1.0,
    timestamp: datetime | None = None,
) -> ContextItem:
    return ContextItem(
        body=body,
        source=source,
        priority=priority,
        confidence=confidence,
        timestamp=timestamp,
    )


def _run_context() -> RunContext:
    return RunContext(thread_id="t", account_id="acc", niche="母婴")


def test_dedup_keeps_first_occurrence_and_order() -> None:
    items = (
        _item("甲"),
        _item("乙", source="memory:audience_preferences"),
        _item("甲"),  # same source+body as first → dropped
        _item("丙"),
    )
    assert [item.body for item in dedup_items(items)] == ["甲", "乙", "丙"]


def test_rerank_orders_by_priority_then_confidence_then_recency() -> None:
    ts_old = datetime(2026, 9, 1, tzinfo=UTC)
    ts_new = datetime(2026, 9, 14, tzinfo=UTC)
    items = (
        _item("低优先级", priority=0),
        _item("高优先级", priority=5),
        _item("同优先级更新", priority=2, timestamp=ts_new),
        _item("同优先级更旧", priority=2, timestamp=ts_old),
        _item("同优先级无时间", priority=2),
    )
    ranked = rerank_items(items)
    assert [item.body for item in ranked] == [
        "高优先级",
        "同优先级更新",
        "同优先级更旧",
        "同优先级无时间",
        "低优先级",
    ]


def test_rerank_source_weights_scale_confidence() -> None:
    items = (
        _item("无权重命中", confidence=0.8),
        _item("有权重命中", source="memory:strategy_notes", confidence=0.5),
    )
    ranked = rerank_items(items, source_weights={"memory:strategy_notes": 3.0})
    assert ranked[0].body == "有权重命中"
    # Stable sort without weights: first recall order preserved on tie.
    assert [item.body for item in rerank_items(items)] == ["无权重命中", "有权重命中"]


def test_compile_joins_sections_and_items_in_layer_order() -> None:
    compiler = ContextCompiler()
    prompt = compiler.compile(
        _run_context(),
        sections={
            PromptLayer.L0_SYSTEM: "你是小红书运营专家",
            PromptLayer.L3_TASK: "输出 JSON 趋势报告",
        },
        retrievals=(
            RetrievalResult(
                namespace="performance_insights",
                layer=PromptLayer.L4_MEMORY,
                items=(_item("历史洞察甲", source="memory:performance_insights"),),
                mode=RetrievalMode.HIT,
            ),
            RetrievalResult(
                namespace="workflow",
                layer=PromptLayer.L5_OBSERVATION,
                items=(_item("实时数据块", source="tool:xhs"),),
                mode=RetrievalMode.HIT,
            ),
        ),
    )
    assert prompt.render().split("\n\n") == [
        "你是小红书运营专家",
        "输出 JSON 趋势报告",
        "历史洞察甲",
        "实时数据块",
    ]
    assert prompt.total_token_cost > 0


def test_compile_dedups_across_retrievals_of_same_layer() -> None:
    compiler = ContextCompiler()
    duplicate = _item("重复洞察", source="memory:performance_insights")
    prompt = compiler.compile(
        _run_context(),
        sections={},
        retrievals=(
            RetrievalResult(
                namespace="performance_insights",
                items=(duplicate,),
                mode=RetrievalMode.HIT,
            ),
            RetrievalResult(
                namespace="performance_insights",
                items=(_item("重复洞察", source="memory:performance_insights"),),
                mode=RetrievalMode.HIT,
            ),
        ),
    )
    assert prompt.layers[PromptLayer.L4_MEMORY].count("重复洞察") == 1


def test_budget_trims_l5_before_l4_and_never_static_layers() -> None:
    compiler = ContextCompiler()
    long_l5 = _item("五" * 40, source="tool:xhs", priority=0)  # ≈40 tokens
    short_l5 = _item("五" * 5, source="tool:xhs", priority=9)  # ≈5 tokens
    l4 = _item("四" * 5, source="memory:performance_insights", priority=1)  # ≈5 tokens
    prompt = compiler.compile(
        _run_context(),
        sections={PromptLayer.L0_SYSTEM: "零" * 10},  # 10 tokens, reserved
        retrievals=(
            RetrievalResult(
                namespace="workflow",
                layer=PromptLayer.L5_OBSERVATION,
                items=(long_l5, short_l5),
                mode=RetrievalMode.HIT,
            ),
            RetrievalResult(
                namespace="performance_insights",
                layer=PromptLayer.L4_MEMORY,
                items=(l4,),
                mode=RetrievalMode.HIT,
            ),
        ),
        budget=18,
    )
    # Reserved L0 = 10 → item allowance 8.  L5 (45) drops lowest-priority
    # first ("五"*40 → 10 > 8 → "五"*5 → 5 ≤ 8); L4 (5) survives whole; the
    # static L0 layer is never trimmed.
    assert PromptLayer.L5_OBSERVATION not in prompt.layers
    assert prompt.layers[PromptLayer.L4_MEMORY] == "四" * 5
    assert prompt.layers[PromptLayer.L0_SYSTEM] == "零" * 10
    assert prompt.total_token_cost == 16  # includes layer separator
    assert prompt.total_token_cost <= 18


def test_no_budget_keeps_everything() -> None:
    compiler = ContextCompiler()
    items = (_item("甲" * 100),)
    prompt = compiler.compile(
        _run_context(),
        sections={},
        retrievals=(
            RetrievalResult(
                namespace="performance_insights",
                items=items,
                mode=RetrievalMode.HIT,
            ),
        ),
    )
    assert "甲" * 100 in prompt.layers[PromptLayer.L4_MEMORY]


def test_degraded_retrieval_items_still_compile_in_s1() -> None:
    """Mode is observability metadata; S1 assembly keeps partial items."""
    compiler = ContextCompiler()
    prompt = compiler.compile(
        _run_context(),
        sections={},
        retrievals=(
            RetrievalResult(
                namespace="performance_insights",
                items=(_item("部分数据"),),
                mode=RetrievalMode.DEGRADED,
                error="search timeout",
            ),
        ),
    )
    assert "部分数据" in prompt.layers[PromptLayer.L4_MEMORY]
