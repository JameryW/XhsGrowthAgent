"""Pipeline skeleton tests: dedup, rerank, budget trim, layered compile."""

from datetime import UTC, datetime

from backend.context.compiler import (
    TRUST_RERANK_WEIGHTS,
    ContextCompiler,
    dedup_items,
    rerank_items,
)
from backend.context.models import (
    ContextItem,
    PromptLayer,
    RetrievalMode,
    RetrievalResult,
    RunContext,
    TrustClass,
)


def _item(
    body: str,
    source: str = "memory:performance_insights",
    *,
    priority: int = 0,
    confidence: float = 1.0,
    timestamp: datetime | None = None,
    trust_class: TrustClass = TrustClass.UNSPECIFIED,
) -> ContextItem:
    return ContextItem(
        body=body,
        source=source,
        priority=priority,
        confidence=confidence,
        timestamp=timestamp,
        trust_class=trust_class,
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


def test_trust_rerank_weights_are_closed_and_ordered() -> None:
    """Relative order is load-bearing; every TrustClass member is covered."""
    assert set(TRUST_RERANK_WEIGHTS) == set(TrustClass)
    assert (
        TRUST_RERANK_WEIGHTS[TrustClass.INTERNAL_FACT]
        > TRUST_RERANK_WEIGHTS[TrustClass.MEMORY]
        > TRUST_RERANK_WEIGHTS[TrustClass.MODEL_GENERATED]
        > TRUST_RERANK_WEIGHTS[TrustClass.EXTERNAL_DOCUMENT]
        > TRUST_RERANK_WEIGHTS[TrustClass.UNSPECIFIED]
    )
    assert TRUST_RERANK_WEIGHTS[TrustClass.INTERNAL_FACT] == 1.0
    assert TRUST_RERANK_WEIGHTS[TrustClass.MEMORY] == 0.85
    assert TRUST_RERANK_WEIGHTS[TrustClass.MODEL_GENERATED] == 0.7
    assert TRUST_RERANK_WEIGHTS[TrustClass.EXTERNAL_DOCUMENT] == 0.55
    assert TRUST_RERANK_WEIGHTS[TrustClass.UNSPECIFIED] == 0.5


def test_rerank_trust_class_breaks_ties_on_same_priority_confidence_source() -> None:
    """Same priority/confidence/source: internal_fact ranks before external_document."""
    items = (
        _item("外部文档", trust_class=TrustClass.EXTERNAL_DOCUMENT),
        _item("内部事实", trust_class=TrustClass.INTERNAL_FACT),
    )
    ranked = rerank_items(items)
    assert [item.body for item in ranked] == ["内部事实", "外部文档"]


def test_rerank_trust_multiplies_with_source_weights() -> None:
    """effective = confidence * source_weight * trust_weight (stackable)."""
    # Without source weight: external (0.55) loses to memory (0.85).
    # With source_weight=2 on the external item: 1.0*2*0.55=1.10 > 1.0*1*0.85=0.85.
    items = (
        _item("记忆项", source="memory:a", trust_class=TrustClass.MEMORY),
        _item(
            "加权外部",
            source="doc:b",
            trust_class=TrustClass.EXTERNAL_DOCUMENT,
        ),
    )
    assert [item.body for item in rerank_items(items)] == ["记忆项", "加权外部"]
    ranked = rerank_items(items, source_weights={"doc:b": 2.0})
    assert [item.body for item in ranked] == ["加权外部", "记忆项"]


def test_rerank_missing_trust_uses_unspecified_weight() -> None:
    """Default ContextItem.trust_class is UNSPECIFIED; verified does not affect order."""
    items = (
        _item("默认", trust_class=TrustClass.UNSPECIFIED),
        ContextItem(
            body="已验证但未分类",
            source="memory:performance_insights",
            confidence=1.0,
            verified=True,  # 票 5ad: verified is out of scope for ranking
        ),
        _item("内部", trust_class=TrustClass.INTERNAL_FACT),
    )
    ranked = rerank_items(items)
    assert ranked[0].body == "内部"
    # Two unspecified-weight items keep stable recall order.
    assert [item.body for item in ranked[1:]] == ["默认", "已验证但未分类"]


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
    assert prompt.total_token_cost == 15
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


# ── L1 tool schema (P1c-S4) ────────────────────────────────────────────────
#
# The layer is the one static layer the prompt YAML cannot carry: it is
# rendered from the capability registry, so it travels on RunContext and the
# compiler seeds it. Off by default — ``RunContext.tool_schema`` is empty
# unless an agent opts in — which is what keeps every existing prompt and the
# recorded baseline byte-identical.

_L1_TEXT = "[可用能力] 以下能力由运行时（Tool Gateway）执行。\n- xhs.trending — 抓取平台热门趋势"


def test_no_tool_schema_means_no_l1_layer() -> None:
    prompt = ContextCompiler().compile_prompt(_run_context(), "系统提示")
    assert PromptLayer.L1_TOOL_SCHEMA not in prompt.layers
    assert prompt.render() == "系统提示"


def test_the_tool_schema_lands_between_l0_and_l2() -> None:
    """The whole point of the layer is *where* it sits: stable prefix, after
    policy and before the account profile that changes per account."""
    context = RunContext(thread_id="t", account_id="acc", niche="母婴", tool_schema=_L1_TEXT)
    prompt = ContextCompiler().compile_prompt(context, "系统提示\n<!-- ctx:l2_account -->\n账号段")
    assert prompt.layers[PromptLayer.L1_TOOL_SCHEMA] == _L1_TEXT
    rendered = prompt.render()
    assert rendered.index("系统提示") < rendered.index("[可用能力]") < rendered.index("账号段")


def test_l1_is_never_trimmed_by_the_budget() -> None:
    """L0-L3 are static and the allocator only trims L5/L4 (D4'); L1 is a
    static layer, so a budget too small for the prompt must not silently drop
    the schema and leave a prompt that documents none of its capabilities."""
    context = RunContext(thread_id="t", account_id="acc", niche="母婴", tool_schema="能" * 400)
    prompt = ContextCompiler().compile_prompt(
        context,
        "系统提示",
        budget=10,
        retrievals=(
            RetrievalResult(
                namespace="performance_insights",
                items=(_item("召回一"),),
                mode=RetrievalMode.HIT,
            ),
        ),
    )
    assert prompt.layers[PromptLayer.L1_TOOL_SCHEMA] == "能" * 400


def test_a_yaml_segment_and_a_run_context_merge_into_one_l1() -> None:
    """Two producers, one layer: a YAML that carries an L1 segment (hand-
    written prose) and a rendered schema must not overwrite each other —
    whichever order they are read in, both are in the prefix."""
    context = RunContext(thread_id="t", account_id="acc", niche="母婴", tool_schema="来自 registry")
    prompt = ContextCompiler().compile_prompt(
        context, "系统提示\n<!-- ctx:l1_tool_schema -->\n来自 YAML"
    )
    layer = prompt.layers[PromptLayer.L1_TOOL_SCHEMA]
    assert "来自 YAML" in layer
    assert "来自 registry" in layer


def test_seeding_l1_does_not_mutate_the_callers_sections() -> None:
    """``compile`` takes a Mapping it does not own; seeding the layer into the
    caller's dict would leak one run's tool schema into the next."""
    sections = {PromptLayer.L0_SYSTEM: "系统提示"}
    context = RunContext(thread_id="t", account_id="acc", niche="母婴", tool_schema=_L1_TEXT)
    ContextCompiler().compile(context, sections)
    assert PromptLayer.L1_TOOL_SCHEMA not in sections
