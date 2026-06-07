# Ripple 分析后重新选题能力

## Goal

当 Ripple 传播预测和 PMF 验证结果不理想时，给用户提供重新选题的选择：要么回退到 trend_scout 完全换话题，要么保留趋势数据换角度重新规划策略。用户有明确的选择权，而非系统自动处理。

## What I already know

* `content_strategist` 在 viral_probability < 0.3 时会自动用 Ripple 洞察重新生成策略（第164-180行），但用户无法控制这个过程
* LangGraph 已有 `interrupt_before` 机制：`review_gate`, `choice_gate`, `draft_gate`, `brief_gate`
* Gate node 使用 `interrupt(None)` 或 `interrupt({...})` 接收用户决策，通过 `Command(resume=decision)` 恢复
* 后端已有 `submit_review` 端点处理 review_gate 决策（approve/needs_revision）
* 后端已有 `retry_ripple_analysis` 端点但仅重试超时/不可用的情况，不支持基于结果重新选题
* 前端 `RipplePanel` 已有 retry 按钮（仅在 fallback 状态显示），但不支持"重新选题"
* 图拓扑：content_strategist → copywriter → draft_gate → viral_matcher → ...
* 回退路由已有 precedent：`revise_content → copywriter` 是回退到上一个节点
* 图中有 `should_continue` 路由：analyst → orchestrator（回到起点）

## Assumptions (temporary)

* "重新选题"应该在 Ripple 结果展示后触发，用户看完数据再决定
* 需要新增一个 `ripple_gate` 中断节点（类似 draft_gate），让用户决定是否接受当前选题
* 回退到 trend_scout 需要 LangGraph 支持"回退到之前节点"——可以用 aupdate_state + as_node 实现

## Open Questions

* ~~重新选题的触发时机：是 content_strategist 节点完成后自动中断，还是用户手动触发？~~ → **条件中断**：仅当 Ripple 结果不理想时才中断
* ~~"换角度"时是否需要再次运行 Ripple 模拟验证新角度？~~ → 是，但设上限 2 次循环，超过后自动继续

## Requirements (evolving)

* Ripple 分析完成后，展示结果的同时提供用户决策选项：
  - **接受当前选题** — 继续进入 copywriter 流程
  - **换角度重新规划** — 保留趋势数据，让 content_strategist 基于新方向重新规划
  - **换话题** — 回退到 trend_scout 重新搜索趋势
* 仅当 Ripple 结果不理想时（viral_probability < 0.4 或 pmf_score < 0.5），在 ripple_gate 中断等待用户决策。结果好时自动继续，不打断流程
* 前端 RipplePanel 或新增决策面板展示三个选项
* 后端新增 `ripple_gate` 中断节点和对应 API 端点
* 图拓扑新增 `content_strategist → ripple_gate` 边
* Brief 模式下 `brief_analyzer → ripple_gate` 同样适用
* ripple_gate 添加到 `interrupt_before` 列表
* 条件中断阈值：viral_probability < 0.4 或 pmf_score < 0.5
* 重新选题循环上限 2 次（state 中 `reselect_count`），换角度和换话题都计入

## Acceptance Criteria (evolving)

* [ ] Ripple 分析完成后，工作流在 ripple_gate 处中断等待用户决策
* [ ] 前端展示三个选项（接受/换角度/换话题）
* [ ] 用户选择"接受"后继续正常流程（copywriter）
* [ ] 用户选择"换角度"后重新运行 content_strategist（保留趋势数据），新策略再次走 Ripple 验证
* [ ] 用户选择"换话题"后回退到 trend_scout 重新搜索
* [ ] 换角度和换话题都计入同一 `reselect_count` 上限（2 次），超过后自动接受继续
* [ ] Brief 模式下 brief_analyzer 完成 Ripple 后同样支持重新选题
* [ ] 所有路径的进度在页面上实时更新

## Definition of Done

* Tests added/updated for ripple_gate node, API endpoint, graph routing
* Lint / typecheck / CI green
* Frontend UI 实现 + i18n
* 部署验证

## Out of Scope (explicit)

* 自动阈值判断（系统自动决定是否重新选题）— 只做人工触发，阈值仅用于判断是否中断
* Ripple 模拟本身的优化（只关注决策流程）

## Technical Notes

* **Gate node pattern**: `interrupt(None)` 在 `interrupt_before` 节点 → 用户通过 `Command(resume=decision)` 恢复。参考 `review_gate_node`, `choice_gate_node`
* **Graph routing**: `content_strategist → ripple_gate → [copywriter | content_strategist | trend_scout]`。需要条件路由。Brief 模式：`brief_analyzer → ripple_gate → [copywriter | brief_analyzer | trend_scout]`
* **Backward routing**: LangGraph 不原生支持回退到之前节点。但可以用 `aupdate_state(config, ..., as_node="trend_scout")` + 重新执行实现。参考 `resume_workflow` 中 `as_node=resume_node` 的用法（workflow.py 第739行）
* **State schema**: XHSGrowthState 需要新增 `ripple_decision` 和 `reselect_count` 字段
* **关键文件**:
  - `backend/graph/builder.py` — 添加 ripple_gate 节点和条件边
  - `backend/agents/nodes/` — 新增 ripple_gate_node
  - `backend/graph/routers.py` — 新增 ripple_gate_router
  - `backend/api/routes/review.py` 或 `workflow.py` — 新增 submit_ripple_decision 端点
  - `backend/state/schema.py` — 新增 ripple_decision 字段
  - `frontend/src/components/RipplePanel.vue` — 新增决策选项 UI
  - `frontend/src/api/workflow.ts` — 新增 submitRippleDecision API