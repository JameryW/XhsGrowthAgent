# fix-workflow-stale-running-state

## Goal

修复 workflow 状态管理的核心问题：当后台任务异常终止但 snapshot.next 仍有节点时，系统错误地显示 "running" 状态，导致用户无法恢复且无法识别真正的执行状态。

## Requirements (Updated 2026-06-03)

### 1. 新增 STALE 状态 ✅ DONE

- `WorkflowStatus` 新增 `STALE = "stale"`
- `derive_status()` 需要额外参数判断是否有活跃后台任务
- 当 `next_nodes 非空 && 无活跃后台任务` 时返回 STALE（而非 RUNNING）
- STALE 暴露给前端，`"status": "stale"` 语义清晰——需要 resume

### 2. 后台任务 done callback ✅ DONE

- `asyncio.create_task()` 后立即添加 `task.add_done_callback()`
- callback 内：消费异常（避免 `Task exception was never retrieved`），记录 `task_done_at`、`task_error` 到 registry
- 保证 registry 不残留假 running：如果任务异常退出且 derived 仍是 RUNNING，更新为 STALE

### 3. resume 支持 stale ✅ DONE

- resume 端点 guard 扩展：`derived == STALE` 时允许 resume
- 调用 `_start_resume_task(thread_id, graph, config, phase)` 恢复执行

### 4. _run_graph_and_persist 兜底 ✅ DONE

- `ainvoke()` 返回后检查：如果仍有非 gate 的普通 next_nodes，标记 STALE
- 不继续 ainvoke（避免无限循环），不静默退出

### 5. CLI status 命令修复 🔲 TODO

- `backend/cli/main.py` 的 `status` 命令直接读取 `state.values.get("phase")`，未使用 `derive_status()`
- 导致显示 `unknown` 而非 `stale`/`running`/`completed`
- 修复：引入 `derive_status()` + `has_active_task` 参数，正确展示派生状态

### 6. 前端 stale 状态处理 🔲 TODO

- `workflow.ts:342-352` 使用旧启发式检测 stale（`running && no next_steps && no agent`）
- 后端现在直接返回 `status: "stale"`，前端应直接匹配 `status === 'stale'`
- 修复：替换启发式为 `status === 'stale'` 直接判断
- 增强：stale 工作流显示 toast 提示 + 提供 resume 按钮

## Decision (ADR-lite)

**Context**: 需要区分"真正在跑"和"假 running"状态
**Decision**:
1. 状态命名为 `STALE`（不是 recoverable/zombie）——表达"数据过时"，比能力描述更精确
2. 不自动恢复——用户需知道发生了什么，手动 resume 更安全，避免容器重启后雪崩
3. 兜底标记 STALE 而非继续 ainvoke——避免无限循环，与 resume 流程一致

**Consequences**: 前端需处理新状态值 `"stale"`；derive_status 需要额外参数传入后台任务状态

## Acceptance Criteria (Updated)

- [x] `WorkflowStatus` 新增 STALE，`derive_status()` 正确识别 stale（next_nodes 非空 + 无活跃后台任务）
- [x] 后台任务有 done callback，异常被记录而非静默丢失
- [x] resume 端点能恢复 STALE 状态的 workflow
- [x] `_run_graph_and_persist()` 不静默留下假 running，有 next_nodes 时标记 STALE
- [x] 单元测试覆盖：stale 检测、resume stale、done callback 异常记录
- [ ] CLI `status` 命令使用 `derive_status()` 展示正确的派生状态
- [ ] 前端 `workflow.ts` 直接匹配 `status === 'stale'`，替换旧启发式
- [ ] 前端 stale 工作流显示 toast 提示 + resume 按钮

## Definition of Done

- Tests added/updated (unit/integration where appropriate)
- Lint / typecheck / CI green
- Docs/notes updated if behavior changes

## Out of Scope

- Postgres checkpointer 部署配置问题
- 多 worker 分布式协调（需要 Redis 或数据库支持）

## Technical Notes

**关键文件：**
- `backend/state/machine.py` — `WorkflowStatus` enum + `derive_status()`
- `backend/api/routes/workflow.py` — `_background_tasks`, `_start_resume_task()`, resume endpoint
- `backend/api/routes/_runner.py` — `_run_graph_and_persist()`, `bind_registry()`
- `backend/cli/main.py` — `status` 命令（需修复）
- `frontend/src/stores/workflow.ts` — stale 状态处理（需修复）
- `frontend/src/views/Home.vue` / `Dashboard.vue` — stale UI 增强

**derive_status 签名变更：**
```python
def derive_status(
    snapshot: StateSnapshot,
    *,
    has_active_task: bool = True,  # 默认 True 保持向后兼容
) -> WorkflowStatus:
```
当 `has_active_task=False && next_nodes 非空` 时返回 STALE 而非 RUNNING。

**done callback：**
```python
def _on_task_done(thread_id: str):
    def callback(task: asyncio.Task):
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Task %s failed: %s", thread_id, e)
            _workflow_registry[thread_id]["task_error"] = str(e)
        _workflow_registry[thread_id]["task_done_at"] = datetime.now(UTC).isoformat()
    return callback
```

**_status_to_str 更新：** 新增 `WorkflowStatus.STALE: "stale"` 映射
