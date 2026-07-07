# 决策收件箱：合并人工决策点

## Goal

业务流程优化第 1 项：合并人工决策点。图里有 draft_gate/blogger_gate/choice_gate/ripple_gate/review_gate 多个暂停点。建"决策收件箱"：一次展示 Ripple 结果、博主候选、版本选择、草稿审核，用户集中处理，减少来回等待。

## What I already know

- 现有分散端点：`GET /review/pending/{thread_id}`、`GET /review/ripple-pending/{thread_id}`
- 各 gate 用 interrupt() 或 interrupt_before 暂停，state.next / state.interrupts 标识当前位置
- review_gate/ripple_gate 用动态 interrupt()（gate 字段标识）；choice_gate/draft_gate 用 interrupt_before
- blogger_gate 在 trend 模式有博主候选时 interrupt
- 单 thread 一次只在一个 gate 暂停（图线性），但用户可能多 thread 并行

## Requirements

- 新端点 `GET /inbox/{account_id}` 或 `GET /inbox`（用 active account）：
  - 列出该 account 所有 paused/at-gate 的 thread
  - 每个 entry 含：thread_id、gate 类型（review/ripple/choice/draft/blogger）、gate 数据快照（ripple_summary / blogger_candidates / versions / draft）、phase、created_at
  - 一次响应聚合所有待处理决策
- 复用现有 `get_pending_review` / `get_pending_ripple_decision` 的数据抽取逻辑（抽成 helper）
- 不改各 gate 的 submit 端点（用户从 inbox 看到决策，仍走原 submit 端点处理）

## Acceptance Criteria

- [ ] `GET /inbox` 返回当前 account 所有 at-gate thread
- [ ] 每个 entry 含 gate 类型 + 数据快照
- [ ] 无待处理时返回空列表（不 500）
- [ ] 复用现有数据抽取，不重复实现
- [ ] 全量 pytest 绿，ruff/mypy 不新增错误

## Out of Scope

- 前端 UI 组件（API 先行）
- 跨 account inbox
- 批量 submit（仍单 thread 单 gate submit）
- gate 合并到单页面交互（API 聚合数据即可，UI 后续）

## Technical Approach

- `backend/api/routes/inbox.py`：新 router，`GET /inbox`
  - 从 DB 列该 account 所有 paused/at-gate thread（复用 workflow list 逻辑）
  - 对每个 thread `graph.aget_state` 取 state.next/interrupts 识别 gate
  - 按 gate 类型抽快照：review→copy_content/visual_plan；ripple→ripple_prediction/pmf；choice→content_versions；draft→copy_content；blogger→blogger_notes/selected_blogger
  - 抽 helper `_gate_snapshot(state, gate) -> dict` 复用 review/ripple 端点的抽取
- 注册 router 到 app

## Implementation Plan

- PR（本 task）：`backend/api/routes/inbox.py` + helper + 单测

## Technical Notes

- 文件：`backend/api/routes/inbox.py`、`backend/api/app.py`（注册）、`tests/unit/api/test_inbox.py`
- 约束：复用现有抽取；空列表不 500；不改 submit 端点
- 风险：多 thread aget_state 并发——串行即可（inbox 量小）
