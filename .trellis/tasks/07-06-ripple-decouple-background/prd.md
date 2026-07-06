# Ripple 解耦：不默认阻塞链路，后台跑，结果回来触发决策

## Goal

业务流程优化第 3 项：Ripple 不默认阻塞整条链路。改：先生成可用草稿（copywriter 不等 Ripple），Ripple 后台跑；结果回来后只触发"建议优化"或"需要重写"的决策（轻量 interrupt 或 async 通知），而不是让整个工作流卡 1800s。

## What I already know

- `backend/agents/content_strategist.py:166` `asyncio.gather(_predict(), _validate_pmf())` 阻塞等 Ripple（max 1800s）
- `ripple_gate_node` 在 strategist 后 interrupt（仅 suboptimal 时）
- `_DEFAULT_RIPPLE_TIMEOUT=1800`（30min）
- RippleService 单例，`predict_spread`/`validate_pmf` async
- copywriter 不依赖 ripple_prediction（读 content_plan），但 strategist 把 ripple_prediction 写进 content_plan 给 copywriter 参考文案
- ripple_reason in (timeout, unreachable) 时 ripple_gate 不 gate

## Requirements

- 配置开关 `RIPPLE_BACKGROUND`（默认 False，保持现状阻塞模式）
- 开启时：strategist fire-and-forget Ripple（`asyncio.create_task`），不 await；content_plan 标 `ripple_pending: True`；copywriter 正常生成草稿
- Ripple 完成（predict_spread/validate_pmf 返回）后写 ripple_prediction/ripple_pmf 到 state + 标 `ripple_pending: False`，发 EventBus 事件 `WORKFLOW_RIPPLE_READY`
- review_gate 前/后若 ripple 结果 suboptimal 且未到 reselect 上限 → 触发轻量"建议优化"决策（复用 ripple_gate 的 interrupt 机制，但放在草稿完成后）
- timeout/unreachable → 标 ripple_reason，不阻塞
- 关闭时（默认）：行为同现状

## Acceptance Criteria

- [ ] RIPPLE_BACKGROUND=false 时行为不变（全量测试绿）
- [ ] RIPPLE_BACKGROUND=true 时 strategist 不 await Ripple，copywriter 立即跑
- [ ] Ripple 后台完成写 state + 发事件
- [ ] suboptimal 结果触发建议优化决策（不阻塞主链 1800s）
- [ ] timeout 不阻塞
- [ ] 全量 pytest 绿，ruff/mypy 不新增错误

## Out of Scope

- 前端实时展示 Ripple 进度（EventBus 事件已发，UI 后续）
- Ripple 跨 workflow 持久化（仅本 thread）
- Ripple 取消机制（已有 _ripple_cancel）

## Technical Approach

- `content_strategist.py`：`RIPPLE_BACKGROUND` 开 → `_schedule_ripple_background(state, content_plan, thread_id)` 起 task，return content_plan 标 ripple_pending；关 → 现 gather 逻辑
- `_schedule_ripple_background`：`asyncio.create_task(_run_ripple_and_store(...))`，内部 await predict+validate，完成后通过 EventBus 或 store 写回 state（store.aput namespace `ripple/{thread_id}`）
- 新增 `ripple_finalize_node`（analyst 后或 review 前）：读 store 的 ripple 结果，若 suboptimal → interrupt 建议；否则 pass
- 或更简：review_gate 后插 `ripple_finalize_gate`（仅 RIPPLE_BACKGROUND 模式生效）

## Implementation Plan

- PR（本 task）：strategist background 模式 + ripple_finalize + 配置开关 + 单测

## Technical Notes

- 文件：`backend/agents/content_strategist.py`、`backend/agents/nodes/ripple_gate.py`、`backend/graph/builder.py`、`backend/config/settings.py`（开关）
- 约束：默认 False 不破坏现状；后台 task 异常不影响主链；store 写回需 thread_id
- 风险：background task 跨节点 state 写回——LangGraph state 不能跨 node 直接写，需 store 或 Command(update=)
