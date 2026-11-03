"""Exception handling middleware."""

import logging
import uuid

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import RequestResponseEndpoint

from backend.api.errors import APIError, ErrorCode
from backend.api.responses import error
from backend.db.pool import DatabaseUnavailableError

logger = logging.getLogger("xhs_growth.api")


async def error_handler_middleware(
    request: Request, call_next: RequestResponseEndpoint
) -> Response:
    """Unified exception handling middleware."""
    request_id = str(uuid.uuid4())[:8]
    try:
        response = await call_next(request)
        return response
    except APIError as e:
        logger.warning(f"API Error [{request_id}]: {e.code.value} - {e.message}")
        return JSONResponse(
            status_code=e.status_code,
            content=e.to_response(request_id).model_dump(mode="json"),
        )
    except DatabaseUnavailableError as e:
        # Graph-only dev mode (no POSTGRES_URI) has no app DB layer; every
        # auth/account endpoint would otherwise 500 with a traceback. 503 +
        # explicit code tells the operator the deployment is missing Postgres.
        logger.warning(f"DB unavailable [{request_id}]: {e}")
        return JSONResponse(
            status_code=503,
            content=error(
                code=ErrorCode.DB_UNAVAILABLE.value,
                message=(
                    "The application database layer is not initialized in this "
                    "deployment (POSTGRES_URI is not configured); login and "
                    "account endpoints require Postgres"
                ),
                details=None,
                request_id=request_id,
            ).model_dump(mode="json"),
        )
    except Exception as e:
        logger.exception(f"Unexpected error [{request_id}]: {e}")
        return JSONResponse(
            status_code=500,
            content=error(
                code=ErrorCode.INTERNAL_ERROR.value,
                message="Internal server error",
                # ponytail: raw str(e) leaks internals (paths/SQL/traceback) to
                # the client; full detail is preserved in logger.exception above
                # and request_id lets support cross-ref the server logs.
                details=None,
                request_id=request_id,
            ).model_dump(mode="json"),
        )
