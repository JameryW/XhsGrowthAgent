"""Account management API routes — CRUD for XHS accounts and QR login."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter
from pydantic import BaseModel

from backend.api.errors import APIError, ErrorCode, ValidationError
from backend.api.responses import ApiResponse, success

logger = logging.getLogger("xhs_growth.api.accounts")

router = APIRouter()

_QR_LOGIN_START_TIMEOUT_S = 10.0


async def _is_cdp_endpoint_up(cdp_endpoint: str) -> bool:
    """Return True when a per-account CDP endpoint answers /json/version."""
    if not cdp_endpoint:
        return False
    parsed = urlparse(cdp_endpoint)
    if not parsed.hostname or parsed.port is None:
        return False

    from backend.services.chrome_launcher import probe_port

    return await probe_port(parsed.port, host=parsed.hostname)


# ── Request/Response models ──


class CreateAccountRequest(BaseModel):
    name: str
    is_active: bool = False


class UpdateAccountRequest(BaseModel):
    name: str | None = None
    is_active: bool | None = None
    chrome_profile_path: str | None = None
    cdp_port: int | None = None
    niche: str | None = None
    niche_source: str | None = None


class ResolveNicheRequest(BaseModel):
    """Resolve account niche from history notes and/or manual override."""

    manual_niche: str = ""
    persist: bool = False


class SubmitVerificationCodeRequest(BaseModel):
    code: str


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

    return success(
        data={
            "id": account.id,
            "name": account.name,
            "is_active": account.is_active,
            "created_at": account.created_at,
            "chrome_profile_path": account.chrome_profile_path,
            "cdp_port": account.cdp_port,
            "niche": account.niche,
            "niche_source": account.niche_source,
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
                "niche": a.niche,
                "niche_source": a.niche_source,
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
            "created_at": account.created_at,
            "updated_at": getattr(account, "updated_at", None),
            "chrome_profile_path": account.chrome_profile_path,
            "cdp_port": account.cdp_port,
            "niche": account.niche,
            "niche_source": account.niche_source,
        }
    )


@router.put("/{account_id}")
async def update_account(account_id: str, request: UpdateAccountRequest) -> ApiResponse[Any]:
    """Update an account's name, active status, or Chrome profile binding."""
    from backend.db.accounts import set_active_account
    from backend.db.accounts import update_account as db_update

    # If setting active, use set_active_account which handles deactivation of others
    if request.is_active is True:
        account = await set_active_account(account_id)
        if account is None:
            raise AccountNotFoundError(account_id)
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
        if request.niche is not None:
            fields["niche"] = request.niche.strip()
            fields["niche_source"] = (
                request.niche_source.strip()
                if request.niche_source
                else ("manual" if fields["niche"] else "")
            )
        elif request.niche_source is not None:
            fields["niche_source"] = request.niche_source.strip()
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
            "niche": account.niche,
            "niche_source": account.niche_source,
        }
    )


@router.delete("/{account_id}")
async def delete_account(account_id: str) -> ApiResponse[Any]:
    """Delete an account."""
    from backend.db.accounts import delete_account as db_delete

    deleted = await db_delete(account_id)
    if not deleted:
        raise AccountNotFoundError(account_id)

    return success(data={"deleted": True, "account_id": account_id})


@router.post("/{account_id}/niche/resolve")
async def resolve_account_niche_route(
    account_id: str, body: ResolveNicheRequest
) -> ApiResponse[Any]:
    """Infer niche from imported note history, or apply manual niche override.

    Manual non-empty ``manual_niche`` always wins. Empty → keyword infer from
    creator-center note stats; no signal → cold_start.
    """
    from backend.db.accounts import get_account
    from backend.services.niche_resolver import resolve_account_niche

    account = await get_account(account_id)
    if account is None:
        raise AccountNotFoundError(account_id)

    result = await resolve_account_niche(
        account_id,
        manual_niche=body.manual_niche,
        cold_start_default="",
        persist=body.persist,
    )
    return success(
        data={
            "account_id": account_id,
            **result.to_dict(),
        }
    )


@router.get("/{account_id}/login/status")
async def get_account_login_status(account_id: str) -> ApiResponse[Any]:
    """Check whether the account's Chrome profile has a durable XHS login."""
    from backend.db.accounts import get_account, get_account_cdp_endpoint
    from backend.services.xhs_login import inspect_profile_login_status

    account = await get_account(account_id)
    if account is None:
        raise AccountNotFoundError(account_id)

    if not account.chrome_profile_path:
        return success(
            data={
                "account_id": account_id,
                "status": "unavailable",
                "is_logged_in": False,
                "reason": "missing_profile",
            }
        )

    cdp_endpoint = await get_account_cdp_endpoint(account_id)
    if not await _is_cdp_endpoint_up(cdp_endpoint or ""):
        return success(
            data={
                "account_id": account_id,
                "status": "unavailable",
                "is_logged_in": False,
                "reason": "cdp_port_down",
            }
        )

    result = await inspect_profile_login_status(account_id, cdp_endpoint or "")
    return success(data=result)


# ── Scan-login (QR code) ──


@router.post("/{account_id}/login/qr")
async def start_qr_login(account_id: str) -> ApiResponse[Any]:
    """启动扫码登录：connect_over_cdp 连 host 真实 Chrome，拦 qrcode/create.

    Returns:
        ``{qr_id, url, account_id}`` — 前端用 ``qrcode`` JS 库渲染 ``url``
        为矢量二维码。登录态写 host Chrome 的 user-data-dir
        (``account.chrome_profile_path``)，常驻 Chrome 后续 CDP 发布复用。

    Raises:
        AccountNotFoundError: 账号不存在.
        ValidationError: 账号未绑定 chrome_profile_path / cdp_port，或 host Chrome 未启动.
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

    from backend.db.accounts import get_account_cdp_endpoint

    cdp_endpoint = await get_account_cdp_endpoint(account_id)
    if not cdp_endpoint:
        raise ValidationError(
            "cdp_port",
            "该账号未绑定 cdp_port 或 host Chrome 未启动。先跑 scripts/chrome-profiles.sh start "
            "启动该账号的常驻 Chrome，再扫码登录。",
        )

    session = get_or_create_session(account_id, account.chrome_profile_path, cdp_endpoint)
    try:
        result = await asyncio.wait_for(session.start(), timeout=_QR_LOGIN_START_TIMEOUT_S)
    except TimeoutError as e:
        from backend.services.xhs_login import stop_session

        with contextlib.suppress(Exception):
            await asyncio.wait_for(stop_session(account_id), timeout=3.0)
        raise APIError(
            code=ErrorCode.SERVICE_UNAVAILABLE,
            message=(
                "启动扫码登录超时：小红书页面未能生成二维码。"
                "当前页面可能被安全限制拦截，请切换网络或稍后重试。"
            ),
            details={"account_id": account_id, "timeout_s": _QR_LOGIN_START_TIMEOUT_S},
            status_code=503,
        ) from e
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
        - ``confirmed`` — 已确认登录，登录态已写 profile
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


@router.post("/{account_id}/login/qr/verification-code")
async def submit_qr_verification_code(
    account_id: str, request: SubmitVerificationCodeRequest
) -> ApiResponse[Any]:
    """Submit a numeric web verification code into the active CDP login page."""
    from backend.db.accounts import get_account
    from backend.services.xhs_login import LoginError, get_session

    account = await get_account(account_id)
    if account is None:
        raise AccountNotFoundError(account_id)

    code = request.code.strip()
    if not code.isdigit() or not (4 <= len(code) <= 8):
        raise ValidationError("code", "验证码必须是 4-8 位数字")

    session = get_session(account_id)
    if session is None:
        raise ValidationError(
            "login_session",
            "该账号没有进行中的扫码登录会话。先调用 POST /accounts/{id}/login/qr 启动。",
        )

    try:
        result = await session.submit_verification_code(code)
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
