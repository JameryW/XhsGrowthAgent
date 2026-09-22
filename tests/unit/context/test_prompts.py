"""Production template equivalence, stable prefixes and bounded compilation."""

import asyncio
import re
from collections import Counter
from dataclasses import replace
from pathlib import Path

import pytest
import yaml
from langgraph.store.memory import InMemoryStore

from backend.context.estimator import estimate_tokens
from backend.context.models import PromptLayer
from backend.context.prompts import TemplateContext, prepare_prompt
from backend.context.runtime import current_run_context
from backend.state.artifacts import artifact_seam

PROMPTS = Path(__file__).resolve().parents[3] / "backend/config/prompts"
VARIABLES = {
    "weights_block": "copywriting 0.40, compliance 0.60",
    "pass_threshold": "75",
    "reject_threshold": "55",
    "bias_severity_note": "本 epoch 加严",
    "state_summary": "当前执行状态",
}


@pytest.mark.parametrize("path", sorted(PROMPTS.glob("*.yaml")), ids=lambda p: p.stem)
def test_all_templates_preserve_content_and_stable_prefix(path):
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    template = data.get("system", "")
    schema = TemplateContext.model_validate(data["context"])
    state = {"account_id": "a", "thread_id": "t", "niche": "美食"}
    prompt = prepare_prompt(state, template, schema, memory="memory-one", variables=VARIABLES)
    old = template
    values = {"account_niche": "美食", "memory_context": "memory-one", "ripple_context": ""}
    values.update(VARIABLES)
    for name, value in values.items():
        old = old.replace("{" + name + "}", value)
    if "{account_niche}" not in template:
        old += "\n账号垂类：美食\n"
    if "{memory_context}" not in template:
        old += "\nmemory-one\n"

    # Layer moves may change whitespace and order, never policy/example text.
    def tokens(text):
        return Counter(re.findall(r"\w+|[^\w\s]", text))

    assert tokens(prompt.render()) == tokens(old)
    next_prompt = prepare_prompt(
        {**state, "topic": "new topic", "phase": "creating"},
        template,
        schema,
        memory="memory-two",
        variables={**VARIABLES, "pass_threshold": "90"},
    ).with_observations("new observation")
    first = prompt.messages("task-one")
    second = next_prompt.messages("task-two")
    assert first[0].content == second[0].content
    assert "memory-one" not in first[0].content
    assert "memory-one" in first[1].content
    assert first[1].content.index("task-one") < first[1].content.index("memory-one")
    assert second[1].content.index("memory-two") < second[1].content.index("new observation")


def test_replacement_values_are_not_reinterpreted_as_placeholders():
    schema = TemplateContext(variables={"memory_context": PromptLayer.L4_MEMORY})
    text = '{"example": {"json": true}}\n\n{memory_context}'
    prompt = prepare_prompt({"niche": "美食"}, text, schema, memory="literal {account_niche}")
    assert '{"example": {"json": true}}' in prompt.render()
    assert "literal {account_niche}" in prompt.render()


def test_budget_trims_observations_then_memory_and_keeps_required_policy():
    data = yaml.safe_load((PROMPTS / "evaluator.yaml").read_text(encoding="utf-8"))
    prompt = prepare_prompt(
        {"niche": "美食"},
        data["system"],
        TemplateContext.model_validate(data["context"]),
        variables=VARIABLES,
        memory="记" * 1200,
    ).with_observations("观" * 1500)
    pinned = (
        prepare_prompt(
            {"niche": "美食"},
            data["system"],
            TemplateContext.model_validate(data["context"]),
            variables=VARIABLES,
        )
        .compile("task")
        .total_token_cost
    )
    compiled = replace(prompt, budget=pinned + 1250).compile("task")
    assert "观" * 1500 not in compiled.render()
    assert "记" * 1200 in compiled.render()
    compiled = replace(prompt, budget=pinned + 10).compile("task")
    assert "记" * 1200 not in compiled.render()
    assert ">= 75" in compiled.render()
    assert "copywriting 0.40" in compiled.render()
    assert compiled.total_token_cost == estimate_tokens(compiled.render())
    assert compiled.total_token_cost <= pinned + 10
    with pytest.raises(ValueError, match="Required context exceeds"):
        replace(prompt, budget=10).compile("task")


@pytest.mark.parametrize("state", [{}, {"niche": ""}, {"niche": "   "}, {"niche": None}])
def test_missing_niche_fails_before_prompt_is_built(state):
    with pytest.raises(ValueError, match="niche is required"):
        prepare_prompt(state, "policy", TemplateContext())


def test_historical_unknown_niche_is_explicit_not_invented():
    prompt = prepare_prompt(
        {"historical_note": True, "niche_context_available": False},
        "policy",
        TemplateContext(),
    )
    assert "未提供赛道（不可推断）" in prompt.render()
    assert "母婴" not in prompt.render()


def test_schema_errors_fail_closed():
    with pytest.raises(ValueError, match="Undeclared"):
        prepare_prompt({"niche": "美食"}, "{typo}", TemplateContext())
    with pytest.raises(ValueError):
        TemplateContext.model_validate({"version": 2})
    with pytest.raises(ValueError):
        TemplateContext.model_validate({"variables": {"memory_context": "l6_unknown"}})


async def test_run_context_is_local_to_hydrated_node_and_reset_on_failure():
    barrier = asyncio.Event()
    entered = set()
    contexts = {}

    async def node(state, *, store):
        context = current_run_context.get()
        assert context is not None
        entered.add(context.account_id)
        if len(entered) == 2:
            barrier.set()
        await asyncio.wait_for(barrier.wait(), 1)
        contexts[context.account_id] = current_run_context.get()
        assert context.values == state
        if context.account_id == "b":
            raise RuntimeError("node failure")
        prompt = prepare_prompt(state, "policy", TemplateContext())
        assert prompt.context.thread_id == context.thread_id
        return {"phase": "completed"}

    results = await asyncio.gather(
        *(
            artifact_seam(node)(
                {"account_id": a, "session_id": a, "niche": "美食"},
                store=InMemoryStore(),
            )
            for a in ("a", "b")
        ),
        return_exceptions=True,
    )
    assert results[0] == {"phase": "completed"}
    assert isinstance(results[1], RuntimeError)
    assert contexts["a"].account_id == "a"
    assert contexts["b"].account_id == "b"
    assert current_run_context.get() is None
