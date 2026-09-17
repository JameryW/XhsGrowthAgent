"""Workflow artifacts layer: history files, checkpoint snapshots, documents.

Everything that touches a file or turns stored state into a document: the
per-thread history JSON (written by the runner, read here), checkpoint
snapshots, uploaded brief/PDF text, the shooting-plan text and the phase
progress table.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from backend.api.routes._wf_models import CheckpointSnapshot
from backend.state.hydration import checkpoint_view, ripple_payload

logger = logging.getLogger(__name__)


# ── History files for completed workflow results ──
_HISTORY_DIR = Path(os.environ.get("XHS_REGISTRY_PATH", ".xhs")) / "history"


def _load_history_file(thread_id: str) -> dict[str, Any] | None:
    path = _HISTORY_DIR / f"{thread_id}.json"
    if path.exists():
        try:
            return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            logger.exception("Failed to load history for %s", thread_id)
    return None


PHASE_PROGRESS = {
    "idle": 0,
    "briefing": 15,
    "scouting": 10,
    "planning": 20,
    "creating": 40,
    "reviewing": 60,
    "publishing": 80,
    "analyzing": 90,
    "engaging": 95,
    "completed": 100,
    "error": 0,
    "paused": 0,
    "cancelled": 0,
}


def get_progress(phase: str) -> int:
    return PHASE_PROGRESS.get(phase, 0)


def _extract_ripple(values: dict[str, Any], key: str) -> dict[str, Any]:
    """Legacy ripple payload reader — implementation moved to
    backend.state.hydration.ripple_payload (single source)."""
    return ripple_payload(values, key)


def _get_ripple_progress(thread_id: str) -> dict[str, Any]:
    """Get current Ripple simulation progress for a thread from RippleService."""
    try:
        from backend.services.ripple_service import RippleService

        return RippleService.get_thread_progress(thread_id)
    except Exception:
        return {}


async def _snapshot_to_checkpoint(
    snapshot: Any,
    store: Any = None,
    thread_id: str = "",
) -> CheckpointSnapshot:
    """Convert a LangGraph StateSnapshot to a CheckpointSnapshot.

    P1a-S3: artifact refs are resolved first so /history keeps echoing the
    full inline stage view (D4) for ref'd threads; legacy threads pass
    through unchanged.
    """
    from backend.state.artifacts import resolve_state

    values = await resolve_state(store, thread_id, snapshot.values or {})
    meta = snapshot.metadata or {}
    checkpoint_id = ""
    if snapshot.config and snapshot.config.get("configurable"):
        checkpoint_id = snapshot.config["configurable"].get("checkpoint_id", "")
    return CheckpointSnapshot(
        checkpoint_id=checkpoint_id,
        step=meta.get("step", 0),
        source=meta.get("source", ""),
        phase=values.get("phase", "unknown"),
        current_agent=values.get("current_agent", ""),
        created_at=snapshot.created_at,
        next_nodes=list(snapshot.next) if snapshot.next else [],
        **checkpoint_view(values),
    )


async def _extract_pdf_text(content_bytes: bytes) -> tuple[str, dict[str, Any] | None]:
    """Extract text from PDF using pdfplumber, with multimodal LLM fallback.

    Returns the extracted text plus a kind:"llm" perf entry when the
    LLM fallback ran (None when pdfplumber succeeded — no LLM call made). The
    caller emits the entry to the Event store (P1a-S2).
    """
    try:
        import io

        import pdfplumber

        text_parts = []
        with pdfplumber.open(io.BytesIO(content_bytes)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                text_parts.append(page_text)

        extracted = "\n".join(text_parts).strip()
        if extracted:
            return extracted, None

        logger.info("PDF text extraction yielded no text, attempting multimodal LLM fallback")
        return await _extract_pdf_with_llm(content_bytes)
    except ImportError:
        logger.warning("pdfplumber not installed, using LLM fallback for PDF")
        return await _extract_pdf_with_llm(content_bytes)
    except Exception as e:
        logger.error(f"PDF extraction failed: {e}")
        return "", None


async def _extract_pdf_with_llm(content_bytes: bytes) -> tuple[str, dict[str, Any] | None]:
    """Extract text from PDF using multimodal LLM (for scanned documents).

    Captures token usage + cost via llm_perf_entry (best-effort: never breaks
    extraction) so the upload path can emit it to the Event store and the
    /analytics/costs reader sees the BRIEF_ANALYSIS token spend.
    """
    import base64

    from backend.agents.nodes._base import llm_perf_entry
    from backend.config.models import TaskType, get_model_id_for_task
    from backend.models.router import get_model

    model = get_model(TaskType.BRIEF_ANALYSIS.value)
    model_id = get_model_id_for_task(TaskType.BRIEF_ANALYSIS)
    b64 = base64.b64encode(content_bytes).decode()

    from langchain_core.messages import HumanMessage

    started = datetime.now(UTC).isoformat()
    try:
        response = await model.ainvoke(
            [
                HumanMessage(
                    content=[
                        {
                            "type": "text",
                            "text": "请提取这份PDF文档中的所有文字内容，保持原始格式。",
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:application/pdf;base64,{b64}"},
                        },
                    ]
                )
            ]
        )
    except Exception as e:
        logger.error(f"Multimodal LLM PDF extraction failed: {e}")
        return "", None

    completed = datetime.now(UTC).isoformat()
    text = cast(str, response.content or "")

    perf_entry: dict[str, Any] | None = None
    try:
        perf_entry = llm_perf_entry(
            "brief_pdf_extract",
            response,
            model_id,
            started_at=started,
            completed_at=completed,
        )
    except Exception as e:
        logger.error(f"brief_pdf_extract cost capture failed: {e}")

    return text, perf_entry


def _format_shooting_plan(plan: dict[str, Any]) -> str:
    """Format shooting plan dict into readable markdown text."""
    lines = []

    nickname = plan.get("creator_nickname", "")
    direction = plan.get("content_direction", "")
    type_label = plan.get("content_type_label", "")
    header = f"# {nickname}-{direction}-{type_label}" if nickname else f"# {direction}-{type_label}"
    lines.append(header)
    lines.append("")

    lines.append(f"主页链接：{plan.get('profile_link', '')}")
    lines.append(f"达人量级：{plan.get('creator_level', '')}")
    lines.append(f"预计发布日期：{plan.get('planned_publish_date', '')}")
    lines.append(f"内容方向：{direction}")
    lines.append(f"产品规格：{plan.get('product_specification', '')}")
    lines.append("")

    lines.append("---")
    lines.append("初稿👇")
    for req in plan.get("draft_requirements", []):
        lines.append(f"- {req}")
    for note in plan.get("draft_notes", []):
        lines.append(f"⚠️ {note}")
    lines.append("")

    lines.append("---")
    lines.append("大纲👇")
    titles = plan.get("title_candidates", [])
    lines.append(f"标题（至少给到{len(titles)}个备选）：")
    for i, title in enumerate(titles, 1):
        lines.append(f"{i}. {title}")
    lines.append("")
    lines.append(f"文案：\n{plan.get('body_copy', '')}")
    lines.append("")
    lines.append("话题：")
    lines.append(f"必带话题：{' '.join(plan.get('required_hashtags') or [])}")
    lines.append(f"选带话题：{' '.join(plan.get('optional_hashtags') or [])}")
    lines.append(f"其他热门话题：{' '.join(plan.get('suggested_hashtags') or [])}")
    lines.append("")

    lines.append("---")
    lines.append("拍摄服装")
    outfits = plan.get("outfits", {})
    for role, clothes in outfits.items():
        lines.append(f"\n{role}")
        for item in clothes:
            lines.append(f"- {item}")
    lines.append("")

    lines.append("---")
    lines.append("拍摄角度")
    for angle in plan.get("shooting_angles", []):
        lines.append(f"- {angle.get('description', '')}")

    return "\n".join(lines)
