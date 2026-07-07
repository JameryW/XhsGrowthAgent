# Gate 自动通过规则 — 低风险发布草稿 review_gate 自动放行

## Goal

业务流程优化第 5 项：Gate 加自动通过规则。审计现状发现 3/4 规则已实现：
- ✅ Ripple 足够好自动接受（`ripple_gate_node`：viral>=0.4 且 pmf>=0.5 → auto-accept）
- ✅ 博主候选空自动跳过（`blogger_gate_router`：`blogger_skipped` → shooting_planner）
- ✅ 版本只有一个直接进视觉（`should_present_choice`：len(versions)<=1 → visual_designer）

仅缺：**低风险发布草稿 review_gate 自动放行**。本 task 补这一项。

## What I already know

- `review_gate_node`（`backend/agents/nodes/review_gate.py`）只设 phase=REVIEWING，靠 interrupt_before 暂停等人工
- `compile_graph_dev` interrupt_before 在 review_gate/choice_gate/draft_gate
- review_outcome router 读 `human_feedback.decision` 路由
- review_gate 无风险分类逻辑——所有草稿都暂停等审

## Requirements

- 加发布风险评分：基于草稿内容特征算 low/medium/high
  - low：无敏感词、非医疗/金融高风险类目、正文非空、有图片、标题长度合理
  - medium：缺图片或标题过短或类目偏敏感
  - high：含敏感词/违规风险词、医疗金融类目无免责
- review_gate_node 前置风险检查：low 风险 + `auto_approve_low_risk` 配置开 → 自动写 `human_feedback.decision="approved"` 跳过 interrupt
- 配置开关 `auto_approve_low_risk`（默认 False，安全）—— DB system_config 或 Settings，避免误开自动发布
- 自动放行要记 `review_source: "auto_low_risk"` 便于审计
- high 风险必须人工审，medium 人工审（保守）

## Acceptance Criteria

- [ ] 风险评分函数 + 单测（low/medium/high 各类输入）
- [ ] review_gate 自动放行路径：low + 配置开 → approved，跳 interrupt
- [ ] 配置关 → 行为同现状（全部暂停）
- [ ] 自动放行记 `review_source: "auto_low_risk"`
- [ ] high 风险永不自动放行
- [ ] 全量 pytest 绿，ruff/mypy 不新增错误

## Out of Scope

- Ripple/博主/版本三项自动通过（已实现）
- review_gate interrupt 机制改造（仍用 interrupt_before，只前置 auto-pass）
- 风险评分的 LLM 调用（用规则，不调 LLM，省成本+确定性）
- auto_approve 配置的 UI（system_config 表已有机制，本 task 只读）

## Technical Approach

- `backend/agents/nodes/review_gate.py`：加 `_classify_publish_risk(state) -> "low"|"medium"|"high"` 规则函数
- `review_gate_node`：if risk=="low" and `_auto_approve_enabled()` → return `{"human_feedback": {"decision": "approved", "source": "auto_low_risk"}, "phase": PUBLISHING}`（绕过 interrupt，review_outcome 直接路由 evaluator_gate）
- `_auto_approve_enabled()`：读 system_config `auto_approve_low_risk` 或 env，默认 False
- 敏感词表：放 `backend/config/sensitive_words.py` 或复用现有（查有无）

## Implementation Plan

- PR（本 task）：review_gate.py 加风险分类 + auto-pass + 单测
