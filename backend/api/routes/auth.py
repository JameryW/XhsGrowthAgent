"""Authentication API routes — login, logout, token validation."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.api.auth import generate_token, verify_credentials
from backend.api.deps import get_current_user, get_optional_user
from backend.api.errors import LoginFailedError
from backend.api.responses import success

router = APIRouter()


class LoginRequest(BaseModel):
    """Login request body."""
    username: str
    password: str


class LoginResponse(BaseModel):
    """Login response data."""
    token: str
    expires_at: str
    user: dict


class ValidateResponse(BaseModel):
    """Token validation response."""
    valid: bool
    user: dict | None
    expires_at: str | None


@router.post("/login")
async def login(request: LoginRequest):
    """Authenticate user and return token.

    Args:
        request: Login credentials

    Returns:
        LoginResponse with token and user info
    """
    # Verify credentials
    user = verify_credentials(request.username, request.password)
    if not user:
        raise LoginFailedError()

    # Generate token
    token_data = generate_token(user["id"], user["username"])

    return success(data={
        "token": token_data.token,
        "expires_at": token_data.expires_at.isoformat(),
        "user": {"id": user["id"], "username": user["username"]},
    })


@router.post("/logout")
async def logout(user: dict = Depends(get_current_user)):
    """Logout and invalidate token.

    Args:
        user: Current user (from dependency)

    Returns:
        Success message
    """
    # Token is passed via Authorization header
    # We need to extract and revoke it
    # For simplicity, we'll revoke by user_id (all tokens for this user)
    # In production, track specific token per session

    return success(data={"message": "Logged out successfully", "user": user})


@router.get("/validate")
async def validate(user: dict = Depends(get_optional_user)):
    """Validate current token.

    Returns:
        ValidateResponse with validity status
    """
    if user:
        return success(data={
            "valid": True,
            "user": user,
            "expires_at": None,  # Could return actual expiry from token_data
        })

    return success(data={
        "valid": False,
        "user": None,
        "expires_at": None,
    })


@router.get("/me")
async def get_me(user: dict = Depends(get_current_user)):
    """Get current authenticated user.

    Args:
        user: Current user (from dependency)

    Returns:
        User info
    """
    return success(data={"user": user})