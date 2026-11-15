"""Stable L0-L2 prefix and explicit cache breakpoint."""

from __future__ import annotations

from backend.context.models import (
    CACHE_BREAKPOINT,
    CACHE_PREFIX_LAYERS,
    CompiledPrompt,
    PromptLayer,
)


def _prompt() -> CompiledPrompt:
    return CompiledPrompt(
        layers={
            PromptLayer.L0_SYSTEM: "system rules",
            PromptLayer.L1_TOOL_SCHEMA: "tool schema",
            PromptLayer.L2_ACCOUNT: "account profile",
            PromptLayer.L3_TASK: "task brief",
            PromptLayer.L4_MEMORY: "memory snippets",
            PromptLayer.L5_OBSERVATION: "current observation",
        }
    )


def test_prefix_is_l0_to_l2_and_tail_is_rest() -> None:
    prompt = _prompt()

    assert prompt.cache_prefix == "system rules\n\ntool schema\n\naccount profile"
    assert prompt.cache_tail == "task brief\n\nmemory snippets\n\ncurrent observation"
    assert prompt.cache_prefix_token_cost > 0


def test_render_is_unchanged_and_breakpoint_is_opt_in() -> None:
    prompt = _prompt()

    assert prompt.render() == (
        "system rules\n\ntool schema\n\naccount profile\n\n"
        "task brief\n\nmemory snippets\n\ncurrent observation"
    )
    rendered = prompt.render_with_cache_breakpoint()
    assert CACHE_BREAKPOINT in rendered
    assert rendered.split(CACHE_BREAKPOINT)[0].strip() == prompt.cache_prefix
    assert rendered.split(CACHE_BREAKPOINT)[1].strip() == prompt.cache_tail


def test_prefix_does_not_change_when_only_tail_changes() -> None:
    first = _prompt()
    second = first.model_copy(
        update={
            "layers": {
                **first.layers,
                PromptLayer.L5_OBSERVATION: "different observation",
            }
        }
    )

    assert first.cache_prefix == second.cache_prefix
    assert first.cache_tail != second.cache_tail
    assert tuple(CACHE_PREFIX_LAYERS) == (
        PromptLayer.L0_SYSTEM,
        PromptLayer.L1_TOOL_SCHEMA,
        PromptLayer.L2_ACCOUNT,
    )
