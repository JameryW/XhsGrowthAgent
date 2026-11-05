"""Request-body helpers shared by the workflow action routes.

Several resume/retry endpoints accept an *optional* JSON object body.  The
``request.json()`` call raises ``JSONDecodeError`` for an empty body even when
the caller still sent ``Content-Type: application/json`` (some HTTP clients do),
which surfaced as an unhandled 500 instead of the endpoint's documented
"empty body means no decision" behaviour.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request
from starlette.requests import ClientDisconnect


async def json_object_body(request: Request) -> dict[str, Any]:
    """Return a JSON object body, treating absent/invalid bodies as ``{}``."""
    if not request.headers.get("content-type", "").startswith("application/json"):
        return {}
    try:
        parsed: Any = await request.json()
    except (ValueError, ClientDisconnect):
        return {}
    return parsed if isinstance(parsed, dict) else {}


__all__ = ["json_object_body"]
