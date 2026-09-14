"""P1b-S3 tests: segment schema, compile_prompt, L0-L2 stable prefix."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.context.compiler import ContextCompiler
from backend.context.estimator import estimate_tokens
from backend.context.models import (
    ContextItem,
    PromptLayer,
    RetrievalMode,
    RetrievalResult,
    RunContext,
)
from backend.context.segments import (
    SegmentSchemaError,
    marker_for,
    parse_system_segments,
    segments_equivalent_to_source,
)

SYSTEM_SEGMENTED = """你是小红书增长引擎。
<!-- ctx:l0_system -->
安全与风格红线：不得虚构数据。
<!-- ctx:l2_account -->
账号定位：{account_niche}
"""


def _rc() -> RunContext:
    return RunContext(thread_id="t", account_id="a", niche="母婴")


def _hit(ns: str, body: str, layer: PromptLayer) -> RetrievalResult:
    return RetrievalResult(
        namespace=ns,
        layer=layer,
        mode=RetrievalMode.HIT,
        items=(ContextItem(body=body, source=f"memory:{ns}"),),
    )


# ── parse_system_segments ──


def test_unsegmented_system_is_single_l0() -> None:
    system = "纯 policy 文本，没有标记。"
    segments = parse_system_segments(system)
    assert segments == {PromptLayer.L0_SYSTEM: system}


def test_markers_split_and_preamble_joins_l0() -> None:
    segments = parse_system_segments(SYSTEM_SEGMENTED)
    # preamble (before any marker) and the l0_system marker body are one L0
    # segment — both are static policy text by definition.
    assert segments[PromptLayer.L0_SYSTEM] == (
        "你是小红书增长引擎。\n安全与风格红线：不得虚构数据。"
    )
    assert segments[PromptLayer.L2_ACCOUNT] == "账号定位：{account_niche}"


def test_segment_content_is_verbatim() -> None:
    system = "头。\n<!-- ctx:l4_memory -->\n  缩进 保留\n\n内部空行\n"
    segments = parse_system_segments(system)
    assert segments[PromptLayer.L4_MEMORY] == "  缩进 保留\n\n内部空行"


def test_unknown_layer_fails_fast() -> None:
    with pytest.raises(SegmentSchemaError):
        parse_system_segments("<!-- ctx:l9_unknown -->\n文本")


def test_descending_order_fails_fast() -> None:
    system = "<!-- ctx:l4_memory -->\n记忆\n<!-- ctx:l0_system -->\n政策\n"
    with pytest.raises(SegmentSchemaError):
        parse_system_segments(system)


def test_duplicate_marker_fails_fast() -> None:
    system = "<!-- ctx:l0_system -->\n一\n<!-- ctx:l0_system -->\n二\n"
    with pytest.raises(SegmentSchemaError):
        parse_system_segments(system)


def test_marker_for_round_trips() -> None:
    assert marker_for(PromptLayer.L2_ACCOUNT) == "<!-- ctx:l2_account -->"
    segments = parse_system_segments(f"{marker_for(PromptLayer.L2_ACCOUNT)}\n正文")
    assert segments == {PromptLayer.L2_ACCOUNT: "正文"}


def test_marker_with_spaces_still_parses() -> None:
    segments = parse_system_segments("<!-- ctx: l2_account -->\n正文")
    assert segments == {PromptLayer.L2_ACCOUNT: "正文"}


def test_equivalence_invariant_holds() -> None:
    assert segments_equivalent_to_source(SYSTEM_SEGMENTED)
    assert segments_equivalent_to_source("无标记文本")
    tricky = "  缩进头\n<!-- ctx:l4_memory -->\n\n  保留缩进  \n\n尾\n"
    assert segments_equivalent_to_source(tricky)


def test_equivalence_detects_lossy_parser(monkeypatch: pytest.MonkeyPatch) -> None:
    """The red-line invariant must catch a parser that rewrites text."""
    import backend.context.segments as seg

    def lossy(system: str) -> dict[PromptLayer, str]:
        dropped = system.replace("安全与风格红线：不得虚构数据。", "")
        return {PromptLayer.L0_SYSTEM: dropped}

    monkeypatch.setattr(seg, "parse_system_segments", lossy)
    assert not seg.segments_equivalent_to_source(SYSTEM_SEGMENTED)


# ── compile_prompt + stable prefix ──


_L0_EXPECTED = "你是小红书增长引擎。\n安全与风格红线：不得虚构数据。"


def test_compile_prompt_layers_and_l3_merge() -> None:
    prompt = ContextCompiler().compile_prompt(
        _rc(),
        SYSTEM_SEGMENTED,
        user_template="任务：分析爆款趋势。",
        retrievals=(_hit("content_history", "历史洞察 A", PromptLayer.L4_MEMORY),),
    )
    assert prompt.layers[PromptLayer.L0_SYSTEM] == _L0_EXPECTED
    assert prompt.layers[PromptLayer.L2_ACCOUNT] == "账号定位：{account_niche}"
    assert "安全与风格红线" in prompt.layers[PromptLayer.L0_SYSTEM]
    assert prompt.layers[PromptLayer.L3_TASK] == "任务：分析爆款趋势。"
    assert prompt.layers[PromptLayer.L4_MEMORY] == "历史洞察 A"
    rendered = prompt.render()
    assert rendered.index("增长引擎") < rendered.index("账号定位") < rendered.index("任务：")


def test_l0_l2_prefix_stable_across_supersteps() -> None:
    compiler = ContextCompiler()
    first = compiler.compile_prompt(
        _rc(),
        SYSTEM_SEGMENTED,
        user_template="任务一。",
        retrievals=(_hit("content_history", "洞察一", PromptLayer.L4_MEMORY),),
    )
    second = compiler.compile_prompt(
        _rc(),
        SYSTEM_SEGMENTED,
        user_template="任务二（不同 superstep）。",
        retrievals=(
            _hit("audience_preferences", "偏好二", PromptLayer.L4_MEMORY),
            _hit("performance_insights", "实时数据二", PromptLayer.L5_OBSERVATION),
        ),
    )
    for layer in (PromptLayer.L0_SYSTEM, PromptLayer.L1_TOOL_SCHEMA, PromptLayer.L2_ACCOUNT):
        assert first.layers.get(layer, "") == second.layers.get(layer, "")
    prefix = "\n\n".join(
        first.layers[layer]
        for layer in PromptLayer
        if layer in first.layers and layer in (PromptLayer.L0_SYSTEM, PromptLayer.L2_ACCOUNT)
    )
    assert second.render().startswith(prefix)


def test_budget_trims_l5_before_l4() -> None:
    compiler = ContextCompiler()
    l4_body = "四" * 40
    l5_body = "五" * 40
    static_cost = (
        estimate_tokens("你是小红书增长引擎。")
        + estimate_tokens("安全与风格红线：不得虚构数据。")
        + estimate_tokens("账号定位：{account_niche}")
    )
    budget = static_cost + estimate_tokens(l4_body) + estimate_tokens(l5_body) - 1
    prompt = compiler.compile_prompt(
        _rc(),
        SYSTEM_SEGMENTED,
        retrievals=(
            _hit("content_history", l4_body, PromptLayer.L4_MEMORY),
            _hit("performance_insights", l5_body, PromptLayer.L5_OBSERVATION),
        ),
        budget=budget,
    )
    assert PromptLayer.L5_OBSERVATION not in prompt.layers
    assert PromptLayer.L4_MEMORY in prompt.layers
    assert prompt.total_token_cost <= budget


def test_budget_never_touches_static_layers() -> None:
    compiler = ContextCompiler()
    prompt = compiler.compile_prompt(
        _rc(),
        SYSTEM_SEGMENTED,
        retrievals=(_hit("content_history", "x" * 500, PromptLayer.L4_MEMORY),),
        budget=1,  # absurdly small: static still wins
    )
    assert prompt.layers[PromptLayer.L0_SYSTEM] == _L0_EXPECTED
    assert "账号定位：{account_niche}" in prompt.layers[PromptLayer.L2_ACCOUNT]


def test_recall_item_with_timestamp_reranks_by_recency() -> None:
    old = ContextItem(body="旧", source="memory:ns", timestamp=datetime(2026, 1, 1, tzinfo=UTC))
    new = ContextItem(body="新", source="memory:ns", timestamp=datetime(2026, 9, 14, tzinfo=UTC))
    result = RetrievalResult(
        namespace="ns",
        mode=RetrievalMode.HIT,
        items=(old, new),
    )
    prompt = ContextCompiler().compile_prompt(_rc(), SYSTEM_SEGMENTED, retrievals=(result,))
    assert prompt.layers[PromptLayer.L4_MEMORY].index("新") < prompt.layers[
        PromptLayer.L4_MEMORY
    ].index("旧")
