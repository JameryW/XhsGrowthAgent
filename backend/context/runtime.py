"""Request-local context built after artifact hydration, never checkpointed."""

from __future__ import annotations

from collections.abc import Mapping
from contextvars import ContextVar
from typing import Any

from backend.context.models import RunContext
from backend.state.events import resolve_thread_id

current_run_context: ContextVar[RunContext | None] = ContextVar("run_context", default=None)


def require_niche(state: Mapping[str, Any]) -> str:
    if state.get("historical_note") and not state.get("niche_context_available"):
        return "未提供赛道（不可推断）"
    niche = state.get("niche")
    if not isinstance(niche, str) or not niche.strip():
        raise ValueError("niche is required; specify an account niche before generation")
    return niche.strip()


def build_run_context(state: Mapping[str, Any]) -> RunContext:
    """Non-LLM nodes may have no niche; prompt compilation validates it."""
    return RunContext(
        thread_id=resolve_thread_id(state),
        account_id=str(state.get("account_id") or ""),
        niche=str(state.get("niche") or ""),
        workflow_mode=str(state.get("workflow_mode") or "trend"),
        phase=str(state.get("phase") or ""),
        topic=str(state.get("topic") or ""),
        values=dict(state),
    )
