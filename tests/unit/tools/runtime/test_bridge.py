"""P1c-S3 contract tests: the agent layer's composition root.

Two things are load-bearing here and neither is obvious from the code:

* the gateway is **shared**, so ``max_concurrency`` is a real ceiling rather
  than a per-call one — which is only safe because implementations are
  resolved per call, not captured;
* the trace *destination* is per-task (ContextVar), because agent classes are
  shared by concurrent workflows — the same lesson as P0-W1.
"""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from backend.tools.runtime import reset_gateway, shared_gateway, tracing_to

_TOPIC_SCORER = "backend.tools.analysis.topic_scorer.topic_scorer"


@pytest.fixture(autouse=True)
def _fresh_gateway():
    """The shared gateway is process-wide, so tests start from a clean one."""
    reset_gateway()
    yield
    reset_gateway()


def _scorer(return_value: dict[str, Any]) -> AsyncMock:
    """A LangChain-shaped double: routing only needs an awaitable ``ainvoke``."""
    fake = AsyncMock()
    fake.ainvoke = AsyncMock(return_value=return_value)
    return fake


class TestSharedGateway:
    def test_one_instance_process_wide(self):
        assert shared_gateway() is shared_gateway()

    def test_carries_the_real_catalogue(self):
        assert len(shared_gateway().registry) == 10

    def test_reset_rebuilds_it(self):
        first = shared_gateway()
        reset_gateway()
        assert shared_gateway() is not first


class TestLateBinding:
    """Why entries hold a *name* instead of a function object.

    Every agent test in this repo doubles a tool by rebinding its module
    attribute. A captured function would ignore that, so the agent would keep
    calling the real platform client while the test believed it was faking —
    the worst possible failure mode for a test.
    """

    @pytest.mark.asyncio
    async def test_a_tool_replaced_after_the_gateway_was_built_is_used(self):
        gateway = shared_gateway()  # built BEFORE the replacement, on purpose
        fake = _scorer({"heat_score": 99})
        with patch(_TOPIC_SCORER, fake):
            result = await gateway.invoke(
                "analysis.topic_scorer", {"topic": "探店", "niche": "美食"}
            )
        assert result.ok is True, result.error
        assert result.value == {"heat_score": 99}
        assert fake.ainvoke.await_count == 1

    @pytest.mark.asyncio
    async def test_each_replacement_is_adapted_again(self):
        gateway = shared_gateway()
        first, second = _scorer({"n": 1}), _scorer({"n": 2})
        with patch(_TOPIC_SCORER, first):
            assert (await gateway.invoke("analysis.topic_scorer", {})).value == {"n": 1}
        with patch(_TOPIC_SCORER, second):
            assert (await gateway.invoke("analysis.topic_scorer", {})).value == {"n": 2}
        assert first.ainvoke.await_count == 1
        assert second.ainvoke.await_count == 1

    @pytest.mark.asyncio
    async def test_a_kwargs_double_is_adapted_too(self):
        """Re-adaptation follows the *object*, not a remembered shape."""
        gateway = shared_gateway()

        async def double(**payload: Any) -> dict[str, Any]:
            return {"echo": payload}

        with patch(_TOPIC_SCORER, double):
            result = await gateway.invoke("analysis.topic_scorer", {"topic": "t"})
        assert result.value == {"echo": {"topic": "t"}}


class TestTracingScope:
    @pytest.mark.asyncio
    async def test_a_bound_sink_receives_the_event(self):
        events: list[dict[str, Any]] = []

        async def sink(event: Any) -> None:
            events.append(dict(event))

        with tracing_to(sink):
            await shared_gateway().invoke(
                "content.algorithmic_de_ai", {"selected_title": "震惊！绝了"}
            )

        assert len(events) == 1
        assert events[0]["kind"] == "tool"
        assert events[0]["capability"] == "content.algorithmic_de_ai"
        assert events[0]["ok"] is True

    @pytest.mark.asyncio
    async def test_unbound_means_nowhere_to_go_and_nothing_breaks(self):
        result = await shared_gateway().invoke(
            "content.algorithmic_de_ai", {"selected_title": "震惊！绝了"}
        )
        assert result.ok is True

    @pytest.mark.asyncio
    async def test_the_inner_scope_wins_and_the_outer_one_returns(self):
        outer: list[int] = []
        inner: list[int] = []

        async def outer_sink(event: Any) -> None:
            outer.append(1)

        async def inner_sink(event: Any) -> None:
            inner.append(1)

        gateway = shared_gateway()
        payload = {"selected_title": "震惊！绝了"}
        with tracing_to(outer_sink):
            await gateway.invoke("content.algorithmic_de_ai", payload)
            with tracing_to(inner_sink):
                await gateway.invoke("content.algorithmic_de_ai", payload)
            await gateway.invoke("content.algorithmic_de_ai", payload)

        assert len(outer) == 2
        assert len(inner) == 1

    @pytest.mark.asyncio
    async def test_concurrent_runs_do_not_share_a_destination(self):
        """P0-W1, again: the sink belongs to the task, not to a shared object."""
        seen: dict[str, list[dict[str, Any]]] = {"a": [], "b": []}
        gateway = shared_gateway()

        async def run(key: str) -> None:
            async def sink(event: Any) -> None:
                seen[key].append(dict(event))

            with tracing_to(sink):
                await gateway.invoke(
                    "content.algorithmic_de_ai",
                    {"selected_title": key},
                    thread_id=key,
                )

        await asyncio.gather(run("a"), run("b"))

        assert [event["thread_id"] for event in seen["a"]] == ["a"]
        assert [event["thread_id"] for event in seen["b"]] == ["b"]
