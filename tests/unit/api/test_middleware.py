"""Tests for exception handling middleware."""

from unittest.mock import MagicMock

import pytest
from fastapi.responses import JSONResponse

from backend.api.errors import ErrorCode, WorkflowNotFoundError
from backend.api.middleware import error_handler_middleware


class MockRequest:
    """Mock FastAPI request."""

    def __init__(self):
        self.url = MagicMock()
        self.method = "GET"
        self.headers = {}


@pytest.mark.asyncio
async def test_api_error_handling():
    """Test APIError handling returns correct JSONResponse."""
    request = MockRequest()

    async def raise_api_error(req):
        raise WorkflowNotFoundError("test-thread-123")

    response = await error_handler_middleware(request, raise_api_error)

    assert isinstance(response, JSONResponse)
    assert response.status_code == 404

    # Check response body
    body = response.body.decode()
    import json

    data = json.loads(body)

    assert data["success"] is False
    assert data["error"]["code"] == ErrorCode.WORKFLOW_NOT_FOUND.value
    assert "test-thread-123" in data["error"]["message"]
    assert data["request_id"]  # Should have a request ID


@pytest.mark.asyncio
async def test_generic_exception_handling():
    """Test generic Exception handling returns 500 with INTERNAL_ERROR."""
    request = MockRequest()

    async def raise_generic_error(req):
        raise RuntimeError("Something went wrong")

    response = await error_handler_middleware(request, raise_generic_error)

    assert isinstance(response, JSONResponse)
    assert response.status_code == 500

    # Check response body
    body = response.body.decode()
    import json

    data = json.loads(body)

    assert data["success"] is False
    assert data["error"]["code"] == ErrorCode.INTERNAL_ERROR.value
    assert data["error"]["message"] == "Internal server error"
    # ponytail: raw exception text must NOT leak to the client `details`.
    assert data["error"]["details"] is None


@pytest.mark.asyncio
async def test_generic_exception_does_not_leak_raw_text():
    """Catch-all 500 must not leak raw exception text (paths/SQL/traceback)."""
    request = MockRequest()

    secret = "secret internal path /etc/passwd"

    async def raise_generic_error(req):
        raise RuntimeError(secret)

    response = await error_handler_middleware(request, raise_generic_error)

    body = response.body.decode()
    import json

    data = json.loads(body)

    # Generic message, no raw text in the client payload.
    assert data["error"]["message"] == "Internal server error"
    assert data["error"]["details"] is None
    assert secret not in body
    # request_id is still sent so support can cross-ref server logs.
    assert data["request_id"]
    assert len(data["request_id"]) == 8


@pytest.mark.asyncio
async def test_request_id_generation():
    """Test request ID is generated as 8-char UUID."""
    request = MockRequest()

    async def successful_call(req):
        return JSONResponse(content={"test": "data"})

    response = await error_handler_middleware(request, successful_call)

    # Request ID should be generated when error occurs
    async def raise_error(req):
        raise WorkflowNotFoundError("test-123")

    response = await error_handler_middleware(request, raise_error)
    body = response.body.decode()
    import json

    data = json.loads(body)

    # Request ID should be 8 characters
    assert len(data["request_id"]) == 8
    # Should be alphanumeric (from UUID)
    assert data["request_id"].isalnum()


@pytest.mark.asyncio
async def test_json_response_format():
    """Test JSONResponse format matches ApiResponse structure."""
    request = MockRequest()

    async def raise_api_error(req):
        raise WorkflowNotFoundError("format-test")

    response = await error_handler_middleware(request, raise_api_error)

    body = response.body.decode()
    import json

    data = json.loads(body)

    # Verify ApiResponse structure
    assert "success" in data
    assert "error" in data
    assert "request_id" in data
    assert "timestamp" in data

    # Verify ErrorDetail structure
    assert "code" in data["error"]
    assert "message" in data["error"]
    assert "details" in data["error"]
