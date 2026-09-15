"""Tool Runtime — spec / registry / catalogue (P1c).

``ToolSpec`` declares what a capability *is*; ``ToolRegistry`` holds the
declarations; ``catalog.build_registry()`` is the table of every capability
the agents currently use. The Gateway (S2) is the only thing allowed to
invoke them.
"""

from backend.tools.runtime.bridge import (
    reset_gateway,
    shared_gateway,
    tool_schema_section,
    tracing_to,
)
from backend.tools.runtime.catalog import (
    ToolRef,
    adapt_tool,
    bind,
    build_registry,
    describe_params,
    tool_ref,
)
from backend.tools.runtime.gateway import (
    PermissionDeniedError,
    Sleeper,
    ToolGateway,
    TraceSink,
)
from backend.tools.runtime.models import (
    CostClass,
    DomainOutcome,
    ErrorKind,
    LatencyClass,
    PassStyle,
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
from backend.tools.runtime.schema import render_tool_schema

__all__ = [
    "CostClass",
    "DomainOutcome",
    "DuplicateCapabilityError",
    "ErrorKind",
    "LatencyClass",
    "PassStyle",
    "PermissionDeniedError",
    "RegisteredTool",
    "RetryPolicy",
    "SideEffect",
    "Sleeper",
    "ToolFn",
    "ToolGateway",
    "ToolRef",
    "ToolRegistry",
    "ToolResult",
    "ToolSpec",
    "TraceSink",
    "UnknownCapabilityError",
    "adapt_tool",
    "bind",
    "build_registry",
    "describe_params",
    "render_tool_schema",
    "reset_gateway",
    "shared_gateway",
    "tool_ref",
    "tool_schema_section",
    "tracing_to",
]
