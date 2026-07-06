# 状态恢复操作化：显式恢复/重试操作

## Goal

业务流程优化第 4 项：状态诊断变操作。代码已有 derive_status/stale/checkpoint_lost + `/resume`（重试失败节点）。本 task 补 2 个缺失操作 + 把 3 个操作作为显式 API 暴露：
1. **只重试失败节点**（已存在 — `/resume` error 路径 native ainvoke(None) 重跑失败 task）
2. **从上个成功节点重试**（新）— Command(goto=last_success_node) 重跑该节点起的链
3. **恢复到下一节点**（新）— 跳过失败节点，Command(goto=failed_node_successor)

## What I already know

- `backend/api/routes/workflow.py:978` `POST /resume/{thread_id}` 已处理 error/stale/paused/terminal
- error/stale 路径：native ainvoke(None) 重跑失败 task（`_start_resume_task` input_data=None）= "只重试失败节点"
- `_start_resume_task`（workflow.py:201）支持 `input_data` 参数，传 `Command(goto=node)` 可重定向到特定节点
- `_resume_nodes_from_tasks`（:180）从 state.tasks 提取失败/命名 task
- `_resume_phase_for_next_nodes`（:141）节点→phase 映射
- `state.next` 是 checkpoint 的待执行节点
- `state.tasks` 含失败 task 信息（`_task_has_error`）
- LangGraph `Command(goto=...)` 支持跳转节点

## Requirements

- 新端点 `POST /recover/{thread_id}` 带 `strategy` 参数：`retry_failed` | `retry_from_last_success` | `skip_to_next`
  - `retry_failed`：等同现 `/resume` error 路径（native ainvoke(None) 重跑失败 task）
  - `retry_from_last_success`：找上次成功节点（state.tasks 里非失败的命名 task，或 _last_node），Command(goto=该节点) 重跑该节点起的链
  - `skip_to_next`：跳过失败节点，Command(goto=state.next[0])（失败节点的后继）
- 端点返回恢复策略 + 目标节点 + 新 phase（诊断信息变可见操作）
- 仅 error/stale 状态可 recover；paused 用 `/resume`，completed/cancelled 用 `/resume` restart
- 不存在的成功节点 / 无法确定后继 → 400 带诊断信息（不盲跑）
- DB 状态更新 + background task 复用 `_start_resume_task`

## Acceptance Criteria

- [ ] `POST /recover/{thread_id}?strategy=retry_failed` 行为同 `/resume` error 路径
- [ ] `strategy=retry_from_last_success` 用 Command(goto=last_success) 重跑
- [ ] `strategy=skip_to_next` 用 Command(goto=next) 跳过失败节点
- [ ] 非 error/stale 状态 recover 返回明确拒绝信息
- [ ] 无法确定目标节点时 400 + 诊断（不盲跑）
- [ ] 返回值含 strategy/target_node/phase 诊断字段
- [ ] 全量 pytest 绿，ruff/mypy 不新增错误

## Out of Scope

- 前端 UI（API 先行，UI 后续 task）
- `/resume` 改造（保持兼容，新端点并行）
- checkpoint_lost 的自动恢复（仍人工触发 recover）
- 跨 thread 恢复

## Technical Approach

- `backend/api/routes/workflow.py`：加 `POST /recover/{thread_id}` 端点
  - 入参 `RecoverRequest{strategy: Literal[...]}`
  - 复用 `_resume_nodes_from_tasks` / `_resume_phase_for_next_nodes` 定位节点
  - `retry_from_last_success`：从 state.tasks 找最后一个无 error 的命名 task → Command(goto=它)
  - `skip_to_next`：state.next[0] → Command(goto=它)；state.next 空则 400
  - 调 `_start_resume_task(thread_id, graph, config, phase, input_data=Command(goto=target))`
- 单测 `tests/unit/api/test_recover.py`：3 strategy 各路径 + 拒绝非 error + 400 诊断

## Implementation Plan

- PR（本 task）：`/recover` 端点 + 单测

## Technical Notes

- 文件：`backend/api/routes/workflow.py`、`tests/unit/api/test_recover.py`
- 约束：不盲跑（无法定位节点 400）；复用 `_start_resume_task`；不破坏 `/resume`
- 风险：Command(goto) 跳到已运行过的节点会重跑——retry_from_last_success 需用户理解会重跑该节点起下游
