"""Checkpoint serializer with every project enum explicitly allowlisted.

LangGraph's default permissive msgpack path logs a warning whenever a checkpoint
contains a type it does not know ("Deserializing unregistered type
backend.state.enums.WorkflowPhase … This will be blocked in a future version").
Declaring ``allowed_msgpack_modules`` switches that hook to **strict** mode: only
the SAFE built-in types and the listed ``(module, class)`` pairs deserialize,
everything else comes back as the raw value **and** logs "Blocked deserialization
… not in allowed_msgpack_modules".

So the allowlist must name *every* enum the workflow state can carry, not just the
workflow-control pair: ``evaluation_result["decision"]`` stores ``ContentStatus``,
``review_gate`` writes ``ContentStatus.APPROVED`` into ``human_feedback``, and the
brief/plan structures carry ``ContentType`` / ``Urgency`` / ``ExecutionMode``.
A missing entry silently downgrades that field to a bare string on resume (and
re-introduces the very warning this module exists to remove).

Use this for every checkpointer the graph compiles (dev SQLite, in-memory, prod
Postgres) so a resumed thread reads the same types it wrote.
"""

from __future__ import annotations

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

# (module path, class name) — the exact keys the serializer's allowlist wants.
# Keep in sync with ``backend.state.enums`` (the unit test pins the full set).
ALLOWED_MSGPACK_MODULES: tuple[tuple[str, str], ...] = (
    ("backend.state.enums", "WorkflowPhase"),
    ("backend.state.enums", "WorkflowMode"),
    ("backend.state.enums", "ContentStatus"),
    ("backend.state.enums", "ContentType"),
    ("backend.state.enums", "Urgency"),
    ("backend.state.enums", "ExecutionMode"),
)


def checkpoint_serde() -> JsonPlusSerializer:
    """A ``JsonPlusSerializer`` that accepts every project enum in checkpoints."""
    return JsonPlusSerializer(allowed_msgpack_modules=ALLOWED_MSGPACK_MODULES)
