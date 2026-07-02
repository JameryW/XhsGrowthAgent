# 审核页手动改文案 + 展示评估结果

## Goal
审核页（Review.vue）增加两个能力：
1. 手动修改文案（标题/正文），保存后直接覆盖 state.copy_content，并提供"基于此重生成"可选按钮
2. 展示评估 agent 生成的结果（evaluation_result），复用 EvaluationView 的雷达图 + 完整维度卡片嵌入审核页
3. 文案修改保存后自动重新跑 evaluator，保证评估结果与文案一致

## What I already know
- Review.vue 的 copy_content（line 575-600）是只读展示卡片，无编辑入口
- 审核 submit 走 `POST /api/review/submit/{thread_id}`，带 decision + revisions(list[str]) + publish_options
- revisions 是给 copywriter 的修改提示，不是直接覆盖文案
- evaluation_result 在 state（evaluator_gate 产出）：overall_score, dimensions(6维), decision, bias_warning, revision_hints
- EvaluationView.vue 有现成组件：EvaluationRadar（雷达图）、评分卡片、bias 卡片、维度标签
- 评估手动触发已有 `POST /api/evaluation/run/{thread_id}`（不推进工作流，仅评估当前内容）
- 评估结果读取已有 `GET /api/evaluation/result/{thread_id}`

## Decisions (已确认)
1. **文案提交**：直接覆盖 copy_content + 可选"基于此重生成"按钮（调 copywriter 用当前文案作 revision 提示重生成）
2. **评估展示**：复用 EvaluationView 的雷达图 + 完整维度卡片嵌入 Review 页
3. **改完文案**：自动重跑 evaluator（保存文案后触发评估，更新 evaluation_result）

## Open Questions
- 编辑权限边界：哪些工作流状态允许编辑文案？（awaiting_review only？还是更宽）
- 自动重跑评估的执行方式：同步等还是后台跑（evaluator LLM 调用耗时）

## Requirements (evolving)
- Review 页 copy_content 区域改为可编辑（标题 input、正文 textarea）
- 保存按钮 → 调新 API 覆盖 state.copy_content
- 保存成功后自动触发 evaluator 重跑，前端展示新评估结果
- "基于此重生成"按钮 → 调 copywriter 以当前文案为提示重新生成
- Review 页嵌入评估结果展示（雷达图 + 维度 + decision + bias + revision_hints）
- 复用 EvaluationRadar 等现有组件，不重复造

## Acceptance Criteria (evolving)
- [ ] 审核页可直接编辑标题/正文并保存
- [ ] 保存后 copy_content 被覆盖（state 验证）
- [ ] 保存后自动重跑 evaluator，evaluation_result 更新
- [ ] 审核页展示评估结果（雷达图 + 6 维度 + decision + bias）
- [ ] "基于此重生成"按钮触发 copywriter 重生成
- [ ] 仅 awaiting_review 工作流可编辑（边界待确认）

## Definition of Done
- 后端新 API + 测试
- 前端 Review.vue 改造 + 复用组件
- ruff/mypy/vue-tsc 全绿
- pytest 全过
- 端到端验证

## Out of Scope (explicit)
- 不改 evaluator 本身（6 维评分逻辑不变）
- 不改工作流拓扑（evaluator_gate 位置不变）
- 不改 EvaluationView 独立页面（保留，审核页是内嵌复用）

## Technical Notes
- 后端：新端点覆盖 copy_content（POST /api/review/update-copy/{thread_id} 或复用现有）
- 后端：保存后触发 evaluator（复用 EvaluatorAgent.execute 或 POST /api/evaluation/run）
- 前端：Review.vue 引入 EvaluationRadar + 维度卡片组件
- 前端：copy_content 卡片改可编辑 + 保存/重生成按钮
- evaluation_result 字段见 backend/state/schema.py EvaluationResult
