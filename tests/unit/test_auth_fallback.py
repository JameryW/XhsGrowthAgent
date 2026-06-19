"""Regression test: deleting a console user must actually deny that user login.

Bug: verify_credentials_async fell through to the legacy hardcoded admin
fallback whenever verify_login returned None — including when the user
existed but had been deleted, or when a password was simply wrong. The
fallback should ONLY trigger when the DB lookup itself raised.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_deleted_admin_cannot_login_via_legacy_fallback():
    """If the DB returns None, do NOT fall back to hardcoded admin/admin123."""
    from backend.api.auth import verify_credentials_async

    # Simulate DB working fine but reporting "no such user / wrong password"
    with patch("backend.db.console_users.verify_login", new=AsyncMock(return_value=None)):
        result = await verify_credentials_async("admin", "admin123")

    assert result is None, (
        "Hardcoded admin fallback must not activate when DB is healthy — "
        "this would let a deleted admin keep logging in."
    )


@pytest.mark.asyncio
async def test_db_failure_falls_back_to_legacy_admin():
    """If the DB raises (pool not ready / table missing), legacy admin still works.

    This is the only scenario where the fallback should fire — it's a
    bootstrap escape hatch, not a real auth path.
    """
    from backend.api.auth import verify_credentials_async

    with patch("backend.db.console_users.verify_login", new=AsyncMock(side_effect=RuntimeError("pool not ready"))):
        result = await verify_credentials_async("admin", "admin123")

    assert result is not None
    assert result["username"] == "admin"


@pytest.mark.asyncio
async def test_db_user_match_returns_user():
    """Happy path: DB-backed user matches → return their info."""
    from backend.api.auth import verify_credentials_async
    from backend.db.console_users import ConsoleUserRow

    fake_user = ConsoleUserRow(id="u-42", username="alice")
    with patch("backend.db.console_users.verify_login", new=AsyncMock(return_value=fake_user)):
        result = await verify_credentials_async("alice", "hunter2")

    assert result == {"id": "u-42", "username": "alice"}


if __name__ == "__main__":
    import asyncio
    asyncio.run(test_deleted_admin_cannot_login_via_legacy_fallback())
    asyncio.run(test_db_failure_falls_back_to_legacy_admin())
    asyncio.run(test_db_user_match_returns_user())
    print("All auth fallback tests passed")
