"""Account management API routes — CRUD for accounts and credentials."""

from __future__ import annotations

import logging

from fastapi import APIRouter
from pydantic import BaseModel

from backend.api.errors import APIError, ErrorCode, ValidationError
from backend.api.responses import success

logger = logging.getLogger("xhs_growth.api.accounts")

router = APIRouter()


# ── Request/Response models ──


class CreateAccountRequest(BaseModel):
    name: str
    is_active: bool = False


class UpdateAccountRequest(BaseModel):
    name: str | None = None
    is_active: bool | None = None


class SetCredentialsRequest(BaseModel):
    credentials: dict[str, str]


# ── Account CRUD ──


@router.post("")
async def create_account(request: CreateAccountRequest):
    """Create a new account."""
    if not request.name.strip():
        raise ValidationError("name", "Account name cannot be empty")

    from backend.db.accounts import create_account as db_create
    from backend.db.accounts import set_active_account

    account = await db_create(name=request.name.strip(), is_active=request.is_active)

    # If this is the first account or explicitly set active, activate it
    if request.is_active:
        await set_active_account(account.id)
        from backend.db.accounts import activate_credentials

        await activate_credentials(account.id)

    return success(
        data={
            "id": account.id,
            "name": account.name,
            "is_active": account.is_active,
            "created_at": account.created_at,
        }
    )


@router.get("")
async def list_accounts():
    """List all accounts."""
    from backend.db.accounts import list_accounts as db_list

    accounts = await db_list()
    return success(
        data=[
            {
                "id": a.id,
                "name": a.name,
                "is_active": a.is_active,
                "created_at": a.created_at,
                "updated_at": a.updated_at,
            }
            for a in accounts
        ]
    )


@router.get("/active")
async def get_active_account():
    """Get the currently active account."""
    from backend.db.accounts import get_active_account as db_get_active

    account = await db_get_active()
    if account is None:
        return success(data=None)
    return success(
        data={
            "id": account.id,
            "name": account.name,
            "is_active": account.is_active,
        }
    )


@router.put("/{account_id}")
async def update_account(account_id: str, request: UpdateAccountRequest):
    """Update an account's name or active status."""
    from backend.db.accounts import activate_credentials, set_active_account
    from backend.db.accounts import update_account as db_update

    # If setting active, use set_active_account which handles deactivation of others
    if request.is_active is True:
        account = await set_active_account(account_id)
        if account is None:
            raise AccountNotFoundError(account_id)
        await activate_credentials(account_id)
    else:
        fields = {}
        if request.name is not None:
            if not request.name.strip():
                raise ValidationError("name", "Account name cannot be empty")
            fields["name"] = request.name.strip()
        if request.is_active is False:
            fields["is_active"] = False
        account = await db_update(account_id, **fields)
        if account is None:
            raise AccountNotFoundError(account_id)

    return success(
        data={
            "id": account.id,
            "name": account.name,
            "is_active": account.is_active,
        }
    )


@router.delete("/{account_id}")
async def delete_account(account_id: str):
    """Delete an account and all its credentials."""
    from backend.db.accounts import deactivate_credentials, get_active_account
    from backend.db.accounts import delete_account as db_delete

    # Deactivate env vars if deleting the active account
    active = await get_active_account()
    if active and active.id == account_id:
        await deactivate_credentials()

    deleted = await db_delete(account_id)
    if not deleted:
        raise AccountNotFoundError(account_id)

    return success(data={"deleted": True, "account_id": account_id})


# ── Credentials ──


@router.get("/{account_id}/credentials")
async def get_credentials(account_id: str):
    """Get all credentials for an account (values masked)."""
    from backend.db.accounts import list_credentials as db_list

    creds = await db_list(account_id)
    return success(
        data=[
            {
                "key_name": c.key_name,
                "masked_value": c.masked,
                "is_set": bool(c.masked),
            }
            for c in creds
        ]
    )


@router.put("/{account_id}/credentials")
async def set_credentials(account_id: str, request: SetCredentialsRequest):
    """Batch-set credentials for an account. Empty values delete the key."""
    from backend.db.accounts import activate_credentials, get_active_account
    from backend.db.accounts import set_credentials as db_set

    await db_set(account_id, request.credentials)

    # If this is the active account, hot-reload into os.environ
    active = await get_active_account()
    if active and active.id == account_id:
        await activate_credentials(account_id)

    return success(data={"updated_keys": list(request.credentials.keys())})


@router.delete("/{account_id}/credentials/{key_name}")
async def delete_credential(account_id: str, key_name: str):
    """Delete a single credential."""
    import os

    from backend.db.accounts import delete_credential as db_delete
    from backend.db.accounts import get_active_account

    deleted = await db_delete(account_id, key_name)
    if not deleted:
        return success(data={"deleted": False, "message": "Credential not found"})

    # Remove from os.environ if this is the active account
    active = await get_active_account()
    if active and active.id == account_id:
        os.environ.pop(key_name, None)

    return success(data={"deleted": True, "key_name": key_name})


# ── Error classes ──


class AccountNotFoundError(APIError):
    def __init__(self, account_id: str):
        super().__init__(
            code=ErrorCode.ACCOUNT_NOT_FOUND,
            message=f"Account '{account_id}' not found",
            details={"account_id": account_id},
            status_code=404,
        )
