"""Review gate node implementation - human-in-the-loop checkpoint."""

from __future__ import annotations

import logging
import os
from typing import Any, Literal

from langgraph.store.base import BaseStore
from langgraph.types import interrupt

from backend.agents.nodes._base import NodeResult, _check_cancelled
from backend.state.enums import ContentStatus, WorkflowPhase
from backend.state.schema import XHSGrowthState

logger = logging.getLogger("xhs_growth.graph.nodes")

# ── 低风险自动放行 ──
# 规则风险评估用，不调 LLM。敏感/违规风险词与高风险类目内联于此，
# 避免新增配置文件。命中即 high，永不自动放行。

_SENSITIVE_WORDS: tuple[str, ...] = (
    "处方",
    "处方药",
    "看病",
    "诊断",
    "治愈",
    "疗效",
    "投资",
    "理财",
    "荐股",
    "保证收益",
    "保本",
    "返利",
    "加微信",
    "加微",
    "私聊",
    "代购",
    "违禁",
    "黄赌毒",
    "色情",
    "赌博",
)

_HIGH_RISK_NICHES: tuple[str, ...] = (
    "医疗",
    "金融",
    "药品",
    "保健",
    "投资",
)

# 偏敏感但未达 high 的类目（缺免责时升 high，有免责仍 medium）
_MEDIUM_RISK_NICHES: tuple[str, ...] = (
    "母婴",
    "美妆",
    "护肤",
)

_MIN_TITLE_LEN = 5
_MIN_BODY_LEN = 20


def _auto_approve_enabled() -> bool:
    """读 AUTO_APPROVE_LOW_RISK 配置开关，默认 False（安全）。

    system_config 通过 activate_system_config() 推入 os.environ，故此处读 env。
    任何读取异常 → False（fail-safe，绝不误开自动发布）。
    """
    try:
        return os.environ.get("AUTO_APPROVE_LOW_RISK", "").strip().lower() in (
            "true",
            "1",
            "yes",
        )
    except Exception:
        return False


def _classify_publish_risk(
    state: XHSGrowthState | dict[str, Any],
) -> Literal["low", "medium", "high"]:
    """基于草稿内容特征算发布风险等级（纯规则，不调 LLM）。

    - high：敏感/违规词命中；或高风险类目（医疗/金融等）无免责声明
    - medium：缺图片、标题过短、正文过短、或偏敏感类目
    - low：以上均不满足（有图、标题正文合理、无敏感词、非敏感类目）
    """
    copy = state.get("copy_content") or {}
    visual = state.get("visual_plan") or {}
    niche = state.get("niche") or ""

    title = copy.get("selected_title") or ""
    body = copy.get("body_text") or ""
    image_paths = visual.get("image_paths") or []

    text_blob = f"{title}\n{body}"

    # high：敏感词命中
    for word in _SENSITIVE_WORDS:
        if word in text_blob:
            return "high"

    # high：高风险类目无免责声明
    if niche in _HIGH_RISK_NICHES and "免责" not in body and "不构成建议" not in body:
        return "high"

    # medium：缺图片
    if not image_paths:
        return "medium"

    # medium：标题过短
    if len(title) < _MIN_TITLE_LEN:
        return "medium"

    # medium：正文过短
    if len(body) < _MIN_BODY_LEN:
        return "medium"

    # medium：偏敏感类目
    if niche in _MEDIUM_RISK_NICHES:
        return "medium"

    return "low"


def _should_auto_approve(state: XHSGrowthState | dict[str, Any]) -> bool:
    """低风险 + 配置开 → 自动放行。high 永不放行。"""
    return _classify_publish_risk(state) == "low" and _auto_approve_enabled()


async def review_gate_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    """Human-in-the-loop review gate — dynamic interrupt() like ripple_gate.

    Flow:
    1. If low-risk + auto_approve_low_risk enabled, auto-approve → PUBLISHING
       (audit trace: human_feedback.source="auto_low_risk"). No interrupt.
    2. Otherwise, interrupt() for human review. On resume, read decision from
       the Command(resume=...) value, write human_feedback, set phase. The
       review_outcome router reads human_feedback.decision to route.

    Decision format (from Command(resume=decision)):
      {"decision": "approved", ...}       → PUBLISHING → evaluator_gate
      {"decision": "needs_revision", ...}  → CREATING → revise_content
      {"decision": "rejected", ...}        → ERROR (terminal)
    """
    _check_cancelled(state)

    if _should_auto_approve(state):
        logger.info("Low-risk draft + auto_approve_low_risk enabled, auto-approving")
        return NodeResult(
            {
                "human_feedback": {
                    "decision": ContentStatus.APPROVED,
                    "source": "auto_low_risk",
                },
                "phase": WorkflowPhase.PUBLISHING,
            },
            "review_gate",
        ).to_dict()

    # 非自动放行 — 暂停等人工审核。gate 字段供 derive_status 识别 awaiting_review。
    interrupt_payload = {
        "gate": "review",
        "review_summary": {
            "title": (state.get("copy_content") or {}).get("selected_title", ""),
            "has_images": bool((state.get("visual_plan") or {}).get("image_paths")),
            "risk": _classify_publish_risk(state),
        },
    }

    decision = interrupt(interrupt_payload)

    # decision 来自 submit_review 的 Command(resume=...)，是 ReviewDecision.model_dump()。
    # review_outcome 路由读 human_feedback.decision，故此处写入 state。
    raw_decision: Any = ContentStatus.REJECTED
    if decision and isinstance(decision, dict):
        raw_decision = decision.get("decision", ContentStatus.REJECTED)

    if raw_decision == ContentStatus.APPROVED or raw_decision == "approved":
        phase = WorkflowPhase.PUBLISHING
    elif raw_decision == ContentStatus.NEEDS_REVISION or raw_decision == "needs_revision":
        phase = WorkflowPhase.CREATING
    else:
        phase = WorkflowPhase.ERROR

    human_feedback = decision if isinstance(decision, dict) else {"decision": raw_decision}

    return NodeResult(
        {
            "human_feedback": human_feedback,
            "phase": phase,
        },
        "review_gate",
    ).to_dict()
