# 状态源归一：checkpoint 为事实源，孤儿 running 检测

## Goal

业务流程优化第 6 项（工程侧 #2）：状态源减少分裂。状态落在 LangGraph checkpoint、DB、history file、进程内 background task registry。部署/重启后 DB "running" 但进程内无 task → "看着 running 实际 orphan"。本 task 加孤儿检测 + 明确分层：checkpoint 为事实源，DB 仅索引摘要，进程内 task 仅运行时缓存。

## What I already know

- `backend/api/routes/_runner.py` `_background_tasks: dict[thread_id, Task]` 进程内任务注册表
- `backend/api/routes/workflow.py:95` `_on_task_done` 已检测 stale（task 完成 DB 仍 running）
- `derive_status(state, has_active_task=...)` 已有 stale 派生
- `backend/db/workflows.py` DB 存 status/phase/label/created_at/task_done_at
- 重启后 `_background_tasks` 清空（进程内），DB running 记录残留 → orphan
- `/status` 端点已算 `has_active_task = thread_id in _background_tasks and not done`

## Requirements

- 启动时（或 `/status` / `/list` 时）检测 orphan：DB status=running 但进程内无 active task
  → 标记 DB status=stale（或 orphan），让 `/recover` 可恢复
- `/list` 返回的 running 项标注 `orphan: True`（DB running 无 task）
- 不改 checkpoint 为事实源的根本结构（太大），只加 orphan 检测 + 文档化分层
- 进程内 task registry 明确仅运行时缓存（注释 + 重启清空语义）

## Acceptance Criteria

- [ ] DB running 但进程内无 active task → status 派生为 stale/orphan
- [ ] `/list` orphan 项标注
- [ ] `/status` orphan 返回明确状态
- [ ] 重启后孤儿可被 `/recover` 恢复
- [ ] 全量 pytest 绿，ruff/mypy 不新增错误

## Out of Scope

- 完全移除 DB status 列（仍保留作索引/摘要）
- history file 归一（低频用，后续）
- 跨进程任务注册表（Redis 等，后续）
- checkpoint 重写为唯一源的大重构

## Technical Approach

- `derive_status` 已有 has_active_task 参数；扩 `_orphan_status` helper：
  DB running + not has_active_task → "stale"（复用现有 stale 语义，避免新状态）
- `/list` 端点：对每个 running 行查 `_background_tasks`，无则标 `orphan: True` + 派生 stale
- `/status` 端点：已有 has_active_task 计算，确保 orphan 时返回 stale + 可 recover 标志
- 启动 hook（app startup）：扫 DB running 记录，无 task 的标 stale（一次性清理）
  - 或更简：不启动扫，惰性检测（/list //status 时算）—— ponytail，避免启动开销

## Implementation Plan

- PR（本 task）：orphan 检测（惰性）+ /list 标注 + 启动清理（可选）+ 单测

## Technical Notes

- 文件：`backend/api/routes/workflow.py`、`backend/state/machine.py`（derive_status）、`backend/api/app.py`（startup hook 可选）
- 约束：复用 stale 语义不新增状态；惰性检测优先；不改 DB schema
- 风险：启动扫描若 DB 大可能慢——惰性检测更稳
