"""Authentication API routes — login, logout, token validation."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel

from backend.api.auth import generate_token, revoke_token, verify_credentials_async
from backend.api.deps import get_current_user, get_optional_user
from backend.api.errors import LoginFailedError
from backend.api.responses import ApiResponse, success

router = APIRouter()


class LoginRequest(BaseModel):
    """Login request body."""

    username: str
    password: str


class LoginResponse(BaseModel):
    """Login response data."""

    token: str
    expires_at: str
    user: dict[str, Any]


class ValidateResponse(BaseModel):
    """Token validation response."""

    valid: bool
    user: dict[str, Any] | None
    expires_at: str | None


@router.post("/login")
async def login(request: LoginRequest) -> ApiResponse[Any]:
    """Authenticate user and return token.

    Args:
        request: Login credentials

    Returns:
        LoginResponse with token and user info
    """
    # Verify credentials
    user = await verify_credentials_async(request.username, request.password)
    if not user:
        raise LoginFailedError()

    # Generate token
    token_data = generate_token(user["id"], user["username"])

    return success(
        data={
            "token": token_data.token,
            "expires_at": token_data.expires_at.isoformat(),
            "user": {"id": user["id"], "username": user["username"]},
        }
    )


@router.post("/logout")
async def logout(
    user: dict[str, Any] = Depends(get_current_user),
    authorization: str | None = Header(None, alias="Authorization"),
) -> ApiResponse[Any]:
    """Logout and invalidate the presented token.

    The token store is keyed by the token itself, so revoking the header value
    is what makes logout real: returning 200 without revoking left the same
    bearer token valid for /me and every other authenticated route.
    """
    token = (authorization or "").removeprefix("Bearer ").strip()
    revoked = bool(token) and revoke_token(token)

    return success(data={"message": "Logged out successfully", "user": user, "revoked": revoked})


@router.get("/validate")
async def validate(user: dict[str, Any] = Depends(get_optional_user)) -> ApiResponse[Any]:
    """Validate current token.

    Returns:
        ValidateResponse with validity status
    """
    if user:
        return success(
            data={
                "valid": True,
                "user": user,
                "expires_at": None,  # Could return actual expiry from token_data
            }
        )

    return success(
        data={
            "valid": False,
            "user": None,
            "expires_at": None,
        }
    )


@router.get("/me")
async def get_me(user: dict[str, Any] = Depends(get_current_user)) -> ApiResponse[Any]:
    """Get current authenticated user.

    Args:
        user: Current user (from dependency)

    Returns:
        User info
    """
    return success(data={"user": user})
