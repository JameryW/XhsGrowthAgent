"""Declarative template segmentation and L0-L5 message compilation.

Only declared placeholders are substituted: JSON examples and braces in
inserted user/memory content are never interpreted as template syntax.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from backend.context.compiler import ContextCompiler
from backend.context.estimator import estimate_tokens
from backend.context.models import (
    CompiledPrompt,
    ContextItem,
    PromptLayer,
    RetrievalMode,
    RetrievalResult,
    RunContext,
)
from backend.context.runtime import build_run_context, current_run_context, require_niche

DEFAULT_CONTEXT_BUDGET = 32768
_VARIABLE = re.compile(r"\{([a-z_]+)\}")
_KNOWN_VARIABLES = frozenset(
    {
        "account_niche",
        "memory_context",
        "ripple_context",
        "weights_block",
        "pass_threshold",
        "reject_threshold",
        "bias_severity_note",
        "state_summary",
        "topic",
        "angle",
        "target_audience",
        "content_type",
        "phase",
        "error",
        "pending_count",
        "has_plan",
        "has_report",
        "brief_text",
        "trend_data",
        "performance_insights",
        "post_data",
        "history_data",
        "draft_title",
        "draft_text",
        "draft_hashtags",
        "viral_summary",
        "keywords",
        "candidate_limit",
        "niche",
    }
)


class TemplateContext(BaseModel):
    """YAML context schema; unknown fields/layers fail at template load."""

    model_config = ConfigDict(extra="forbid")
    version: int = Field(default=1, ge=1, le=1)
    variables: dict[str, PromptLayer] = Field(default_factory=dict)
    required: tuple[str, ...] = ()


@dataclass(frozen=True)
class PreparedPrompt:
    context: RunContext
    sections: Mapping[PromptLayer, str]
    retrievals: tuple[RetrievalResult, ...] = ()
    budget: int = DEFAULT_CONTEXT_BUDGET

    def with_memory(
        self,
        result: RetrievalResult | list[dict[str, Any]] | tuple[dict[str, Any], ...],
        formatter: Callable[[dict[str, Any]], str],
    ) -> PreparedPrompt:
        """Format each record without discarding recall provenance or rank."""
        if not isinstance(result, RetrievalResult):
            result = RetrievalResult(
                namespace="legacy",
                mode=RetrievalMode.HIT,
                items=tuple(ContextItem(body="", source="legacy", value=value) for value in result),
            )
        items = []
        for item in result.items:
            body = formatter(item.value)
            items.append(
                item.model_copy(
                    update={
                        "body": body,
                        "token_cost": estimate_tokens(body),
                    }
                )
            )
        formatted = result.model_copy(update={"items": tuple(items)})
        return replace(self, retrievals=(*self.retrievals, formatted))

    def with_observations(self, text: str, *, required: bool = False) -> PreparedPrompt:
        if not text:
            return self
        item = ContextItem(body=text, source="observation", required=required)
        result = RetrievalResult(
            namespace="observations",
            layer=PromptLayer.L5_OBSERVATION,
            items=(item,),
            mode=RetrievalMode.HIT,
        )
        return replace(self, retrievals=(*self.retrievals, result))

    def with_task_hint(self, text: str) -> PreparedPrompt:
        sections = dict(self.sections)
        sections[PromptLayer.L3_TASK] = "\n\n".join(
            part for part in (sections.get(PromptLayer.L3_TASK, ""), text) if part
        )
        return replace(self, sections=sections)

    def compile(self, task: str = "") -> CompiledPrompt:
        prompt = self.with_task_hint(task)
        return ContextCompiler().compile(
            self.context,
            prompt.sections,
            self.retrievals,
            budget=self.budget,
        )

    def render(self) -> str:
        return self.compile().render()

    def messages(self, task: str) -> list[Any]:
        from langchain_core.messages import HumanMessage, SystemMessage

        compiled = self.compile(task)
        stable = "\n\n".join(
            compiled.layers[layer]
            for layer in (
                PromptLayer.L0_SYSTEM,
                PromptLayer.L1_TOOL_SCHEMA,
                PromptLayer.L2_ACCOUNT,
            )
            if layer in compiled.layers
        )
        dynamic = "\n\n".join(
            compiled.layers[layer]
            for layer in (
                PromptLayer.L3_TASK,
                PromptLayer.L4_MEMORY,
                PromptLayer.L5_OBSERVATION,
            )
            if layer in compiled.layers
        )
        return [SystemMessage(content=stable), HumanMessage(content=dynamic)]


def prepare_prompt(
    state: Mapping[str, Any],
    template: str,
    schema: TemplateContext,
    *,
    memory: str = "",
    variables: Mapping[str, str] | None = None,
    budget: int = DEFAULT_CONTEXT_BUDGET,
) -> PreparedPrompt:
    niche = require_niche(state)
    context = current_run_context.get()
    if context is None or context.values != state:
        context = build_run_context(state)
    context = context.model_copy(update={"niche": niche})
    values = {"account_niche": niche, "memory_context": memory, "ripple_context": ""}
    values.update({name: "" for name in _KNOWN_VARIABLES if name not in values})
    values.update(variables or {})
    sections: dict[PromptLayer, list[str]] = {}
    retrievals: list[RetrievalResult] = []

    # Standalone placeholders are independent segments even if adjacent;
    # otherwise paragraphs stay intact (e.g. evaluator decision rules).
    segments = re.split(r"\n\s*\n|(?m:^[ \t]*(\{[a-z_]+\})[ \t]*$)", template)
    for segment in segments:
        if not segment or not segment.strip():
            continue
        names = set(_VARIABLE.findall(segment))
        undeclared = names - schema.variables.keys() - _KNOWN_VARIABLES
        if undeclared:
            raise ValueError(f"Undeclared prompt variables: {sorted(undeclared)}")
        missing = names - values.keys()
        if missing:
            raise ValueError(f"Missing prompt variables: {sorted(missing)}")
        layers = {
            schema.variables.get(
                name,
                PromptLayer.L3_TASK
                if name
                not in {
                    "account_niche",
                    "niche",
                    "memory_context",
                    "ripple_context",
                    "weights_block",
                    "pass_threshold",
                    "reject_threshold",
                    "bias_severity_note",
                }
                else {
                    "account_niche": PromptLayer.L2_ACCOUNT,
                    "niche": PromptLayer.L2_ACCOUNT,
                    "memory_context": PromptLayer.L4_MEMORY,
                    "ripple_context": PromptLayer.L5_OBSERVATION,
                    "weights_block": PromptLayer.L5_OBSERVATION,
                    "pass_threshold": PromptLayer.L5_OBSERVATION,
                    "reject_threshold": PromptLayer.L5_OBSERVATION,
                    "bias_severity_note": PromptLayer.L5_OBSERVATION,
                }[name],
            )
            for name in names
        }
        if len(layers) > 1:
            raise ValueError("A prompt segment cannot mix context layers")
        layer = next(iter(layers), PromptLayer.L0_SYSTEM)
        text = _VARIABLE.sub(lambda match: values[match[1]], segment).strip()
        if not text:
            continue
        if layer in (PromptLayer.L4_MEMORY, PromptLayer.L5_OBSERVATION):
            retrievals.append(
                RetrievalResult(
                    namespace="template",
                    layer=layer,
                    mode=RetrievalMode.HIT,
                    items=(
                        ContextItem(
                            body=text,
                            source="template:" + ",".join(sorted(names)),
                            required=bool(names.intersection(schema.required)),
                        ),
                    ),
                )
            )
        else:
            sections.setdefault(layer, []).append(text)
    if PromptLayer.L2_ACCOUNT not in sections:
        sections[PromptLayer.L2_ACCOUNT] = [f"账号垂类：{niche}"]
    # Some templates have no memory placeholder. The context must still reach
    # the model (historically it was silently discarded on these paths).
    if memory and "memory_context" not in _VARIABLE.findall(template):
        retrievals.append(
            RetrievalResult(
                namespace="memory",
                mode=RetrievalMode.HIT,
                items=(ContextItem(body=memory, source="memory:agent"),),
            )
        )
    return PreparedPrompt(
        context=context,
        sections={k: "\n\n".join(v) for k, v in sections.items()},
        retrievals=tuple(retrievals),
        budget=budget,
    )
