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


def verify_credentials(username: str, password: str) -> dict[str, Any] | None:
    """Sync legacy fallback — only checks the hardcoded admin in settings.

    New code should use `verify_credentials_async` (DB-backed) below; this sync
    shim is kept so any external sync caller still gets the legacy behavior.
    """
    settings = Settings().auth
    if username == settings.admin_username and password == settings.admin_password:
        return {"id": "admin", "username": username}
    return None


async def verify_credentials_async(username: str, password: str) -> dict[str, Any] | None:
    """DB-backed credential verification. Falls back to legacy admin if DB is unavailable."""
    try:
        from backend.db.console_users import verify_login
        user = await verify_login(username, password)
        if user is not None:
            return {"id": user.id, "username": user.username}
    except Exception:
        # DB pool / table not ready — fall through.
        pass
    return verify_credentials(username, password)


__all__ = [
    "TokenData",
    "generate_token",
    "validate_token",
    "revoke_token",
    "verify_credentials",
    "verify_credentials_async",
]