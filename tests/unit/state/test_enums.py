from backend.state.enums import ContentStatus, WorkflowPhase


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
    # For str enums, phase.value gives the string value
    assert phase.value == "scouting"
    # The enum itself compares equal to its string value
    assert phase == "scouting"

def test_enum_from_string():
    status = ContentStatus("approved")
    assert status == ContentStatus.APPROVED