"""Checkpoint serde: workflow enums must load without the unregistered-type warning.

Real runs (SQLite and Postgres) printed ``Deserializing unregistered type
backend.state.enums.WorkflowPhase … This will be blocked in a future version`` on
every resume. The allowlist declares exactly those two enums; everything else
keeps LangGraph's default behaviour.
"""

from __future__ import annotations

import logging

from backend.state.checkpoint_serde import ALLOWED_MSGPACK_MODULES, checkpoint_serde
from backend.state.enums import WorkflowMode, WorkflowPhase


def test_workflow_enums_round_trip_without_unregistered_warning(caplog):
    serde = checkpoint_serde()
    value = {"phase": WorkflowPhase.SCOUTING, "mode": WorkflowMode.TREND}

    type_name, payload = serde.dumps_typed(value)
    with caplog.at_level(logging.WARNING):
        loaded = serde.loads_typed((type_name, payload))

    assert loaded == value
    assert not [record for record in caplog.records if "unregistered type" in record.getMessage()]


def test_the_allowlist_names_only_the_workflow_enums():
    assert set(ALLOWED_MSGPACK_MODULES) == {
        ("backend.state.enums", "WorkflowPhase"),
        ("backend.state.enums", "WorkflowMode"),
    }


def test_dev_memory_checkpointer_uses_the_allowlisted_serde():
    from langgraph.checkpoint.memory import MemorySaver

    saver = MemorySaver(serde=checkpoint_serde())
    assert saver.serde is not None
