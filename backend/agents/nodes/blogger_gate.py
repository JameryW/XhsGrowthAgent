"""Blogger gate node — interrupt for user to select a blogger."""

import json
import logging
from typing import Any, cast

from langchain_core.messages import HumanMessage
from langgraph.store.base import BaseStore
from langgraph.types import interrupt

from backend.agents.nodes._base import NodeResult, _check_cancelled
from backend.config.models import TaskType
from backend.models.router import get_model
from backend.state.enums import WorkflowPhase
from backend.state.schema import XHSGrowthState

logger = logging.getLogger("xhs_growth.graph.nodes")


async def blogger_gate_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    """Blogger selection gate — pauses for user to select a blogger from candidates.

    Uses dynamic interrupt() to pause only when candidates exist.
    If no candidates exist, skip interrupt and proceed.

    Selection format (from Command(resume=selection)):
      {"user_id": "...", "nickname": "..."}  — selected blogger
      {"skip": true}                         — user skipped selection
    """
    _check_cancelled(state)

    candidates = state.get("blogger_candidates", [])

    # No candidates — skip gate entirely
    if not candidates:
        logger.info("No blogger candidates, skipping blogger_gate")
        return NodeResult(
            {
                "blogger_skipped": True,
                "selected_blogger": {},
                "blogger_notes": [],
                "phase": WorkflowPhase.CREATING,
            },
            "blogger_gate",
        ).to_dict()

    # Candidates exist — interrupt for user selection
    interrupt_payload = {
        "gate": "blogger",
        "blogger_candidates": candidates,
    }
    decision = interrupt(interrupt_payload)

    # User skipped selection
    if not decision or (isinstance(decision, dict) and decision.get("skip")):
        logger.info("User skipped blogger selection")
        return NodeResult(
            {
                "blogger_skipped": True,
                "selected_blogger": {},
                "blogger_notes": [],
                "phase": WorkflowPhase.CREATING,
            },
            "blogger_gate",
        ).to_dict()

    # User selected a blogger — fetch their top notes
    selected_user_id = decision.get("user_id", "") if isinstance(decision, dict) else ""
    if not selected_user_id:
        logger.warning("No user_id in blogger selection, skipping note fetch")
        return NodeResult(
            {
                "selected_blogger": decision if isinstance(decision, dict) else {},
                "blogger_notes": [],
                "phase": WorkflowPhase.CREATING,
            },
            "blogger_gate",
        ).to_dict()

    note_limit = state.get("blogger_note_limit", 3)
    blogger_notes = await _fetch_blogger_notes(state, selected_user_id, note_limit)

    selected = decision if isinstance(decision, dict) else {"user_id": selected_user_id}
    logger.info(
        f"User selected blogger: {selected.get('nickname', selected_user_id)}, "
        f"fetched {len(blogger_notes)} notes"
    )

    return NodeResult(
        {
            "selected_blogger": selected,
            "blogger_notes": blogger_notes,
            "phase": WorkflowPhase.CREATING,
        },
        "blogger_gate",
    ).to_dict()


async def _fetch_blogger_notes(
    state: XHSGrowthState,
    user_id: str,
    limit: int,
) -> list[dict[str, Any]]:
    """Fetch a blogger's top notes sorted by engagement.

    For mock bloggers (mock_ prefix), generates simulated notes via LLM.
    """
    # Mock blogger — generate simulated notes via LLM
    if user_id.startswith("mock_"):
        return await _generate_mock_notes(state, user_id, limit)

    logger.info("Generating simulated notes for selected blogger")
    return await _generate_mock_notes(state, user_id, limit)


async def _generate_mock_notes(
    state: XHSGrowthState,
    user_id: str,
    limit: int,
) -> list[dict[str, Any]]:
    """Generate simulated blogger notes via LLM for mock bloggers."""
    nickname = ""
    candidates = state.get("blogger_candidates", [])
    for c in candidates:
        if c.get("user_id") == user_id:
            nickname = c.get("nickname", "")
            break

    niche = state.get("niche", "母婴")
    brief_content = state.get("brief_content") or {}
    brief_ctx = ""
    if brief_content.get("brand_name"):
        brief_ctx += f"品牌: {brief_content['brand_name']}. "
    if brief_content.get("product_name"):
        brief_ctx += f"产品: {brief_content['product_name']}. "
    if brief_content.get("content_direction"):
        brief_ctx += f"方向: {brief_content['content_direction'][:80]}. "

    prompt = (
        f"生成{limit}篇小红书笔记模拟数据（JSON格式，不要有其他文字）。\n"
        f"博主：{nickname or user_id}，赛道：{niche}。\n"
        f"商单上下文：{brief_ctx or '无'}\n\n"
        f'输出格式：{{"notes": [{{"note_id": "mock_note_001", '
        f'"title": "笔记标题", "body": "笔记正文前100字", '
        f'"hashtags": ["话题1"], "likes": 500, '
        f'"collects": 200, "comments": 50, '
        f'"engagement_rate": 0.15}}]}}\n'
        f"只输出JSON。"
    )

    try:
        model = get_model(TaskType.MOCK_GEN.value)
        response = await model.ainvoke([HumanMessage(content=prompt)])
        content = response.content
        if isinstance(content, list):
            content = str(content)

        # Parse JSON
        if "```json" in content:
            json_str = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            json_str = content.split("```")[1].split("```")[0].strip()
        else:
            json_str = content.strip()

        parsed = json.loads(json_str)
        notes = cast(list[dict[str, Any]], parsed.get("notes", []))

        # Ensure required fields
        for i, n in enumerate(notes):
            n.setdefault("note_id", f"mock_note_{i + 1}")
            n.setdefault("title", "")
            n.setdefault("body", "")
            n.setdefault("hashtags", [])
            n.setdefault("likes", 0)
            n.setdefault("collects", 0)
            n.setdefault("comments", 0)
            n.setdefault("engagement_rate", 0.0)
            n.setdefault("cover_url", "")

        logger.info(f"Generated {len(notes)} mock notes for {nickname or user_id}")
        return notes[:limit]

    except Exception as e:
        logger.warning(f"Mock note generation failed: {e}")
        return []
