"""Checkpoint serializer with the project's enums explicitly allowlisted.

LangGraph's default permissive msgpack path logs a warning whenever a checkpoint
contains a type it does not know ("Deserializing unregistered type
backend.state.enums.WorkflowPhase … This will be blocked in a future version").
That warning appeared on every real workflow run through both the SQLite and the
Postgres checkpointer, and the future version it mentions would refuse to load
existing threads.  Declaring the two workflow enums as allowed removes the
warning without loosening the strict-msgpack mode: the allowlist is explicit,
everything else keeps the built-in behaviour.

Use this for every checkpointer the graph compiles (dev SQLite, in-memory, prod
Postgres) so a resumed thread reads the same types it wrote.
"""

from __future__ import annotations

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

# (module path, class name) — the exact keys the serializer's allowlist wants.
ALLOWED_MSGPACK_MODULES: tuple[tuple[str, ...], ...] = (
    ("backend.state.enums", "WorkflowPhase"),
    ("backend.state.enums", "WorkflowMode"),
)


def checkpoint_serde() -> JsonPlusSerializer:
    """A ``JsonPlusSerializer`` that accepts the workflow enums in checkpoints."""
    return JsonPlusSerializer(allowed_msgpack_modules=ALLOWED_MSGPACK_MODULES)
