"""L1 tool-schema rendering (P1c-S4).

What is pinned here is the *rendering contract*: deterministic order (a stable
prefix that reshuffles is not a stable prefix), the ``pass_style`` branch S1
handed off in ``describe_params``' docstring, and the runtime facts that stay
out of the prompt.
"""

from __future__ import annotations

import pytest

from backend.tools.runtime.bridge import tool_schema_section
from backend.tools.runtime.catalog import build_registry
from backend.tools.runtime.models import CostClass, LatencyClass, PassStyle, SideEffect, ToolSpec
from backend.tools.runtime.registry import UnknownCapabilityError
from backend.tools.runtime.schema import render_tool_schema


def _spec(
    capability: str,
    *,
    summary: str = "摘要",
    pass_style: PassStyle = PassStyle.INVOKE,
    params: dict | None = None,
    side_effect: SideEffect = SideEffect.READ_ONLY,
) -> ToolSpec:
    return ToolSpec(
        capability=capability,
        summary=summary,
        side_effect=side_effect,
        pass_style=pass_style,
        input_schema=params or {},
    )


class TestRenderShape:
    def test_nothing_to_render_renders_nothing(self) -> None:
        """Empty asks produce ``""``, not a header — the compiler reads
        emptiness to decide whether the layer exists at all, so a stray header
        would put an empty L1 into every prompt."""
        assert render_tool_schema([]) == ""

    def test_the_order_is_the_capability_order(self) -> None:
        """Deterministic regardless of how the specs arrived: this text sits in
        the stable prefix, so a run-to-run reshuffle would defeat the layer."""
        text = render_tool_schema([_spec("xhs.trending"), _spec("analysis.topic_scorer")])
        assert text.index("analysis.topic_scorer") < text.index("xhs.trending")

    def test_a_capability_named_twice_is_described_once(self) -> None:
        text = render_tool_schema([_spec("xhs.trending"), _spec("xhs.trending")])
        assert text.count("- xhs.trending") == 1

    def test_each_capability_carries_its_summary(self) -> None:
        text = render_tool_schema([_spec("xhs.trending", summary="抓取平台热门趋势")])
        assert "- xhs.trending — 抓取平台热门趋势" in text


class TestParameterRendering:
    def test_required_and_optional_read_differently(self) -> None:
        text = render_tool_schema(
            [
                _spec(
                    "x.example",
                    params={
                        "topic": {"type": "string", "required": True},
                        "niche": {"type": "string", "required": False},
                    },
                )
            ]
        )
        assert "topic: string" in text
        assert "topic?: string" not in text
        assert "niche?: string" in text

    def test_a_tool_without_parameters_says_so(self) -> None:
        assert "参数: 无" in render_tool_schema([_spec("pure.thing")])

    def test_a_mapping_tool_is_not_rendered_like_the_others(self) -> None:
        """S1's hand-off, made concrete.

        ``describe_params`` reflects the MAPPING tool's single ``data``
        parameter like any other, so a naive renderer would describe it exactly
        the way it describes the nine tools that unpack by name — and the
        difference is precisely the one that decides whether a call carries the
        payload or silently drops it.
        """
        text = render_tool_schema(
            [
                _spec(
                    "content.algorithmic_de_ai",
                    pass_style=PassStyle.MAPPING,
                    params={"data": {"type": "dict[str, Any]", "required": True}},
                )
            ]
        )
        assert "参数: 整体即 `data: dict[str, Any]`" in text
        assert "参数: data:" not in text

    def test_a_reflected_schema_is_rendered_as_found(self) -> None:
        """Types are reflected, not normalised: a LangChain tool reports
        JSON-schema types and a plain function reports annotation names, and
        inventing a common vocabulary here would describe schemas the tools do
        not have."""
        text = render_tool_schema(
            [_spec("x.a", params={"topic": {"type": "string", "required": True}})]
        )
        assert "topic: string" in text


class TestRuntimeFactsStayOut:
    def test_side_effect_scope_and_cost_are_not_in_the_prompt(self) -> None:
        """L1 tells the model what exists and how it is called.

        What the runtime will *do* about a call — whether it may be retried,
        which scope it needs — is the Gateway's business. Putting it in the
        prompt would invite a model to reason about permissions it does not
        hold, and none of it changes the call shape.
        """
        spec = ToolSpec(
            capability="xhs.publish",
            summary="发布笔记到小红书（写操作）",
            side_effect=SideEffect.SIDE_EFFECTING,
            latency=LatencyClass.SLOW,
            cost=CostClass.EXPENSIVE,
            auth_scope=("xhs:write",),
        )
        text = render_tool_schema([spec])
        for leaked in ("side_effecting", "xhs:write", "expensive", "slow"):
            assert leaked not in text


class TestRegistrySeam:
    def test_an_empty_declaration_never_touches_the_registry(self) -> None:
        assert tool_schema_section(()) == ""

    def test_the_declared_capabilities_are_the_ones_rendered(self) -> None:
        text = tool_schema_section(["ripple.get_report"])
        assert "- ripple.get_report — " in text
        assert "xhs.trending" not in text

    def test_an_unknown_capability_is_a_wiring_error(self) -> None:
        """A typo in an agent's declaration must not render as "no such tool"
        and quietly ship an L1 that omits it."""
        with pytest.raises(UnknownCapabilityError):
            tool_schema_section(["xhs.trending", "xhs.typo"])

    def test_the_whole_catalogue_renders(self) -> None:
        registry = build_registry()
        text = render_tool_schema(registry.specs())
        for capability in registry.capabilities():
            assert f"- {capability} — " in text, capability
