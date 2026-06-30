"""System-wide configuration — global secrets shared across XHS accounts."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.api.deps import get_current_user
from backend.api.responses import ApiResponse, success

logger = logging.getLogger("xhs_growth.api.system_config")

router = APIRouter()


class SetConfigRequest(BaseModel):
    config: dict[str, str]


@router.get("")
async def get_config(_: dict[str, Any] = Depends(get_current_user)) -> ApiResponse[Any]:
    """Return the full system config (values masked) plus key group hints."""
    from backend.db.system_config import (
        SYSTEM_KEY_GROUPS,
        SYSTEM_KEYS,
        SYSTEM_PARAM_KEYS,
        list_config,
    )

    rows = await list_config()
    by_key = {r.key_name: r for r in rows}

    # Always return all known keys (so the UI can render empty fields).
    items = [
        {
            "key_name": key,
            "masked_value": by_key[key].value
            if (key in SYSTEM_PARAM_KEYS and key in by_key)
            else (by_key[key].masked if key in by_key else ""),
            "is_set": key in by_key,
            "is_param": key in SYSTEM_PARAM_KEYS,
            "updated_at": by_key[key].updated_at if key in by_key else "",
        }
        for key in SYSTEM_KEYS
    ]

    return success(data={"items": items, "groups": SYSTEM_KEY_GROUPS})


@router.put("")
async def set_config(
    request: SetConfigRequest, _: dict[str, Any] = Depends(get_current_user)
) -> ApiResponse[Any]:
    """Batch-upsert system config. Empty values delete keys. Activates immediately."""
    from backend.db.system_config import (
        activate_system_config,
    )
    from backend.db.system_config import (
        set_config as db_set,
    )

    await db_set(request.config)
    # Hot reload into os.environ so running services pick up the change.
    await activate_system_config()
    return success(data={"updated_keys": list(request.config.keys())})
