import pytest
from xhs_growth.state.enums import WorkflowPhase, ContentStatus, ContentType, Urgency

def test_workflow_phase_values():
    assert WorkflowPhase.IDLE.value == "idle"
    assert WorkflowPhase.SCOUTING.value == "scouting"
    assert WorkflowPhase.COMPLETED.value == "completed"
    assert WorkflowPhase.ERROR.value == "error"

def test_content_status_values():
    assert ContentStatus.APPROVED.value == "approved"
    assert ContentStatus.NEEDS_REVISION.value == "needs_revision"
    assert ContentStatus.REJECTED.value == "rejected"

def test_enum_string_conversion():
    phase = WorkflowPhase.SCOUTING
    assert str(phase) == "scouting"
    assert phase == "scouting"

def test_enum_from_string():
    status = ContentStatus("approved")
    assert status == ContentStatus.APPROVED