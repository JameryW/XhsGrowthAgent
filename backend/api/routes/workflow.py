"""Workflow API routes -- HTTP shape only.

P2c-S4 split the 3001-line module into layers; this file is the api layer:
the router, the request/response models (re-exported from ``_wf_models``) and
one thin handler per endpoint.  A handler may not touch the DB, the graph or
a file -- it forwards to the application layer and puts the result on the
wire.  ``tests/unit/api/test_workflow_layering.py`` pins that.

| layer | module |
|---|---|
| api | ``workflow.py`` (this file) |
| application | ``_wf_application.py`` |
| runtime | ``_wf_runtime.py`` |
| artifacts | ``_wf_artifacts.py`` |
| actions | ``_wf_actions.py`` |
| models | ``_wf_models.py`` |
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from backend.api.deps import get_current_user
from backend.api.responses import ApiResponse
from backend.api.routes import _wf_actions, _wf_application
from backend.api.routes._wf_models import RecoverRequest, WorkflowStartRequest

router = APIRouter()


# ── Endpoints ──


@router.post("/start")
async def start_workflow(
    req: WorkflowStartRequest,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """启动新的增长引擎工作流（必须使用当前用户拥有的账号）."""
    return await _wf_application.start_workflow(req, request, user)


@router.get("/status/{thread_id}")
async def get_workflow_status(
    thread_id: str,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """获取工作流状态"""
    return await _wf_application.get_workflow_status(thread_id, request, user)


@router.get("/history/{thread_id}")
async def get_checkpoint_history(
    thread_id: str,
    request: Request,
    limit: int = Query(20, ge=1, le=100, description="Max checkpoints to return"),
    before: str | None = Query(None, description="Checkpoint ID cursor for pagination"),
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """获取工作流的检查点历史记录（用于回放）"""
    return await _wf_application.get_checkpoint_history(thread_id, request, limit, before, user)


@router.post("/pause/{thread_id}")
async def pause_workflow(
    thread_id: str,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """暂停工作流"""
    return await _wf_application.pause_workflow(thread_id, request, user)


@router.post("/resume/{thread_id}")
async def resume_workflow(
    thread_id: str,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """恢复暂停或可重试错误的工作流"""
    return await _wf_application.resume_workflow(thread_id, request, user)


@router.post("/recover/{thread_id}")
async def recover_workflow(
    thread_id: str,
    req: RecoverRequest,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """显式恢复操作 — 把状态诊断变成可执行操作。

    仅 error/stale 状态可 recover。三种策略：
      - retry_failed: 等同 /resume error 路径（native ainvoke(None) 重跑失败 task）
      - retry_from_last_success: Command(goto=上次成功节点) 重跑该节点起的链
      - skip_to_next: Command(goto=state.next[0]) 跳过失败节点，从后继继续
    """
    return await _wf_application.recover_workflow(thread_id, req, request, user)


@router.post("/cancel/{thread_id}")
async def cancel_workflow(
    thread_id: str,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """取消工作流"""
    return await _wf_application.cancel_workflow(thread_id, request, user)


@router.get("/stream/{thread_id}")
async def stream_workflow_progress(thread_id: str, request: Request) -> StreamingResponse:
    """SSE 流式进度推送 — EventBus驱动

    Recovery: if the workflow is already in a terminal state (completed/error/
    cancelled) when the client connects, emit a synthetic terminal event
    immediately so the client doesn't hang waiting for a WORKFLOW_COMPLETED
    that was already broadcast before subscription. On reconnect (client sends
    the SSE-standard ``Last-Event-ID`` header), events missed since that seq
    are replayed first, scoped to this thread — mirroring the WebSocket
    ``get_missed?since=<seq>`` recovery path. Fresh connects skip the replay;
    full event recovery for dropped connections is the WebSocket path's job.
    """
    return await _wf_application.stream_workflow_progress(thread_id, request)


@router.get("/list")
async def list_workflows_endpoint(
    request: Request,
    account_id: str | None = Query(None, description="账号 ID（省略则用当前用户活跃账号）"),
    status: str | None = Query(None, description="筛选状态: running/completed/error/cancelled"),
    limit: int = Query(20, ge=1, le=100, description="返回数量限制"),
    offset: int = Query(0, ge=0, description="分页偏移"),
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """列出工作流 — 从 DB 查询，按创建时间倒序（单账号隔离，禁止全量聚合）."""
    return await _wf_application.list_workflows_endpoint(
        request, account_id, status, limit, offset, user
    )


@router.get("/account-totals")
async def workflow_account_totals(
    status: str | None = Query(
        None,
        description="可选：按状态计数（如 awaiting_review），省略则计全部工作流",
    ),
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """Return workflow counts for every account owned by the current user.

    Metadata-only (no workflow content). Powers history/review multi-account
    chip badges in a single round-trip instead of N× ``/list?limit=1`` probes.
    Still ownership-scoped: only the caller's accounts appear.
    """
    return await _wf_application.workflow_account_totals(status, user)


@router.delete("/{thread_id}")
async def delete_workflow(
    thread_id: str,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """删除工作流记录 — 只能删除已完成/已取消/出错的工作流"""
    return await _wf_application.delete_workflow(thread_id, request, user)


@router.post("/ripple-retry/{thread_id}")
async def retry_ripple_analysis(
    thread_id: str,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """重新运行 Ripple 传播预测和 PMF 验证（当之前超时或不可用时）"""
    return await _wf_actions.retry_ripple_analysis(thread_id, request, user)


@router.post("/brief/extract")
async def extract_brief_file(
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """Extract text from a brief document (PDF) without requiring a thread ID.

    Used by the frontend for immediate preview after file selection.
    The extracted text is then passed as briefText when starting the workflow.
    """
    return await _wf_application.extract_brief_file(request, user)


@router.post("/brief/upload/{thread_id}")
async def upload_brief_file(
    thread_id: str,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """Upload a brief document (PDF) and extract text content."""
    return await _wf_application.upload_brief_file(thread_id, request, user)


@router.get("/brief/export/{thread_id}")
async def export_shooting_plan(
    thread_id: str,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """Export shooting plan as formatted text (for copy/download)."""
    return await _wf_application.export_shooting_plan(thread_id, request, user)


@router.post("/images/upload/{thread_id}")
async def upload_images(
    thread_id: str,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """Upload images for a workflow (before publishing).

    Stored on disk, paths saved to visual_plan.image_paths.
    """
    return await _wf_application.upload_images(thread_id, request, user)


@router.post("/trigger-analytics/{thread_id}")
async def trigger_analytics(
    thread_id: str,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """手动触发 analyst 节点（发布后手动运行 Ripple 分析）"""
    return await _wf_application.trigger_analytics(thread_id, request, user)


@router.post("/publish-retry/{thread_id}")
async def retry_publish(
    thread_id: str,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """重试发布：用工作流现有内容重跑发布步骤，不重走创作链路。

    用于发布失败（status=failed/error）或试运行（mock_published）后手动重发。
    已发布的（status=published/success）拒绝，避免重复发笔记。
    P0-W4：status="unknown"（结果不明）先自动对账；对账确认已发布则不重发，
    对账不确定时拒绝重试，需请求体显式 {"force": true} 才继续（真实发布侧还有
    确定性 publish_id 幂等护栏兜底）。
    """
    return await _wf_actions.retry_publish(thread_id, request, user)
