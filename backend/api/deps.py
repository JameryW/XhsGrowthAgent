"""FastAPI dependencies for authentication."""

from __future__ import annotations

from fastapi import Depends, Header

from backend.api.auth import validate_token
from backend.api.errors import TokenMissingError, TokenInvalidError


async def get_current_user(
    authorization: str | None = Header(None, alias="Authorization"),
) -> dict:
    """Dependency that extracts and validates user from token.

    Args:
        authorization: Authorization header value

    Returns:
        User dict with id and username

    Raises:
        TokenMissingError: If no Authorization header
        TokenInvalidError: If token is invalid or expired
    """
    if not authorization:
        raise TokenMissingError()

    # Extract Bearer token
    if not authorization.startswith("Bearer "):
        raise TokenInvalidError("invalid format")

    token = authorization.removeprefix("Bearer ")
    token_data = validate_token(token)

    if not token_data:
        raise TokenInvalidError("expired or invalid")

    return {
        "id": token_data.user_id,
        "username": token_data.username,
    }


async def get_optional_user(
    authorization: str | None = Header(None, alias="Authorization"),
) -> dict | None:
    """Optional dependency - returns user if authenticated, None otherwise.

    Useful for routes that work both authenticated and anonymous.
    """
    if not authorization or not authorization.startswith("Bearer "):
        return None

    token = authorization.removeprefix("Bearer ")
    token_data = validate_token(token)

    if not token_data:
        return None

    return {
        "id": token_data.user_id,
        "username": token_data.username,
    }


__all__ = ["get_current_user", "get_optional_user"]