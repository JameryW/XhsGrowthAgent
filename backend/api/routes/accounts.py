"""Account management API routes — CRUD for accounts and credentials."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from backend.api.errors import APIError, ErrorCode, ValidationError
from backend.api.responses import ApiResponse, success

logger = logging.getLogger("xhs_growth.api.accounts")

router = APIRouter()


# ── Request/Response models ──


class CreateAccountRequest(BaseModel):
    name: str
    is_active: bool = False


class UpdateAccountRequest(BaseModel):
    name: str | None = None
    is_active: bool | None = None
    chrome_profile_path: str | None = None
    cdp_port: int | None = None


class SetCredentialsRequest(BaseModel):
    credentials: dict[str, str]


# ── Account CRUD ──


@router.post("")
async def create_account(request: CreateAccountRequest) -> ApiResponse[Any]:
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
            "chrome_profile_path": account.chrome_profile_path,
            "cdp_port": account.cdp_port,
        }
    )


@router.get("")
async def list_accounts() -> ApiResponse[Any]:
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
                "chrome_profile_path": a.chrome_profile_path,
                "cdp_port": a.cdp_port,
            }
            for a in accounts
        ]
    )


@router.get("/active")
async def get_active_account() -> ApiResponse[Any]:
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
async def update_account(account_id: str, request: UpdateAccountRequest) -> ApiResponse[Any]:
    """Update an account's name, active status, or Chrome profile binding."""
    from backend.db.accounts import activate_credentials, set_active_account
    from backend.db.accounts import update_account as db_update

    # If setting active, use set_active_account which handles deactivation of others
    if request.is_active is True:
        account = await set_active_account(account_id)
        if account is None:
            raise AccountNotFoundError(account_id)
        await activate_credentials(account_id)
    else:
        fields: dict[str, Any] = {}
        if request.name is not None:
            if not request.name.strip():
                raise ValidationError("name", "Account name cannot be empty")
            fields["name"] = request.name.strip()
        if request.is_active is False:
            fields["is_active"] = False
        if request.chrome_profile_path is not None:
            fields["chrome_profile_path"] = request.chrome_profile_path.strip()
        if request.cdp_port is not None:
            if request.cdp_port < 0:
                raise ValidationError("cdp_port", "cdp_port must be non-negative")
            fields["cdp_port"] = request.cdp_port
        account = await db_update(account_id, **fields)
        if account is None:
            raise AccountNotFoundError(account_id)

    return success(
        data={
            "id": account.id,
            "name": account.name,
            "is_active": account.is_active,
            "chrome_profile_path": account.chrome_profile_path,
            "cdp_port": account.cdp_port,
        }
    )


@router.delete("/{account_id}")
async def delete_account(account_id: str) -> ApiResponse[Any]:
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
async def get_credentials(account_id: str) -> ApiResponse[Any]:
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
async def set_credentials(account_id: str, request: SetCredentialsRequest) -> ApiResponse[Any]:
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
async def delete_credential(account_id: str, key_name: str) -> ApiResponse[Any]:
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


# ── Scan-login (QR code) ──


@router.post("/{account_id}/login/qr")
async def start_qr_login(account_id: str) -> ApiResponse[Any]:
    """启动扫码登录：headless Chrome 开 www 登录页，拦截 qrcode/create.

    Returns:
        ``{qr_id, url, account_id}`` — 前端用 ``qrcode`` JS 库渲染 ``url``
        为矢量二维码。登录态 cookie 由 ``launch_persistent_context`` 写入
        ``account.chrome_profile_path``，launcher 常驻 CDP Chrome 复用。

    Raises:
        AccountNotFoundError: 账号不存在.
        ValidationError: 账号未绑定 chrome_profile_path.
    """
    from backend.db.accounts import get_account
    from backend.services.xhs_login import LoginError, get_or_create_session

    account = await get_account(account_id)
    if account is None:
        raise AccountNotFoundError(account_id)

    if not account.chrome_profile_path:
        raise ValidationError(
            "chrome_profile_path",
            "该账号未绑定 chrome_profile_path，无法扫码登录。"
            "创建账号时会自动分配（需设 XHS_CHROME_PROFILES_DIR），或经账号管理 API 设置。",
        )

    session = get_or_create_session(account_id, account.chrome_profile_path)
    try:
        result = await session.start()
    except LoginError as e:
        # LoginError 是预期内的启动失败（playwright 未装 / shield 拦截），
        # 返回 SERVICE_UNAVAILABLE 而非 500，让前端能区分"登录服务不可用"
        # 与"内部错误"。
        raise APIError(
            code=ErrorCode.SERVICE_UNAVAILABLE,
            message=str(e),
            details={"account_id": account_id},
            status_code=503,
        ) from e
    return success(data=result)


@router.get("/{account_id}/login/qr/status")
async def get_qr_login_status(account_id: str) -> ApiResponse[Any]:
    """查询扫码登录状态.

    Returns:
        ``{status, qr_id, url?, account_id}`` where status is one of:
        - ``waiting`` — 待扫码
        - ``scanned`` — 已扫待确认
        - ``confirmed`` — 已确认登录，cookie 已写 profile
        - ``expired`` — 二维码过期，已自动刷新，返回新 url

    Raises:
        AccountNotFoundError: 账号不存在.
        ValidationError: 账号未绑定 chrome_profile_path 或无进行中的登录会话.
    """
    from backend.db.accounts import get_account
    from backend.services.xhs_login import LoginError, get_session

    account = await get_account(account_id)
    if account is None:
        raise AccountNotFoundError(account_id)

    if not account.chrome_profile_path:
        raise ValidationError(
            "chrome_profile_path",
            "该账号未绑定 chrome_profile_path，无法扫码登录。",
        )

    session = get_session(account_id)
    if session is None:
        raise ValidationError(
            "login_session",
            "该账号没有进行中的扫码登录会话。先调用 POST /accounts/{id}/login/qr 启动。",
        )

    try:
        result = await session.get_status()
    except LoginError as e:
        raise APIError(
            code=ErrorCode.SERVICE_UNAVAILABLE,
            message=str(e),
            details={"account_id": account_id},
            status_code=503,
        ) from e
    return success(data=result)


@router.post("/{account_id}/login/qr/stop")
async def stop_qr_login(account_id: str) -> ApiResponse[Any]:
    """关闭扫码登录会话（profile 已落盘，可由 launcher 起常驻 CDP Chrome）.

    登录确认后调用此端点释放 headless Chrome。即使不调，进程退出时也会
    回收（profile 已持久化）。

    Raises:
        AccountNotFoundError: 账号不存在.
    """
    from backend.db.accounts import get_account
    from backend.services.xhs_login import stop_session

    account = await get_account(account_id)
    if account is None:
        raise AccountNotFoundError(account_id)

    stopped = await stop_session(account_id)
    return success(data={"stopped": stopped, "account_id": account_id})


# ── Error classes ──


class AccountNotFoundError(APIError):
    def __init__(self, account_id: str):
        super().__init__(
            code=ErrorCode.ACCOUNT_NOT_FOUND,
            message=f"Account '{account_id}' not found",
            details={"account_id": account_id},
            status_code=404,
        )
