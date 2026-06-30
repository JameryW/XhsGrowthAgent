"""Console user CRUD — admin login accounts."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.api.deps import get_current_user
from backend.api.errors import APIError, ErrorCode, ValidationError
from backend.api.responses import ApiResponse, success

logger = logging.getLogger("xhs_growth.api.console_users")

router = APIRouter()


class CreateUserRequest(BaseModel):
    username: str
    password: str


class UpdatePasswordRequest(BaseModel):
    password: str


class ConsoleUserNotFoundError(APIError):
    def __init__(self, user_id: str):
        super().__init__(
            code=ErrorCode.CONSOLE_USER_NOT_FOUND,
            message=f"Console user '{user_id}' not found",
            details={"user_id": user_id},
            status_code=404,
        )


class ConsoleUserDuplicateError(APIError):
    def __init__(self, username: str):
        super().__init__(
            code=ErrorCode.CONSOLE_USER_DUPLICATE,
            message=f"Username '{username}' already exists",
            details={"username": username},
            status_code=409,
        )


@router.get("")
async def list_users(_: dict[str, Any] = Depends(get_current_user)) -> ApiResponse[Any]:
    """List all console users (no password info)."""
    from backend.db.console_users import list_users as db_list

    users = await db_list()
    return success(
        data=[
            {
                "id": u.id,
                "username": u.username,
                "created_at": u.created_at,
                "last_login_at": u.last_login_at,
            }
            for u in users
        ]
    )


@router.post("")
async def create_user(
    request: CreateUserRequest, _: dict[str, Any] = Depends(get_current_user)
) -> ApiResponse[Any]:
    """Create a new console user."""
    if not request.username.strip():
        raise ValidationError("username", "Username cannot be empty")
    if len(request.password) < 6:
        raise ValidationError("password", "Password must be at least 6 characters")

    from backend.db.console_users import create_user as db_create
    from backend.db.console_users import get_user_by_username

    existing = await get_user_by_username(request.username.strip())
    if existing is not None:
        raise ConsoleUserDuplicateError(request.username.strip())

    user = await db_create(request.username.strip(), request.password)
    return success(
        data={
            "id": user.id,
            "username": user.username,
            "created_at": user.created_at,
        }
    )


@router.put("/{user_id}/password")
async def change_password(
    user_id: str,
    request: UpdatePasswordRequest,
    _: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """Change a user's password. All existing tokens for this user are revoked."""
    if len(request.password) < 6:
        raise ValidationError("password", "Password must be at least 6 characters")

    from backend.api.auth import revoke_user_tokens
    from backend.db.console_users import update_password

    ok = await update_password(user_id, request.password)
    if not ok:
        raise ConsoleUserNotFoundError(user_id)
    revoked = revoke_user_tokens(user_id)
    return success(data={"updated": True, "user_id": user_id, "revoked_sessions": revoked})


@router.delete("/{user_id}")
async def delete_user(
    user_id: str, current: dict[str, Any] = Depends(get_current_user)
) -> ApiResponse[Any]:
    """Delete a console user. Cannot delete yourself. Revokes all their tokens."""
    if user_id == current.get("id"):
        raise ValidationError("user_id", "Cannot delete your own account")

    from backend.api.auth import revoke_user_tokens
    from backend.db.console_users import count_users
    from backend.db.console_users import delete_user as db_delete

    if await count_users() <= 1:
        raise ValidationError("user_id", "Cannot delete the last remaining user")

    ok = await db_delete(user_id)
    if not ok:
        raise ConsoleUserNotFoundError(user_id)
    revoked = revoke_user_tokens(user_id)
    return success(data={"deleted": True, "user_id": user_id, "revoked_sessions": revoked})
