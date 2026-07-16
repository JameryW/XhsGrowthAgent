"""Contract tests for the public Showcase and Replay projection."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.responses import Response

from backend.api.routes.public_showcase import (
    ShowcaseVisibilityUpdate,
    _key_checkpoints,
    _public_id,
    _public_result,
    _safe_colors,
    get_public_checkpoint_detail,
    get_public_replay_manifest,
    list_public_cases,
    revoke_showcase_visibility,
    update_showcase_visibility,
)
from backend.db.workflows import WorkflowRow


def _row(
    thread_id: str,
    *,
    visibility: str = "private",
    status: str = "completed",
    featured: bool = False,
) -> WorkflowRow:
    return WorkflowRow(
        thread_id=thread_id,
        account_id="internal-account",
        status=status,
        phase="completed",
        label="公开案例标题",
        workflow_mode="trend",
        showcase_visibility=visibility,
        showcase_featured=featured,
        created_at="2026-07-16T10:00:00Z",
        updated_at="2026-07-16T10:00:00Z",
    )


def test_public_result_is_allowlisted_and_redacts_internal_fields():
    result = _public_result(
        {
            "content_plan": {"selected_topic": "春日选题", "target_audience": "年轻用户"},
            "copy_content": {
                "selected_title": "可展示标题",
                "body_text": "这是公开摘要",
                "hashtags": ["春日", "生活方式"],
            },
            "analytics": {"views": 1234, "likes": 22, "provider_token": "secret"},
            "error": "auth_failed: provider token",
            "ripple_prediction": {"score_source": "internal", "viral_probability": 0.4},
        }
    )

    assert result["title"] == "可展示标题"
    assert result["metrics"] == {"views": 1234, "likes": 22}
    assert "error" not in result
    assert "provider_token" not in result
    assert "score_source" not in result["prediction"]


def test_public_result_rejects_unsafe_publish_urls():
    result = _public_result(
        {
            "publish_result": {
                "status": "published",
                "post_url": "javascript:alert(document.domain)",
            }
        }
    )

    assert result["publish"] == {"status": "published"}


def test_public_result_only_keeps_css_safe_palette_values():
    assert _safe_colors(
        ["#0f172a", "rgb(20, 184, 166)", "url(javascript:alert(1))", "{color:red}"]
    ) == ["#0f172a", "rgb(20, 184, 166)"]


def test_public_fixture_matrix_covers_release_states_and_redaction():
    fixture_path = Path(__file__).resolve().parents[2] / "fixtures" / "public_showcase_cases.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    cases = {item["name"]: item for item in fixture["cases"]}

    assert set(cases) == {
        "success",
        "in_progress",
        "publish_failed",
        "partial",
        "no_checkpoint",
        "offline",
        "revoked",
    }
    assert cases["revoked"]["visibility"] == "private"
    projected = _public_result(cases["success"]["state"])
    rendered = json.dumps(projected, ensure_ascii=False)
    assert "owner@example.com" not in rendered
    assert "13812345678" not in rendered
    assert "[已脱敏邮箱]" in rendered
    assert _public_result(cases["publish_failed"]["state"])["error_category"] == "authorization"
    assert _public_result(cases["offline"]["state"])["error_category"] == "service_unavailable"


def test_public_result_redacts_pii_and_unapproved_urls():
    result = _public_result(
        {
            "copy_content": {
                "selected_title": "联系 test@example.com 或 13812345678",
                "body_text": "内部标识 550e8400-e29b-41d4-a716-446655440000",
            },
            "publish_result": {
                "status": "published",
                "post_url": "https://evil.example/published",
            },
        }
    )

    rendered = " ".join(str(value) for value in result.values())
    assert "test@example.com" not in rendered
    assert "13812345678" not in rendered
    assert "550e8400-e29b-41d4-a716-446655440000" not in rendered
    assert "post_url" not in result["publish"]


def test_key_checkpoints_deduplicate_system_steps_by_business_phase():
    checkpoints = [
        {"checkpoint_id": "system", "step": 1, "phase": "idle", "current_agent": "orchestrator"},
        {
            "checkpoint_id": "scout",
            "step": 2,
            "phase": "scouting",
            "current_agent": "trend_scout",
            "trend_data": {"hot_topics": [{"topic": "AI"}]},
        },
        {
            "checkpoint_id": "scout-new",
            "step": 3,
            "phase": "scouting",
            "current_agent": "trend_scout",
            "trend_data": {"hot_topics": [{"topic": "AI 2"}]},
        },
        {
            "checkpoint_id": "copy",
            "step": 4,
            "phase": "creating",
            "current_agent": "copywriter",
            "copy_content": {"selected_title": "标题"},
        },
    ]

    result = _key_checkpoints(checkpoints)

    assert [item["checkpoint_id"] for item in result] == ["scout", "copy"]


@pytest.mark.asyncio
async def test_public_case_list_excludes_private_rows_and_uses_featured_fallback():
    public = _row("public-thread", visibility="public", featured=False)
    private = _row("private-thread", visibility="private", featured=True)

    with (
        patch("backend.api.routes.public_showcase.is_pool_ready", return_value=True),
        patch(
            "backend.api.routes.public_showcase.db_list",
            new_callable=AsyncMock,
            return_value=([public, private], 2),
        ),
    ):
        response = await list_public_cases(
            request=MagicMock(),
            response=Response(),
            limit=24,
            offset=0,
            q=None,
            mode=None,
            status=None,
            sort="recent",
        )

    assert response.data["total"] == 1
    assert response.data["cases"][0]["public_id"] == _public_id(public)
    assert response.data["featured_public_id"] == _public_id(public)
    assert "thread_id" not in response.data["cases"][0]
    assert "account_id" not in response.data["cases"][0]


@pytest.mark.asyncio
async def test_public_manifest_returns_key_steps_without_internal_identifiers():
    row = _row("public-thread", visibility="public")
    checkpoints = [
        {
            "checkpoint_id": "cp-1",
            "step": 1,
            "phase": "scouting",
            "current_agent": "trend_scout",
            "trend_data": {"hot_topics": [{"topic": "AI"}]},
        },
        {
            "checkpoint_id": "cp-2",
            "step": 2,
            "phase": "creating",
            "current_agent": "copywriter",
            "copy_content": {"selected_title": "标题"},
        },
    ]

    with (
        patch(
            "backend.api.routes.public_showcase._resolve_case",
            new_callable=AsyncMock,
            return_value=row,
        ),
        patch(
            "backend.api.routes.public_showcase._load_checkpoints",
            new_callable=AsyncMock,
            return_value=checkpoints,
        ),
        patch(
            "backend.api.routes.public_showcase._load_state",
            new_callable=AsyncMock,
            return_value={"status": "completed", "phase": "completed"},
        ),
    ):
        response = await get_public_replay_manifest(
            "case-public", MagicMock(), Response(), False, None
        )

    assert response.data["view"] == "key"
    assert len(response.data["steps"]) == 2
    assert all("checkpoint_id" not in step for step in response.data["steps"])
    assert all("current_agent" not in step for step in response.data["steps"])


@pytest.mark.asyncio
async def test_public_manifest_is_paginated_and_cacheable():
    row = _row("public-thread", visibility="public")
    checkpoints = [
        {
            "checkpoint_id": f"cp-{index}",
            "step": index,
            "phase": "creating",
            "current_agent": "copywriter",
            "copy_content": {"selected_title": f"标题 {index}"},
        }
        for index in range(3)
    ]
    request = MagicMock()
    request.headers = {}
    response_headers = Response()

    with (
        patch(
            "backend.api.routes.public_showcase._resolve_case",
            new_callable=AsyncMock,
            return_value=row,
        ),
        patch(
            "backend.api.routes.public_showcase._load_checkpoints",
            new_callable=AsyncMock,
            return_value=checkpoints,
        ),
    ):
        response = await get_public_replay_manifest(
            "case-public", request, response_headers, True, {"id": "user"}, 1, 1
        )

    assert response.data["offset"] == 1
    assert response.data["limit"] == 1
    assert response.data["total_steps"] == 3
    assert response.data["has_more"] is True
    assert response_headers.headers["Cache-Control"].startswith("public")
    assert response_headers.headers["ETag"]


@pytest.mark.asyncio
async def test_public_manifest_honors_conditional_etag_request():
    row = _row("public-thread", visibility="public")
    request = MagicMock()
    request.headers = {}
    first_response = Response()

    with (
        patch(
            "backend.api.routes.public_showcase._resolve_case",
            new_callable=AsyncMock,
            return_value=row,
        ),
        patch(
            "backend.api.routes.public_showcase._load_checkpoints",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        await get_public_replay_manifest("case-public", request, first_response, False, None)

    cached_request = MagicMock()
    cached_request.headers = {"if-none-match": first_response.headers["ETag"]}
    cached_response = Response()
    with (
        patch(
            "backend.api.routes.public_showcase._resolve_case",
            new_callable=AsyncMock,
            return_value=row,
        ),
        patch(
            "backend.api.routes.public_showcase._load_checkpoints",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        not_modified = await get_public_replay_manifest(
            "case-public", cached_request, cached_response, False, None
        )

    assert isinstance(not_modified, Response)
    assert not_modified.status_code == 304


@pytest.mark.asyncio
async def test_public_checkpoint_detail_has_no_raw_error_or_json_fallback():
    row = _row("public-thread", visibility="public")
    checkpoint = {
        "checkpoint_id": "cp-1",
        "step": 1,
        "phase": "creating",
        "current_agent": "copywriter",
        "copy_content": {"selected_title": "标题", "raw_content": '{"secret":true}'},
        "error": "auth_failed",
    }

    with patch(
        "backend.api.routes.public_showcase._resolve_checkpoint",
        new_callable=AsyncMock,
        return_value=(row, checkpoint),
    ):
        response = await get_public_checkpoint_detail(
            "case-public", "step-public", MagicMock(), Response(), False, None
        )

    assert response.data["result"]["title"] == "标题"
    assert "error" not in response.data
    assert "raw_content" not in response.data["result"]


@pytest.mark.asyncio
async def test_authenticated_operator_can_approve_and_revoke_case_visibility():
    row = _row("public-thread", visibility="private")
    updated = _row("public-thread", visibility="public", featured=True)
    current = {"id": "operator-1", "username": "reviewer"}
    payload = ShowcaseVisibilityUpdate(
        visibility="public",
        public_title="展示标题 test@example.com",
        public_summary="给用户看的摘要",
        featured=True,
        featured_rank=2,
    )

    with (
        patch(
            "backend.api.routes.public_showcase._resolve_any_case",
            new_callable=AsyncMock,
            return_value=row,
        ),
        patch(
            "backend.api.routes.public_showcase.db_update",
            new_callable=AsyncMock,
            return_value=updated,
        ) as db_update_mock,
    ):
        approved = await update_showcase_visibility("case-public", payload, current)

    kwargs = db_update_mock.await_args.kwargs
    assert kwargs["showcase_visibility"] == "public"
    assert kwargs["showcase_featured"] is True
    assert kwargs["featured_rank"] == 2
    assert kwargs["public_title"] == "展示标题 [已脱敏邮箱]"
    assert approved.data["approved_by"] == "reviewer"

    with (
        patch(
            "backend.api.routes.public_showcase._resolve_any_case",
            new_callable=AsyncMock,
            return_value=updated,
        ),
        patch(
            "backend.api.routes.public_showcase.db_update",
            new_callable=AsyncMock,
            return_value=_row("public-thread", visibility="private"),
        ) as db_update_mock,
    ):
        revoked = await revoke_showcase_visibility("case-public", current)

    assert db_update_mock.await_args.kwargs["showcase_visibility"] == "private"
    assert revoked.data == {
        "public_id": _public_id(updated),
        "visibility": "private",
        "revoked_by": "reviewer",
    }
