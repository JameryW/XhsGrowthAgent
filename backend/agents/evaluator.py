"""EvaluatorAgent — 创作质量评估器 (基于 RQGM agent-as-a-judge 面板).

论文 arxiv 2606.26294 (Red Queen Gödel Machine) 核心方法：
- agent-as-a-judge 多评审面板（10 维：文案/视觉/合规/传播/受众/AI味儿/图片质量/
  商业味儿/利他性 + 对抗偏倚检测）
- 对抗偏倚检测维度校准面板是否对 AI 生成内容过度宽容（论文 1.91x 纠偏）
- verifiable metric + judge signal 互补：LLM 给原始评分，代码用确定规则重算
  overall_score/decision，保证判定一致性。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, cast

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.store.base import BaseStore

from backend.agents.base import BaseAgent
from backend.config.models import TaskType
from backend.db.evaluator_config import (
    BIAS_SEVERITY_NOTES,
    EvaluatorWeights,
    get_active_epoch,
    load_weights,
)
from backend.state.enums import ContentStatus
from backend.state.schema import XHSGrowthState

logger = logging.getLogger("xhs_growth.agents.evaluator")

# 维度权重（compliance 由 is_blocking 单独兜底，不参与加权平均的拉高）
# Keep in sync with backend.db.evaluator_config.DEFAULT_DIMENSION_WEIGHTS
_DIMENSION_WEIGHTS: dict[str, float] = {
    "copywriting": 0.18,
    "visual": 0.13,
    "compliance": 0.14,
    "reach": 0.13,
    "audience": 0.13,
    "ai_taste": 0.08,
    "image_quality": 0.07,
    "commercial_tone": 0.05,
    "altruism": 0.09,
}

# Below this score, ensure revision_hints name 利他性 with actionable advice
_ALTRUISM_HINT_THRESHOLD = 65.0

DEFAULT_PASS_THRESHOLD = 70.0
DEFAULT_REJECT_THRESHOLD = 50.0
# bias_severity 高于此值视为检测到明显偏倚，对 overall 下调
_BIAS_PENALTY_THRESHOLD = 60.0
_BIAS_PENALTY = 5.0  # 偏倚下调分

_REQUIRED_DIMENSIONS = list(_DIMENSION_WEIGHTS.keys()) + ["bias_check"]


class EvaluatorAgent(BaseAgent):
    """创作质量评估器 — 发布前 AI 质量关卡."""

    task_type = TaskType.EVALUATION
    agent_name = "evaluator"
    prompt_file = "evaluator.yaml"

    def __init__(self) -> None:
        super().__init__()
        # ponytail: defaults = module constants; overridden per-account from DB at
        # execute time. Falls back to defaults when DB unavailable (tests / no PG).
        self._weights: EvaluatorWeights = EvaluatorWeights()
        self._bias_severity: str = "standard"

    async def _resolve_weights(self, account_id: str) -> EvaluatorWeights:
        """Load per-account weights + active prompt epoch from DB; fall back on failure."""
        try:
            self._weights = await load_weights(account_id)
        except Exception as e:
            logger.debug("weight load failed, using defaults: %s", e)
            self._weights = EvaluatorWeights()
        try:
            epoch = await get_active_epoch()
            self._bias_severity = epoch.bias_severity
        except Exception as e:
            logger.debug("epoch load failed, using standard: %s", e)
            self._bias_severity = "standard"
        return self._weights

    def _build_system_prompt(self, state: XHSGrowthState, extra_context: str = "") -> str:
        """Override to inject DB weights + epoch bias_severity into the prompt.

        ponytail: prompt previously hardcoded weights/thresholds; now synced from
        DB so LLM self-reported overall aligns with code-recomputed overall. Uses
        .replace (not .format) because the prompt body contains literal {} in the
        JSON output example.
        """
        template = self.prompt_template.get("system", "")
        niche = state.get("niche", "母婴")
        template = template.replace("{account_niche}", niche)
        template = template.replace("{memory_context}", extra_context)
        # weights block: "copywriting 0.20, visual 0.15, ..."
        weights_block = ", ".join(
            f"{k} {v:.2f}" for k, v in self._weights.dimension_weights.items()
        )
        template = template.replace("{weights_block}", weights_block)
        template = template.replace("{pass_threshold}", f"{self._weights.pass_threshold:.0f}")
        template = template.replace("{reject_threshold}", f"{self._weights.reject_threshold:.0f}")
        template = template.replace(
            "{bias_severity_note}", BIAS_SEVERITY_NOTES.get(self._bias_severity, "")
        )
        return template

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

        account_id = state.get("account_id", "default")
        await self._resolve_weights(account_id)
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

        # ponytail: ainvoke 无内置 timeout；astron-code-latest 不稳时会挂起整个
        # review submit 请求（HTTP 长连接等待，不抛异常），evaluator_node 的 try/except
        # 捕不到 → 降级放行失效。60s 上限：超时抛 TimeoutError → node except 捕获 → 降级。
        try:
            response = await asyncio.wait_for(
                self.model.ainvoke(
                    [SystemMessage(content=system_prompt), HumanMessage(content=user_msg)]
                ),
                timeout=60.0,
            )
        except TimeoutError as e:
            logger.warning("Evaluator LLM 调用超时(60s)，降级放行: %s", e)
            from backend.state.enums import ContentStatus

            return {
                "evaluation_result": {
                    "overall_score": 100.0,
                    "dimensions": [],
                    "decision": ContentStatus.APPROVED,
                    "revision_hints": [],
                    "bias_warning": "",
                    "summary": f"评估器 LLM 超时，降级放行: {e}",
                    # degraded flag: this is a pass-through fallback (LLM failed),
                    # NOT a real evaluation — callers must not trust the 100/approved.
                    # free-mode evaluate_draft persists it so /draft + /drafts + the
                    # agent render can surface the degradation instead of showing a
                    # fake "100 approved" verdict.
                    "degraded": True,
                }
            }
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
        for name in self._weights.required_dimensions:
            raw_d = dims_by_name.get(name)
            if raw_d is None:
                d = {
                    "dimension": name,
                    "score": 70.0,
                    "rationale": "维度未返回，使用中性默认分",
                    "issues": [],
                    "is_blocking": False,
                }
            else:
                # 规范字段（从原始 raw_d 提取，丢弃未知字段）
                d = {
                    "dimension": name,
                    "score": _clamp(_to_float(raw_d.get("score"), 70.0)),
                    "rationale": str(raw_d.get("rationale", "")),
                    "issues": list(raw_d.get("issues") or []),
                    "is_blocking": bool(raw_d.get("is_blocking", False)),
                }
            # bias_check 维度保留偏倚严重度（驱动 overall 下调 + epoch 演化）。
            # score=校准建议分（越高越无需调整），bias_severity=偏倚严重度（越高越糟）。
            # 语义相反，故 LLM 漏返 bias_severity 时回退 100 - score。
            if name == "bias_check":
                sev = _to_float(raw_d.get("bias_severity") if raw_d else None, -1.0)
                if sev < 0:
                    sev = 100.0 - _clamp(_to_float(d.get("score"), 70.0))
                d["bias_severity"] = _clamp(sev)
            dimensions.append(d)

        overall = self._compute_overall(dimensions)
        decision, revision_hints = self._compute_decision(
            overall, dimensions, raw.get("revision_hints") or []
        )

        bias_dim = next((d for d in dimensions if d["dimension"] == "bias_check"), None)
        bias_warning = ""
        if bias_dim and bias_dim["issues"]:
            bias_warning = "；".join(bias_dim["issues"])
        elif bias_dim and bias_dim.get("bias_severity", 0) >= self._weights.bias_penalty_threshold:
            bias_warning = "检测到面板对 AI 生成内容可能过度宽容，已对综合分下调校准"

        return {
            "overall_score": round(overall, 1),
            "dimensions": dimensions,
            "decision": decision,
            "revision_hints": revision_hints,
            "bias_warning": bias_warning,
            "summary": str(raw.get("summary", "")),
        }

    def _compute_overall(self, dimensions: list[dict[str, Any]]) -> float:
        """加权平均 + 偏倚下调.

        bias_severity 高（检测到明显偏倚）→ 对 overall 下调。
        不再用 bias_check.score（其语义为"校准建议分"，方向与 severity 相反）。
        """
        by_name = {d["dimension"]: d for d in dimensions}
        total = 0.0
        for name, weight in self._weights.dimension_weights.items():
            d = by_name.get(name)
            score = d["score"] if d else 70.0
            total += score * weight

        bias = by_name.get("bias_check")
        if bias and bias.get("bias_severity", 0) >= self._weights.bias_penalty_threshold:
            total -= self._weights.bias_penalty
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

        if has_blocking or (compliance and compliance["score"] < self._weights.reject_threshold):
            decision = ContentStatus.REJECTED
        elif overall >= self._weights.pass_threshold:
            decision = ContentStatus.APPROVED
        else:
            decision = ContentStatus.NEEDS_REVISION

        hints = [str(h) for h in raw_hints if h]
        if decision == ContentStatus.APPROVED:
            # Surface 利他性 tips even when overall passed but altruism is weak
            return decision, self._altruism_suggestions(dimensions)

        if not hints:
            # 无 LLM hints 时从 issues 兜底；issues 也空则给一条综合兜底
            hints = self._hints_from_issues(dimensions) or [
                f"综合分 {overall:.0f} 低于发布阈值，建议全面优化文案与视觉表达"
            ]
        # Ensure low-altruism always yields named, actionable revision advice
        altruism_hints = self._altruism_suggestions(dimensions)
        for h in altruism_hints:
            if h not in hints:
                hints.insert(0, h)
        return decision, hints

    @staticmethod
    def _altruism_suggestions(dimensions: list[dict[str, Any]]) -> list[str]:
        """Actionable 利他性 suggestions when score is weak or issues present."""
        d = next((x for x in dimensions if x.get("dimension") == "altruism"), None)
        if d is None:
            return []
        score = float(d.get("score") or 0)
        issues = [str(i) for i in (d.get("issues") or []) if i]
        if score >= _ALTRUISM_HINT_THRESHOLD and not issues:
            return []
        hints: list[str] = []
        for issue in issues:
            line = f"[altruism/利他性] {issue}"
            if line not in hints:
                hints.append(line)
        if score < _ALTRUISM_HINT_THRESHOLD:
            defaults = [
                "[altruism/利他性] 补充 2-3 条读者可直接照做的具体方法或步骤，减少纯自我展示",
                "[altruism/利他性] 明确说明这篇笔记能帮读者解决什么问题，避免空泛种草话术",
            ]
            for h in defaults:
                if h not in hints:
                    hints.append(h)
        return hints

    @staticmethod
    def _hints_from_issues(dimensions: list[dict[str, Any]]) -> list[str]:
        """从各维度 issues 兜底生成修订指令."""
        hints: list[str] = []
        for d in dimensions:
            if d["dimension"] == "bias_check":
                continue
            for issue in d["issues"]:
                prefix = d["dimension"]
                if prefix == "altruism":
                    prefix = "altruism/利他性"
                hints.append(f"[{prefix}] {issue}")
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
