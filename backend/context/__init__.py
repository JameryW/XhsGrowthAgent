"""Context Compiler package (P1b-S1 skeleton — decisions D1'-D6' in task info.md)."""

from backend.context.compiler import (
    ContextCompiler,
    apply_item_budget,
    dedup_items,
    rerank_items,
)
from backend.context.estimator import estimate_tokens
from backend.context.models import (
    LAYER_ORDER,
    CompiledPrompt,
    ContextItem,
    PromptLayer,
    RetrievalMode,
    RetrievalResult,
    RunContext,
)
from backend.context.prompts import PreparedPrompt, TemplateContext, prepare_prompt
from backend.context.recall import recall_memory
from backend.context.runtime import build_run_context, current_run_context, require_niche

__all__ = [
    "LAYER_ORDER",
    "CompiledPrompt",
    "ContextCompiler",
    "ContextItem",
    "PreparedPrompt",
    "TemplateContext",
    "PromptLayer",
    "RetrievalMode",
    "RetrievalResult",
    "RunContext",
    "apply_item_budget",
    "dedup_items",
    "estimate_tokens",
    "rerank_items",
    "prepare_prompt",
    "recall_memory",
    "build_run_context",
    "current_run_context",
    "require_niche",
]
