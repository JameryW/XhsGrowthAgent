"""Unified API response format."""
from datetime import datetime, timezone
from typing import Any, Generic, TypeVar
from pydantic import BaseModel

T = TypeVar("T")

class ApiResponse(BaseModel, Generic[T]):
    """Unified API response envelope."""
    success: bool
    data: T | None = None
    error: ErrorDetail | None = None
    timestamp: datetime = datetime.now(timezone.utc)
    request_id: str | None = None

class ErrorDetail(BaseModel):
    """Error detail structure."""
    code: str
    message: str
    details: dict[str, Any] | None = None

    def __str__(self) -> str:
        return f"[{self.code}] {self.message}"

def success(data: Any, request_id: str | None = None) -> ApiResponse:
    """Create success response."""
    return ApiResponse(success=True, data=data, request_id=request_id)

def error(
    code: str,
    message: str,
    details: dict | None = None,
    request_id: str | None = None,
) -> ApiResponse:
    """Create error response."""
    return ApiResponse(
        success=False,
        error=ErrorDetail(code=code, message=message, details=details),
        request_id=request_id,
    )