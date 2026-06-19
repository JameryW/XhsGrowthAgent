"""Auth contract: DB is the only source of truth.

The legacy hardcoded admin fallback was removed entirely after a security
hole — `verify_login` returning None (user not found / wrong password) was
indistinguishable from `verify_login` raising (DB unavailable), so a
deleted admin kept being able to log in via the fallback. Now DB is the
sole arbiter and DB errors propagate.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_db_returns_none_means_reject():
    """No such user / wrong password → reject. No fallback exists anymore."""
    from backend.api.auth import verify_credentials_async

    with patch("backend.db.console_users.verify_login", new=AsyncMock(return_value=None)):
        result = await verify_credentials_async("admin", "admin123")

    assert result is None


@pytest.mark.asyncio
async def test_db_failure_propagates():
    """DB errors must propagate — there is no hardcoded admin escape hatch."""
    from backend.api.auth import verify_credentials_async

    with patch(
        "backend.db.console_users.verify_login",
        new=AsyncMock(side_effect=RuntimeError("pool not ready")),
    ), pytest.raises(RuntimeError, match="pool not ready"):
        await verify_credentials_async("admin", "admin123")


@pytest.mark.asyncio
async def test_db_user_match_returns_user():
    """Happy path: DB-backed user matches → return their info."""
    from backend.api.auth import verify_credentials_async
    from backend.db.console_users import ConsoleUserRow

    fake_user = ConsoleUserRow(id="u-42", username="alice")
    with patch("backend.db.console_users.verify_login", new=AsyncMock(return_value=fake_user)):
        result = await verify_credentials_async("alice", "hunter2")

    assert result == {"id": "u-42", "username": "alice"}


def test_legacy_verify_credentials_is_gone():
    """Static guarantee: the sync hardcoded-admin checker is no longer exported."""
    import backend.api.auth as auth_mod

    assert not hasattr(auth_mod, "verify_credentials"), (
        "Sync verify_credentials() was removed — its hardcoded admin/admin123 "
        "was a security hole. Use verify_credentials_async()."
    )


if __name__ == "__main__":
    import asyncio
    asyncio.run(test_db_returns_none_means_reject())
    asyncio.run(test_db_user_match_returns_user())
    test_legacy_verify_credentials_is_gone()
    print("All auth tests passed")
