import pytest
from datetime import datetime
from xhs_growth.api.responses import ApiResponse, success, error, ErrorDetail

def test_success_response():
    response = success({"thread_id": "test123"})
    assert response.success is True
    assert response.data == {"thread_id": "test123"}
    assert response.error is None
    assert isinstance(response.timestamp, datetime)

def test_error_response():
    response = error(
        code="ERROR_WORKFLOW_NOT_FOUND",
        message="Workflow not found",
        details={"thread_id": "test123"}
    )
    assert response.success is False
    assert response.data is None
    assert response.error.code == "ERROR_WORKFLOW_NOT_FOUND"
    assert response.error.message == "Workflow not found"
    assert response.error.details == {"thread_id": "test123"}

def test_api_response_serialization():
    response = ApiResponse(
        success=True,
        data={"phase": "scouting"},
        timestamp=datetime.now()
    )
    json_data = response.model_dump(mode="json")
    assert "success" in json_data
    assert "data" in json_data
    assert "timestamp" in json_data

def test_error_detail_str():
    detail = ErrorDetail(code="ERROR_TEST", message="Test error")
    assert str(detail) == "[ERROR_TEST] Test error"