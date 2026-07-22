"""Contract tests for the privacy-safe public UX telemetry receiver."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import FastAPI

from backend.api.routes.public_telemetry import (
    _EVENT_NAMES,
    _rate_buckets,
    get_public_telemetry_summary,
    router,
)

# PR-1: public-page conversion funnel events added in this PR.
PR1_NEW_EVENTS = (
    "showcase_case_impression",
    "showcase_featured_open",
    "showcase_cta_click",
    "replay_step_navigate",
    "replay_result_expand",
    "replay_result_copy",
    "replay_share",
    "replay_cta_click",
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


@pytest.mark.asyncio
async def test_pr1_new_events_are_recorded(app):
    """Each PR-1 funnel event name is allowlisted and reaches the recorder."""
    for event_name in PR1_NEW_EVENTS:
        assert event_name in _EVENT_NAMES
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
                    json={"event": event_name, "viewport": "desktop"},
                )

        assert response.status_code == 204
        record.assert_awaited_once()
        assert record.await_args.args[0]["event"] == event_name


@pytest.mark.asyncio
async def test_pr1_new_categorical_fields_are_persisted_when_allowlisted(app):
    """auth_state/position/method with allowlisted values are retained."""
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
                    "event": "replay_cta_click",
                    "viewport": "mobile",
                    "auth_state": "authenticated",
                    "position": "hero",
                    "method": "click",
                },
            )

    assert response.status_code == 204
    payload = record.await_args.args[0]
    assert payload["event"] == "replay_cta_click"
    assert payload["auth_state"] == "authenticated"
    assert payload["position"] == "hero"
    assert payload["method"] == "click"


@pytest.mark.asyncio
async def test_authenticated_period_dimensions_are_persisted_without_raw_topic(app):
    """Analytics dimensions are categorical and raw topic text is rejected."""
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
                    "event": "analytics_period_change",
                    "viewport": "desktop",
                    "period": "weekly",
                    "old_period": "daily",
                    "topic": "这是一段不应进入遥测的原始内容",
                },
            )

    assert response.status_code == 204
    payload = record.await_args.args[0]
    assert payload["period"] == "weekly"
    assert payload["old_period"] == "daily"
    assert "topic" not in payload


@pytest.mark.asyncio
async def test_quality_consistency_events_are_allowlisted(app):
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
                    "event": "quality_raw_metric_mismatch",
                    "viewport": "desktop",
                    "source": "quality",
                    "count": 2,
                    "note_id": "must-not-be-retained",
                },
            )

    assert response.status_code == 204
    assert record.await_args.args[0]["event"] == "quality_raw_metric_mismatch"
    assert record.await_args.args[0]["source"] == "quality"
    assert record.await_args.args[0]["count"] == 2
    assert "note_id" not in record.await_args.args[0]


@pytest.mark.asyncio
async def test_pr1_categorical_fields_outside_allowlist_are_dropped_but_event_kept(app):
    """A bad auth_state/position/method is stripped; the event still records."""
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
                    "event": "showcase_cta_click",
                    "viewport": "desktop",
                    "auth_state": "logged-in-user",  # not allowlisted
                    "position": "navbar",  # not allowlisted
                    "method": "tap",  # not allowlisted
                    "source": "showcase",  # allowlisted, must survive
                },
            )

    assert response.status_code == 204
    record.assert_awaited_once()
    payload = record.await_args.args[0]
    assert payload["event"] == "showcase_cta_click"
    assert "auth_state" not in payload
    assert "position" not in payload
    assert "method" not in payload
    assert payload["source"] == "showcase"


@pytest.mark.asyncio
async def test_pr1_unknown_event_remains_silently_dropped(app):
    """A brand-new (non-PR-1) unknown event name still returns 204 without writing."""
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
                json={"event": "showcase_future_event_not_yet_allowlisted"},
            )

    assert response.status_code == 204
    record.assert_not_awaited()


@pytest.mark.asyncio
async def test_pr1_replay_source_is_allowlisted(app):
    """`source: 'replay'` (new for PR-1 replay attribution) is accepted."""
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
                    "event": "replay_cta_click",
                    "viewport": "desktop",
                    "source": "replay",
                },
            )

    assert response.status_code == 204
    payload = record.await_args.args[0]
    assert payload["source"] == "replay"
