"""Contract tests for the privacy-safe public UX telemetry receiver."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import FastAPI

from backend.api.routes.public_telemetry import (
    _rate_buckets,
    get_public_telemetry_summary,
    router,
)


@pytest.fixture(autouse=True)
def clear_rate_buckets():
    _rate_buckets.clear()
    yield
    _rate_buckets.clear()


@pytest.fixture
def app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api/public")
    return app


@pytest.mark.asyncio
async def test_receiver_accepts_only_allowlisted_categories_and_drops_unknown_fields(app):
    with (
        patch("backend.api.routes.public_telemetry.is_pool_ready", return_value=True),
        patch(
            "backend.api.routes.public_telemetry.record_event",
            new_callable=AsyncMock,
        ) as record,
    ):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/public/telemetry",
                json={
                    "event": "showcase_view",
                    "viewport": "mobile",
                    "source": "private-page",
                    "cached": True,
                    "duration_ms": 42,
                    "thread_id": "must-not-be-retained",
                },
            )

    assert response.status_code == 204
    assert record.await_args.args[0] == {
        "event": "showcase_view",
        "event_version": 1,
        "viewport": "mobile",
        "cached": True,
        "duration_ms": 42,
    }


@pytest.mark.asyncio
async def test_receiver_does_not_write_unknown_event(app):
    with (
        patch("backend.api.routes.public_telemetry.is_pool_ready", return_value=True),
        patch(
            "backend.api.routes.public_telemetry.record_event",
            new_callable=AsyncMock,
        ) as record,
    ):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/public/telemetry",
                json={"event": "user_email_and_internal_id"},
            )

    assert response.status_code == 204
    record.assert_not_awaited()


@pytest.mark.asyncio
async def test_summary_returns_aggregate_rows_without_raw_events():
    rows = [
        {
            "event_name": "replay_first_result_visible",
            "viewport": "mobile",
            "event_count": 3,
            "p75_duration_ms": 412.0,
        }
    ]
    with patch(
        "backend.api.routes.public_telemetry.summarize_events",
        new_callable=AsyncMock,
        return_value=rows,
    ) as summary:
        response = await get_public_telemetry_summary(
            days=7,
            event="replay_first_result_visible",
            _={"id": "operator-1"},
        )

    summary.assert_awaited_once_with(days=7, event_name="replay_first_result_visible")
    assert response.data == {"days": 7, "events": rows}
