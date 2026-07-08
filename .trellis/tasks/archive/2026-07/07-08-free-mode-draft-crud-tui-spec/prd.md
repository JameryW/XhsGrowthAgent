# Free Mode Draft CRUD + TUI Interaction + Spec

## Goal

PR#210 交付了 free 模式的 create/evaluate/publish 闭环，但草稿管理只有 create（无 list/update/delete），TUI 无草稿交互命令，spec 无 free 模式契约文档。本任务补全这三块：agent 能列/改/删草稿、TUI 有 /drafts 交互、spec 记录 thread-less 契约供未来参考。

## What I already know

- PR#210 已 merge（commit c23fca2d）：`backend/api/routes/free.py` 有 POST /draft /evaluate /publish；BaseStore namespace `("accounts", account_id, "free_drafts")` key=draft_id；omp bridge 有 xhs_free_draft_create/evaluate/publish host tool；AgentTUI free 默认 agent mode + /start=new_session。
- BaseStore 有 `alist(namespace_prefix=, limit=)` 和 `aget(namespace, key=)`、`aput(namespace, key, value)`。无 delete（需查 langgraph BaseStore 是否有 adel）。
- spec 层：`.trellis/spec/backend/omp-integration.md` 有 host tool 契约场景；无 free 模式专属契约。
- spec 交叉审计约定：bridge 是 TS ext 子集，TS ext 是超集。free 工具目前只在 bridge（设计如此，避免双套）。

## Decisions (verified)

- BaseStore **has** `adelete(namespace, key)` → 真 delete，不需 tombstone
- list: `store.alist(namespace_prefix=("accounts", account_id, "free_drafts"), limit=N)` — 复用 system.py:173 模式（InMemoryStore + AsyncPostgresStore 都支持，宽泛处理异常）
- update: `store.aput` 同 key 覆盖（draft_id 不变）
- TUI /drafts: 新 host tool `xhs_free_draft_list`（agent 经 WS 调）+ AgentTUI `/drafts` slash 命令渲染列表
- spec: 新文件 `.trellis/spec/backend/free-creation.md`

## Open Questions

（已收敛，无 blocking）

## Requirements (final)

### 后端 — free.py 补 3 路由
- `GET /api/free/drafts/{account_id}` → alist namespace → 返回 `[{draft_id, title, ...}]`（精简，不含全 body）
- `PATCH /api/free/draft/{draft_id}` body `{account_id, title?, body?, hashtags?, image_paths?, niche?, content_angle?, target_audience?}` → 取旧草稿 → 合并覆盖 → aput 同 key → 返回更新后草稿
- `DELETE /api/free/draft/{draft_id}` query `account_id` → adelete → 返回 `{deleted: true}`

### omp host tool — 补 1
- `xhs_free_draft_list`（参数: account_id）→ GET /free/drafts/{account_id} → 渲染列表文本
- update/delete 可选暴露：agent 也能直接调 PATCH/DELETE（加 `xhs_free_draft_update` + `xhs_free_draft_delete` host tool）。三块都暴露保完整。

### TUI — AgentTUI
- `/drafts` slash 命令（free 模式）：调 host tool 或直连 GET /api/free/drafts → 渲染草稿列表（draft_id + title）
- 非 free 模式 `/drafts` 提示不可用

### spec — 新文件
- `.trellis/spec/backend/free-creation.md`：记录 thread-less 路由契约（5 路由 + namespace + 复用 EvaluatorAgent/run_publish/BaseStore + host tool 暴露模式 + 非 free 隔离）

## Acceptance Criteria (final)

- [ ] GET /api/free/drafts/{account_id} 返回草稿列表
- [ ] PATCH /api/free/draft/{draft_id} 更新草稿（draft_id 不变）
- [ ] DELETE /api/free/draft/{draft_id} 删除草稿
- [ ] 3 新 host tool（list/update/delete）注册进 omp
- [ ] AgentTUI /drafts 命令渲染草稿列表（free 模式）
- [ ] spec/free-creation.md 文档与代码一致
- [ ] 非 free 模式行为不变
- [ ] 前端 build+typecheck；后端 mypy/pytest；ruff；CI green

## Definition of Done (team quality bar)

- Tests: 前端 build+typecheck 过；后端 mypy/pytest 过；ruff 过
- Lint / CI green
- spec 文档与代码一致

## Out of Scope (explicit)

- （待收敛）

## Technical Notes

- 文件：`backend/api/routes/free.py`、`backend/services/omp_bridge.py`、`frontend/src/views/AgentTUI.vue`、`.trellis/spec/backend/free-creation.md`（新建）
- 约束：不破坏 PR#210 已交付的 create/evaluate/publish；非 free 模式不变
