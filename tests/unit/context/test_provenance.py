"""P1-A Context Provenance — fields travel with the item, rendering is opt-in."""

from __future__ import annotations

from datetime import UTC, datetime

from backend.context.compiler import ContextCompiler
from backend.context.models import (
    CompiledPrompt,
    ContextItem,
    PromptLayer,
    RetrievalMode,
    RetrievalResult,
    RunContext,
    TrustClass,
)


def _item(body: str = "记忆内容", **kwargs) -> ContextItem:
    base = {
        "body": body,
        "source": "memory:content_history",
        "timestamp": datetime(2026, 10, 1, tzinfo=UTC),
        "confidence": 0.9,
    }
    base.update(kwargs)
    return ContextItem(**base)


def _run_context() -> RunContext:
    return RunContext(thread_id="t1", account_id="a1", niche="母婴")


def _retrieval(item: ContextItem) -> tuple[RetrievalResult, ...]:
    return (
        RetrievalResult(
            namespace="content_history",
            layer=PromptLayer.L4_MEMORY,
            items=(item,),
            mode=RetrievalMode.HIT,
        ),
    )


class TestFields:
    def test_defaults_are_conservative(self):
        item = ContextItem(body="x", source="s")
        assert item.trust_class is TrustClass.UNSPECIFIED
        assert item.verified is False
        assert item.ttl_seconds is None
        assert item.source_version == ""

    def test_provenance_label_minimal(self):
        assert _item().provenance_label() == "[source=memory:content_history trust=unspecified]"

    def test_provenance_label_full(self):
        item = _item(
            trust_class=TrustClass.INTERNAL_FACT,
            verified=True,
            ttl_seconds=3600,
            source_version="commit_9a72",
        )
        label = item.provenance_label()
        assert "trust=internal_fact" in label
        assert "verified" in label
        assert "version=commit_9a72" in label
        assert "ttl=3600s" in label


class TestRendering:
    def test_default_render_is_byte_identical(self):
        """The baseline pins rendered bytes — provenance must not leak in."""
        compiled_default = ContextCompiler().compile(_run_context(), {}, _retrieval(_item()))
        compiled_explicit_off = ContextCompiler().compile(
            _run_context(), {}, _retrieval(_item()), annotate_provenance=False
        )
        assert compiled_default.layers == compiled_explicit_off.layers
        assert "trust=" not in compiled_default.layers[PromptLayer.L4_MEMORY]

    def test_annotate_appends_label(self):
        compiled = ContextCompiler().compile(
            _run_context(), {}, _retrieval(_item()), annotate_provenance=True
        )
        line = compiled.layers[PromptLayer.L4_MEMORY]
        assert line.startswith("记忆内容")
        assert "trust=unspecified" in line
        assert "source=memory:content_history" in line

    def test_annotate_changes_token_cost(self):
        plain = ContextCompiler().compile(_run_context(), {}, _retrieval(_item()))
        tagged = ContextCompiler().compile(
            _run_context(), {}, _retrieval(_item()), annotate_provenance=True
        )
        assert tagged.total_token_cost > plain.total_token_cost

    def test_compile_prompt_passes_flag_through(self):
        compiled: CompiledPrompt = ContextCompiler().compile_prompt(
            _run_context(),
            "system",
            retrievals=_retrieval(_item(trust_class=TrustClass.MEMORY)),
            annotate_provenance=True,
        )
        assert "trust=memory" in compiled.layers[PromptLayer.L4_MEMORY]


class TestProducers:
    def test_content_history_is_internal_fact(self):
        from backend.context.retrieval import item_to_context_item

        item = item_to_context_item(
            {"content": "已发布笔记：标题A", "post_id": "p1"}, "content_history"
        )
        assert item.trust_class is TrustClass.INTERNAL_FACT

    def test_derived_namespaces_are_memory(self):
        from backend.context.retrieval import item_to_context_item

        for namespace in ("audience_preferences", "performance_insights", "strategy_notes"):
            item = item_to_context_item({"content": "洞察"}, namespace)
            assert item.trust_class is TrustClass.MEMORY

    def test_hy_memory_items_are_memory_and_unverified(self):
        from backend.memory.hy.recall import _to_context_item

        item = _to_context_item(
            {"content": "Memory: 用户喜欢科幻电影", "channel": "normal", "score": 0.8}
        )
        assert item.trust_class is TrustClass.MEMORY
        assert item.verified is False
