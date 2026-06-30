"""Authentication utilities — token generation and validation."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from typing import Any

from pydantic import BaseModel

from backend.config.settings import Settings


class TokenData(BaseModel):
    """Token payload data."""

    token: str
    user_id: str
    username: str
    created_at: datetime
    expires_at: datetime


# In-memory token store (upgrade to Redis for production)
_active_tokens: dict[str, TokenData] = {}


def generate_token(user_id: str, username: str) -> TokenData:
    """Generate a new authentication token.

    Args:
        user_id: User identifier
        username: User name

    Returns:
        TokenData with token and metadata
    """
    settings = Settings().auth
    token = secrets.token_urlsafe(32)
    now = datetime.now()
    expires_at = now + timedelta(hours=settings.token_expire_hours)

    token_data = TokenData(
        token=token,
        user_id=user_id,
        username=username,
        created_at=now,
        expires_at=expires_at,
    )

    # Store token
    _active_tokens[token] = token_data

    return token_data


def validate_token(token: str) -> TokenData | None:
    """Validate an authentication token.

    Args:
        token: Token string to validate

    Returns:
        TokenData if valid, None if invalid/expired
    """
    token_data = _active_tokens.get(token)
    if not token_data:
        return None

    # Check expiry
    if token_data.expires_at < datetime.now():
        # Remove expired token
        _active_tokens.pop(token, None)
        return None

    return token_data


def revoke_token(token: str) -> bool:
    """Revoke (invalidate) a token.

    Args:
        token: Token to revoke

    Returns:
        True if token was revoked, False if not found
    """
    return _active_tokens.pop(token, None) is not None


def revoke_user_tokens(user_id: str) -> int:
    """Revoke ALL active tokens belonging to a user.

    Called when a user is deleted or has their password changed — without
    this, a stolen/issued token survives until natural expiry (default 24h).

    Returns the number of tokens revoked.
    """
    victims = [tok for tok, data in _active_tokens.items() if data.user_id == user_id]
    for tok in victims:
        _active_tokens.pop(tok, None)
    return len(victims)


async def verify_credentials_async(username: str, password: str) -> dict[str, Any] | None:
    """DB-backed credential verification — the only auth path.

    Returns the user on match, None otherwise. Errors propagate so the route
    layer can return a real 5xx instead of silently letting a hardcoded
    admin slip through.
    """
    from backend.db.console_users import verify_login

    user = await verify_login(username, password)
    if user is None:
        return None
    return {"id": user.id, "username": user.username}


__all__ = [
    "TokenData",
    "generate_token",
    "validate_token",
    "revoke_token",
    "revoke_user_tokens",
    "verify_credentials_async",
]
