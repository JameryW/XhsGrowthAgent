"""Tool Registry — capability → (spec, implementation) (P1c-S1).

The registry is a declarative table, not a dispatcher: S1 only records what
exists so the Gateway (S2) can route, budget and trace it. Registration is
fail-fast on purpose (duplicate capability, empty table lookups) — the same
posture as the P0-W2 namespace check: a typo must never silently degrade.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from backend.tools.runtime.models import ToolFn, ToolSpec

__all__ = [
    "DuplicateCapabilityError",
    "RegisteredTool",
    "ToolRegistry",
    "UnknownCapabilityError",
]


class DuplicateCapabilityError(ValueError):
    """Two implementations claimed the same capability id."""


class UnknownCapabilityError(KeyError):
    """A capability was requested that no spec declares."""

    def __init__(self, capability: str, known: tuple[str, ...] = ()) -> None:
        self.capability = capability
        self.known = known
        hint = f" (known: {', '.join(known)})" if known else ""
        super().__init__(f"unknown capability: {capability!r}{hint}")


@dataclass(frozen=True)
class RegisteredTool:
    """One registry entry: the declaration plus its implementation."""

    spec: ToolSpec
    fn: ToolFn

    @property
    def capability(self) -> str:
        return self.spec.capability


class ToolRegistry:
    """Declarative capability table.

    Not a singleton: build one per composition root (tests build their own),
    which keeps registration explicit and avoids import-time side effects.
    """

    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

    def register(self, spec: ToolSpec, fn: ToolFn) -> RegisteredTool:
        """Register one capability. Duplicate ids raise immediately."""
        if spec.capability in self._tools:
            raise DuplicateCapabilityError(f"capability already registered: {spec.capability!r}")
        entry = RegisteredTool(spec=spec, fn=fn)
        self._tools[spec.capability] = entry
        return entry

    def get(self, capability: str) -> RegisteredTool:
        """Look up a capability; unknown ids raise (never return ``None``)."""
        try:
            return self._tools[capability]
        except KeyError as exc:
            raise UnknownCapabilityError(capability, self.capabilities()) from exc

    def spec(self, capability: str) -> ToolSpec:
        return self.get(capability).spec

    def capabilities(self) -> tuple[str, ...]:
        """Every registered capability, sorted (stable for rendering/tests)."""
        return tuple(sorted(self._tools))

    def specs(self) -> tuple[ToolSpec, ...]:
        return tuple(self._tools[name].spec for name in self.capabilities())

    def subset(self, capabilities: tuple[str, ...] | list[str]) -> ToolRegistry:
        """A registry holding only the named capabilities.

        Used to render just the tool schemas one agent declared (L1 layer)
        without dragging the whole catalogue into its prompt.
        """
        narrowed = ToolRegistry()
        for capability in capabilities:
            entry = self.get(capability)
            narrowed.register(entry.spec, entry.fn)
        return narrowed

    def __contains__(self, capability: object) -> bool:
        return capability in self._tools

    def __len__(self) -> int:
        return len(self._tools)

    def __iter__(self) -> Iterator[RegisteredTool]:
        for name in self.capabilities():
            yield self._tools[name]
