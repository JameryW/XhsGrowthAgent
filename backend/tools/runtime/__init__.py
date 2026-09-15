"""Tool Runtime — spec / registry / catalogue (P1c).

``ToolSpec`` declares what a capability *is*; ``ToolRegistry`` holds the
declarations; ``catalog.build_registry()`` is the table of every capability
the agents currently use. The Gateway (S2) is the only thing allowed to
invoke them.
"""

from backend.tools.runtime.catalog import adapt_tool, build_registry, describe_params
from backend.tools.runtime.models import (
    CostClass,
    LatencyClass,
    RetryPolicy,
    SideEffect,
    ToolFn,
    ToolResult,
    ToolSpec,
)
from backend.tools.runtime.registry import (
    DuplicateCapabilityError,
    RegisteredTool,
    ToolRegistry,
    UnknownCapabilityError,
)

__all__ = [
    "CostClass",
    "DuplicateCapabilityError",
    "LatencyClass",
    "RegisteredTool",
    "RetryPolicy",
    "SideEffect",
    "ToolFn",
    "ToolRegistry",
    "ToolResult",
    "ToolSpec",
    "UnknownCapabilityError",
    "adapt_tool",
    "build_registry",
    "describe_params",
]
