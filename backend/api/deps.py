"""FastAPI dependencies for authentication."""

from __future__ import annotations

import hmac
import os
from typing import Any

from fastapi import Header

from backend.api.auth import validate_token
from backend.api.errors import TokenInvalidError, TokenMissingError

# Identity presented by trusted in-mesh callers (omp bridge / omp extension)
# that authenticate with the shared service token instead of a console user
# JWT.  Ownership checks in backend.api.account_scope bypass this identity.
SERVICE_USER_ID = "service:omp"
SERVICE_USERNAME = "omp-service"
SERVICE_TOKEN_ENV = "XHS_SERVICE_TOKEN"


def service_identity() -> dict[str, Any]:
    """Return the service identity dict for internal (non-HTTP) callers."""

    return {"id": SERVICE_USER_ID, "username": SERVICE_USERNAME, "service": True}


def is_service_identity(user: dict[str, Any] | None) -> bool:
    return user is not None and user.get("id") == SERVICE_USER_ID


def _service_token() -> str:
    return os.environ.get(SERVICE_TOKEN_ENV, "").strip()


async def get_current_user(
    authorization: str | None = Header(None, alias="Authorization"),
) -> dict[str, Any]:
    """Dependency that extracts and validates user from token.

    Accepts either a console user JWT or the shared service token
    (``XHS_SERVICE_TOKEN``) used by trusted in-mesh callers (omp bridge,
    omp extension) that have no console user context.

    Args:
        authorization: Authorization header value

    Returns:
        User dict with id and username (plus ``service: True`` for the
        service identity)

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

    if token_data:
        return {
            "id": token_data.user_id,
            "username": token_data.username,
        }

    service_token = _service_token()
    if service_token and hmac.compare_digest(token, service_token):
        return service_identity()

    raise TokenInvalidError("expired or invalid")


async def get_optional_user(
    authorization: str | None = Header(None, alias="Authorization"),
) -> dict[str, Any] | None:
    """Optional dependency - returns user if authenticated, None otherwise.

    Useful for routes that work both authenticated and anonymous.
    """
    if not authorization or not authorization.startswith("Bearer "):
        return None

    token = authorization.removeprefix("Bearer ")
    token_data = validate_token(token)

    if token_data:
        return {
            "id": token_data.user_id,
            "username": token_data.username,
        }

    service_token = _service_token()
    if service_token and hmac.compare_digest(token, service_token):
        return service_identity()

    return None


__all__ = [
    "SERVICE_USER_ID",
    "get_current_user",
    "get_optional_user",
    "is_service_identity",
    "service_identity",
]
