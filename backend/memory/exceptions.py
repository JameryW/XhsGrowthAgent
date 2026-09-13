"""Memory-layer domain exceptions (P0-W2).

Kept in a dependency-free module: ``backend.agents.base`` imports these at
module load, and base.py is on the hot import path (every agent/route pulls
it) — this module must stay as light as backend.memory.store's TYPE_CHECKING
guard allows.
"""

from __future__ import annotations

_VALID_NAMESPACES_HINT = (
    "expected one of: content_history, audience_preferences, performance_insights, strategy_notes"
)


class MemoryLayerError(Exception):
    """Base class for memory-layer programming errors (fail-fast, not swallowed)."""


class UnknownMemoryNamespaceError(MemoryLayerError):
    """Raised when a caller asks for a memory namespace that does not exist.

    Previously ``BaseAgent._recall_memory`` silently fell back to the
    performance-insights namespace on an unknown name, so a typo read the
    wrong memory and *looked* like a successful recall. Fail fast instead —
    this is a programming error, not a runtime storage failure.
    """

    def __init__(self, namespace: str):
        self.namespace = namespace
        super().__init__(f"Unknown memory namespace {namespace!r} ({_VALID_NAMESPACES_HINT})")
