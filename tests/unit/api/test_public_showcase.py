"""Contract tests for the public Showcase and Replay projection."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.api.routes.public_showcase import (
    _key_checkpoints,
    _public_id,
    _public_result,
    get_public_checkpoint_detail,
    get_public_replay_manifest,
    list_public_cases,
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
            limit=24, offset=0, q=None, mode=None, status=None, sort="recent"
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
        response = await get_public_replay_manifest("case-public", MagicMock(), False, None)

    assert response.data["view"] == "key"
    assert len(response.data["steps"]) == 2
    assert all("checkpoint_id" not in step for step in response.data["steps"])
    assert all("current_agent" not in step for step in response.data["steps"])


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
            "case-public", "step-public", MagicMock(), False, None
        )

    assert response.data["result"]["title"] == "标题"
    assert "error" not in response.data
    assert "raw_content" not in response.data["result"]
