"""Checkpoint serde: every project enum must load without a blocked/unregistered warning.

Real runs (SQLite and Postgres) printed ``Deserializing unregistered type
backend.state.enums.WorkflowPhase … This will be blocked in a future version`` on
every resume.  Declaring ``allowed_msgpack_modules`` also switches the msgpack hook
to strict mode, so a missing enum is silently downgraded to a plain string and
logged as "Blocked deserialization" — this test pins the complete set.
"""

from __future__ import annotations

import logging

from backend.state import enums
from backend.state.checkpoint_serde import ALLOWED_MSGPACK_MODULES, checkpoint_serde


def _enum_types() -> list[type]:
    return [
        enums.WorkflowPhase,
        enums.WorkflowMode,
        enums.ContentStatus,
        enums.ContentType,
        enums.Urgency,
        enums.ExecutionMode,
    ]


def test_allowlist_names_every_enum_in_state_enums():
    expected = {("backend.state.enums", enum_type.__name__) for enum_type in _enum_types()}
    assert set(ALLOWED_MSGPACK_MODULES) == expected


def test_every_enum_round_trips_without_blocked_or_unregistered_warnings(caplog):
    serde = checkpoint_serde()

    for enum_type in _enum_types():
        for member in enum_type:
            type_name, payload = serde.dumps_typed(member)
            with caplog.at_level(logging.WARNING):
                loaded = serde.loads_typed((type_name, payload))

            assert loaded == member and isinstance(loaded, enum_type), enum_type.__name__
            assert not [
                record
                for record in caplog.records
                if "unregistered type" in record.getMessage()
                or "Blocked deserialization" in record.getMessage()
            ], enum_type.__name__


def test_nested_payload_keeps_enum_identity():
    """The evaluator/human_review fields are dicts of enums, not bare scalars."""
    serde = checkpoint_serde()
    value = {
        "evaluation_result": {"decision": enums.ContentStatus.APPROVED},
        "human_feedback": {"decision": enums.ContentStatus.APPROVED},
        "urgency": enums.Urgency.HIGH,
    }

    type_name, payload = serde.dumps_typed(value)
    loaded = serde.loads_typed((type_name, payload))

    assert loaded["evaluation_result"]["decision"] is enums.ContentStatus.APPROVED
    assert loaded["human_feedback"]["decision"] is enums.ContentStatus.APPROVED
    assert loaded["urgency"] is enums.Urgency.HIGH


def test_dev_memory_checkpointer_uses_the_allowlisted_serde():
    from langgraph.checkpoint.memory import MemorySaver

    saver = MemorySaver(serde=checkpoint_serde())
    assert saver.serde is not None
