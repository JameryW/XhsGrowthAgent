# Free Mode Agent Tool Discovery

## Goal

omp agent 进 free 模式(Web TUI,走 Python bridge `/api/agent/ws`)后拿到 33 个 host tool,但无 system prompt 引导它用 `xhs_free_*` 工具链(创建→评估→发布)。agent 可能瞎调需 thread_id 的 workflow_* 工具(free 无 thread → 失败),或不知道 free 工具链顺序。需补 system prompt 引导 + 修过时 TS ext prompt。

## What I already know

- **Web TUI 路径**:`OmpSession.start()` → `register_host_tools(XHS_HOST_TOOLS)`(`backend/services/omp_bridge.py:1185`)把 33 工具 schema 推给 omp。**无 system prompt 注入** —— agent 只靠工具 description 自行发现。
- **TS ext 路径**:`backend/omp/extensions/xhsagent-ext/src/events.ts` `before_agent_start` 注入 system prompt,但:(1) 这只在 omp extension 生效,Web TUI 走 bridge 不走 TS ext;(2) prompt 过时 —— line 27 仍说 "draft directly in conversation",没提 `xhs_free_draft_create/evaluate/publish`(PR#210 后新增)。
- omp bridge host tool 描述已含链路提示(如 `xhs_free_draft_create` description 提 "Returns draft_id for use with xhs_free_evaluate / xhs_free_publish"),但无整体编排引导。
- `xhs_workflow_start` 已被 bridge 拦(返回 disabled error,line 751),但其他 thread-bound 工具(workflow_status 等)在 free 模式调了会失败(agent 无 thread_id)。

## Decision — 引导机制（已定）

**工具发现型**:Python bridge 路径不依赖 omp system prompt 机制(RPC 协议无 set_system_prompt,无 before_agent_start 钩子)。靠:
1. 强化每个 `xhs_free_*` 工具 description,显式标注编排位置(create=step1, evaluate=step2, publish=step3)+ 链路提示
2. 新增 `xhs_free_guide` 只读 host tool,返回完整 free 模式编排说明(创建→评估→发布 + 草稿管理 + 禁调 thread-bound 工具)。agent 首调即可发现全链路。
3. TS ext `events.ts` system prompt 同步更新,提 free host tools(交叉审计,两套一致)

## Open Questions

（已收敛,无 blocking）

## Requirements (final)

### Python bridge — omp_bridge.py
- 强化 `xhs_free_draft_create/evaluate/publish/list/update/delete` 的 description:标注 step 编号 + 链路("Step 1 of 3: create draft → feed draft_id to xhs_free_evaluate (step 2) → xhs_free_publish (step 3)")
- 新增 `xhs_free_guide` host tool(无参数,只读)→ `_execute_xhs_host_tool` 分支返回编排说明文本(不调后端,直接本地生成文本结果)。说明含:free 工具链顺序、草稿管理工具、禁调 thread-bound workflow_* 工具(free 无 thread)、发布前评估建议

### TS ext — events.ts
- `before_agent_start` system prompt 更新:free orchestration loop 提 `xhs_free_draft_create → xhs_free_evaluate → xhs_free_publish`,不再只说 "draft directly in conversation"
- 提草稿管理:`xhs_free_draft_list/update/delete`
- 明确:free 模式禁调 thread-bound 工具(workflow_status 等),用 free 工具替代

### 不破坏
- 非 free 模式(omp extension 走 TS ext 路径)行为不变
- bridge host tool 注册机制不变

## Acceptance Criteria (final)

- [ ] 6 个 xhs_free_* 工具 description 含 step 编号 + 链路提示
- [ ] 新增 xhs_free_guide host tool,返回编排说明
- [ ] TS ext system prompt 更新提 free host tools + 禁调 thread-bound
- [ ] 两套引导一致(交叉审计)
- [ ] 非 free 行为不变
- [ ] 后端 mypy/pytest;ruff;omp typecheck;CI green

## Definition of Done (team quality bar)

- Tests: 后端 mypy/pytest 过；omp typecheck 过；ruff 过
- CI green
- 行为变更自明

## Out of Scope (explicit)

- （待收敛）

## Technical Notes

- 文件:`backend/services/omp_bridge.py`、`backend/omp/extensions/xhsagent-ext/src/events.ts`
- 约束:不破坏 omp bridge 单 session 模型;TS ext + Python bridge 两套 prompt 需一致(交叉审计)
