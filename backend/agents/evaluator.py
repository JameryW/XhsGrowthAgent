"""EvaluatorAgent — 创作质量评估器 (基于 RQGM agent-as-a-judge 面板).

论文 arxiv 2606.26294 (Red Queen Gödel Machine) 核心方法：
- agent-as-a-judge 多评审面板（6 维：文案/视觉/合规/传播/受众 + 对抗偏倚检测）
- 对抗偏倚检测维度校准面板是否对 AI 生成内容过度宽容（论文 1.91x 纠偏）
- verifiable metric + judge signal 互补：LLM 给原始评分，代码用确定规则重算
  overall_score/decision，保证判定一致性。
"""

from __future__ import annotations

import logging
from typing import Any, cast

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.store.base import BaseStore

from backend.agents.base import BaseAgent
from backend.config.models import TaskType
from backend.state.enums import ContentStatus
from backend.state.schema import XHSGrowthState

logger = logging.getLogger("xhs_growth.agents.evaluator")

# 维度权重（compliance 由 is_blocking 单独兜底，不参与加权平均的拉高）
_DIMENSION_WEIGHTS: dict[str, float] = {
    "copywriting": 0.25,
    "visual": 0.20,
    "compliance": 0.20,
    "reach": 0.15,
    "audience": 0.20,
}

DEFAULT_PASS_THRESHOLD = 70.0
DEFAULT_REJECT_THRESHOLD = 50.0
# bias_check 低于此分视为检测到明显偏倚，对 overall 下调
_BIAS_PENALTY_THRESHOLD = 60.0
_BIAS_PENALTY = 5.0  # 偏倚下调分

_REQUIRED_DIMENSIONS = list(_DIMENSION_WEIGHTS.keys()) + ["bias_check"]


class EvaluatorAgent(BaseAgent):
    """创作质量评估器 — 发布前 AI 质量关卡."""

    task_type = TaskType.EVALUATION
    agent_name = "evaluator"
    prompt_file = "evaluator.yaml"

    async def execute(self, state: XHSGrowthState, store: BaseStore) -> dict[str, Any]:
        copy_content = state.get("copy_content") or {}
        visual_plan = state.get("visual_plan") or {}
        plan = state.get("content_plan") or {}

        # 无内容可评估 → 视为通过（降级，不阻断空流程）
        if not copy_content and not visual_plan:
            return {
                "evaluation_result": _empty_pass(),
                "phase": state.get("phase"),
            }

        # 受众偏好记忆召回（喂给 prompt 的 memory_context）
        account_id = state.get("account_id", "default")
        memory_context = await self._recall_memory(
            store,
            account_id,
            query=plan.get("selected_topic", "") or copy_content.get("selected_title", ""),
            namespace="audience_preferences",
            limit=3,
        )
        audience_ctx = ""
        for ap in memory_context:
            audience_ctx += f"- {ap.get('preference', '')}\n"

        system_prompt = self._build_system_prompt(state, extra_context=audience_ctx)
        ripple_context = self._build_ripple_context(state)

        user_msg = self.prompt_template["user_template"].format(
            selected_topic=plan.get("selected_topic", ""),
            content_angle=plan.get("content_angle", ""),
            target_audience=plan.get("target_audience", ""),
            content_type=plan.get("content_type", "note"),
            selected_title=copy_content.get("selected_title", ""),
            body_text=copy_content.get("body_text", ""),
            hashtags=copy_content.get("hashtags", []),
            cta=copy_content.get("cta", ""),
            tone=copy_content.get("tone", ""),
            cover_prompt=visual_plan.get("cover_prompt", ""),
            image_count=visual_plan.get("image_count", 0),
            image_prompts=visual_plan.get("image_prompts", []),
            layout_style=visual_plan.get("layout_style", ""),
            color_palette=visual_plan.get("color_palette", []),
            ripple_context=ripple_context,
            memory_context=audience_ctx,
        )

        response = await self.model.ainvoke(
            [SystemMessage(content=system_prompt), HumanMessage(content=user_msg)]
        )
        raw = self._parse_json_response(cast(str, response.content))

        result = self._build_evaluation_result(raw)
        logger.info(
            "Evaluation done: overall=%.1f decision=%s bias_warning=%s",
            result["overall_score"],
            result.get("decision"),
            bool(result.get("bias_warning")),
        )
        return {"evaluation_result": result}

    @staticmethod
    def _build_ripple_context(state: XHSGrowthState) -> str:
        """从 content_plan / ripple_prediction 提取传播预测上下文."""
        plan = state.get("content_plan") or {}
        prediction: dict[str, Any] = (
            cast("dict[str, Any]", plan.get("ripple_prediction"))
            or cast("dict[str, Any]", state.get("ripple_prediction"))
            or {}
        )
        pmf: dict[str, Any] = (
            cast("dict[str, Any]", plan.get("ripple_pmf"))
            or cast("dict[str, Any]", state.get("ripple_pmf"))
            or {}
        )
        if not prediction and not pmf:
            return "无 Ripple 传播预测数据"
        lines = []
        if prediction:
            lines.append(f"- 预计触达: {prediction.get('estimated_reach', 'N/A')}")
            lines.append(f"- 爆发概率: {prediction.get('viral_probability', 'N/A')}")
            lines.append(f"- verdict: {prediction.get('verdict', 'N/A')}")
        if pmf and pmf.get("risk_factors"):
            lines.append(f"- PMF 风险: {', '.join(pmf['risk_factors'])}")
        return "\n".join(lines) if lines else "无 Ripple 传播预测数据"

    def _build_evaluation_result(self, raw: dict[str, Any]) -> dict[str, Any]:
        """从 LLM 原始 JSON 构造标准化 EvaluationResult.

        用确定规则重算 overall_score/decision，不信任 LLM 自报值
        （verifiable metric + judge signal 互补）。
        """
        raw_dims = raw.get("dimensions") or []
        dims_by_name = {d.get("dimension"): d for d in raw_dims if isinstance(d, dict)}

        # 补齐缺失维度（LLM 漏返时给中性默认）
        dimensions: list[dict[str, Any]] = []
        for name in _REQUIRED_DIMENSIONS:
            d = dims_by_name.get(name)
            if d is None:
                d = {
                    "dimension": name,
                    "score": 70.0,
                    "rationale": "维度未返回，使用中性默认分",
                    "issues": [],
                    "is_blocking": False,
                }
            else:
                # 规范字段
                d = {
                    "dimension": name,
                    "score": _clamp(_to_float(d.get("score"), 70.0)),
                    "rationale": str(d.get("rationale", "")),
                    "issues": list(d.get("issues") or []),
                    "is_blocking": bool(d.get("is_blocking", False)),
                }
            dimensions.append(d)

        overall = self._compute_overall(dimensions)
        decision, revision_hints = self._compute_decision(
            overall, dimensions, raw.get("revision_hints") or []
        )

        bias_dim = next((d for d in dimensions if d["dimension"] == "bias_check"), None)
        bias_warning = ""
        if bias_dim and bias_dim["issues"]:
            bias_warning = "；".join(bias_dim["issues"])
        elif bias_dim and bias_dim["score"] < _BIAS_PENALTY_THRESHOLD:
            bias_warning = "检测到面板对 AI 生成内容可能过度宽容，已对综合分下调校准"

        return {
            "overall_score": round(overall, 1),
            "dimensions": dimensions,
            "decision": decision,
            "revision_hints": revision_hints,
            "bias_warning": bias_warning,
            "summary": str(raw.get("summary", "")),
        }

    @staticmethod
    def _compute_overall(dimensions: list[dict[str, Any]]) -> float:
        """加权平均 + 偏倚下调."""
        by_name = {d["dimension"]: d for d in dimensions}
        total = 0.0
        for name, weight in _DIMENSION_WEIGHTS.items():
            d = by_name.get(name)
            score = d["score"] if d else 70.0
            total += score * weight

        bias = by_name.get("bias_check")
        if bias and bias["score"] < _BIAS_PENALTY_THRESHOLD:
            total -= _BIAS_PENALTY
        return max(0.0, min(100.0, total))

    def _compute_decision(
        self,
        overall: float,
        dimensions: list[dict[str, Any]],
        raw_hints: list[Any],
    ) -> tuple[ContentStatus, list[str]]:
        """确定规则判定 decision（不信任 LLM 自报）."""
        has_blocking = any(d["is_blocking"] for d in dimensions)
        compliance = next((d for d in dimensions if d["dimension"] == "compliance"), None)

        if has_blocking or (compliance and compliance["score"] < DEFAULT_REJECT_THRESHOLD):
            decision = ContentStatus.REJECTED
        elif overall >= DEFAULT_PASS_THRESHOLD:
            decision = ContentStatus.APPROVED
        else:
            decision = ContentStatus.NEEDS_REVISION

        hints = [str(h) for h in raw_hints if h]
        if decision == ContentStatus.APPROVED:
            hints = []
        elif not hints:
            # 无 LLM hints 时从 issues 兜底；issues 也空则给一条综合兜底
            hints = self._hints_from_issues(dimensions) or [
                f"综合分 {overall:.0f} 低于发布阈值，建议全面优化文案与视觉表达"
            ]
        return decision, hints

    @staticmethod
    def _hints_from_issues(dimensions: list[dict[str, Any]]) -> list[str]:
        """从各维度 issues 兜底生成修订指令."""
        hints: list[str] = []
        for d in dimensions:
            if d["dimension"] == "bias_check":
                continue
            for issue in d["issues"]:
                hints.append(f"[{d['dimension']}] {issue}")
        return hints


def _empty_pass() -> dict[str, Any]:
    """无内容可评估时的降级通过结果."""
    return {
        "overall_score": 100.0,
        "dimensions": [
            {
                "dimension": name,
                "score": 100.0,
                "rationale": "无内容可评估，降级通过",
                "issues": [],
                "is_blocking": False,
            }
            for name in _REQUIRED_DIMENSIONS
        ],
        "decision": ContentStatus.APPROVED,
        "revision_hints": [],
        "bias_warning": "",
        "summary": "无内容可评估，自动通过",
    }


def _to_float(v: Any, default: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))
