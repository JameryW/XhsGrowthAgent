"""Composition root + trace routing for the agent layer (P1c-S3).

Agents call capabilities by name through one shared gateway; they never
import the catalogue. Keeping the seam in one module is what lets the S5
gate forbid ``backend.agents.**`` from importing ``backend.tools.**`` except
here — so "did this agent bypass the runtime?" stays an AST question rather
than a review question.
"""

from __future__ import annotations

import contextvars
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from typing import Any

from backend.tools.runtime.catalog import build_registry
from backend.tools.runtime.gateway import ToolGateway, TraceSink
from backend.tools.runtime.schema import render_tool_schema

__all__ = ["reset_gateway", "shared_gateway", "tool_schema_section", "tracing_to"]

_trace_var: contextvars.ContextVar[TraceSink | None] = contextvars.ContextVar(
    "tool_trace_sink", default=None
)
"""Where the *current task's* tool events go (``None`` = nowhere)."""

_gateway: ToolGateway | None = None


async def _dispatch(event: Mapping[str, Any]) -> None:
    """Forward one trace event to the sink bound for this context.

    A plain dispatcher, and the only thing the shared gateway was built
    with: the destination belongs to the running workflow, so it cannot be
    baked into a process-wide object.
    """
    sink = _trace_var.get()
    if sink is not None:
        await sink(event)


def shared_gateway() -> ToolGateway:
    """The process-wide Gateway, built on first use.

    Deliberately shared rather than built per call. ``max_concurrency`` is a
    semaphore owned by the gateway, so a per-call gateway would hand every
    concurrent workflow its own ceiling — i.e. no ceiling at all on exactly
    the platform-scraping capabilities that need one. Sharing it is safe
    because implementations are resolved per call (:func:`catalog.bind`),
    not captured: a shared gateway does not freeze what the catalogue points
    at, so test doubles still work.
    """
    global _gateway
    if _gateway is None:
        _gateway = ToolGateway(build_registry(), trace=_dispatch)
    return _gateway


def reset_gateway() -> None:
    """Drop the shared gateway so the next call rebuilds it (tests)."""
    global _gateway
    _gateway = None


def tool_schema_section(capabilities: Sequence[str]) -> str:
    """L1 text for these capabilities, resolved from the shared registry.

    The agent-facing seam for the layer (S4): an agent declares the
    capabilities it uses and hands them over here; it never names a module
    path, just as it never names one when invoking. Resolution goes through
    ``ToolRegistry.subset`` — the narrowing S1 built for exactly this, so the
    renderer sees the agent's own capabilities and not the catalogue's other
    nine. An unknown or duplicated name raises from the registry rather than
    rendering as "no such tool": a declaration that does not match the
    catalogue is a wiring mistake, and the error says which name is wrong.

    Returning ``""`` for an empty declaration is what makes the layer opt-in
    per agent: no capabilities, no L1, nothing to render.
    """
    if not capabilities:
        return ""
    registry = shared_gateway().registry
    return render_tool_schema(registry.subset(list(capabilities)).specs())


@contextmanager
def tracing_to(sink: TraceSink | None) -> Iterator[None]:
    """Route tool trace events to ``sink`` for the duration of the block.

    ContextVar-scoped on purpose, the same reason as the P0-W1 llm-perf
    accumulator: agent classes are module-level singletons shared by every
    concurrent workflow on one event loop, so a trace destination stored on
    the instance would mix up threads. Tasks created inside the block inherit
    the binding, which is what makes ``asyncio.gather`` inside an agent work.
    """
    token = _trace_var.set(sink)
    try:
        yield
    finally:
        _trace_var.reset(token)
