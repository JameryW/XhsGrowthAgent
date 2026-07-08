# 自由创作模式全面优化

## Goal

自由创作模式（/tui?mode=free）当前入口（Home/表单三模式）做得不错，但进 TUI 后"自由编排创作+评估+发布"基本无法兑现：banner 承诺对话编排，实际普通文本输入被 `freeAgentUnavailable` 拦死、`/start` 禁用、工作流命令禁用；`/mode` 切 agent 后拿到 omp 全工具集，但几乎所有工具要 `thread_id`，free 模式无 thread → agent 实际无活可干。需让 free 模式真正可用（功能）+ 进出/对话体验顺（体验）。

## What I already know

- 入口层（已完成，07-06 任务）：Home.vue 单按钮→WorkflowStartForm 三模式（trend/brief/free）数组驱动，free 隐藏配置字段、按钮文案 `home.form.enterFree`、跳 `/tui?mode=free` 带 topic/niche/account_id query。i18n 齐。
- 隔离层（已完成，07-07 任务）：AgentTUI.vue `isFreeCreationEntry` = `route.query.mode==='free'`；onMounted 跳过 activeThreadId 绑定 + 「恢复活跃工作流」提示；/status /pause /resume /cancel /approve /reject 全禁用提示 `freeWorkflowOpDisabled`；/start 禁用 `freeStartDisabled`；普通文本 `freeAgentUnavailable`。i18n 齐。
- agent WS：`/api/agent/ws`（`backend/api/routes/agent.py`），无 mode 概念，全走 omp bridge 同一 session/工具集。
- omp 工具集（`backend/omp/extensions/xhsagent-ext/src/tools/`）30 个工具，绝大多数要 `thread_id`：workflow_*/review_*/optimization_draft/evaluation_* 全绑 thread。standalone 候选：system_health、analytics_*（可能要 account）、blogger_pending、ripple_pending。
- draft 路由：`backend/api/routes/optimization.py: POST /optimization/draft/{thread_id}` — 绑 thread，无 standalone 创作入口。
- 旧 PRD 都假设 free 模式靠"agent 对话编排原子能力"，但未补 standalone 能力 → 这是缺口根因。

## Assumptions (temporary)

- free 模式核心价值 = 不走固定 trend/brief 工作流，由 agent 对话驱动创作（标题/正文/视觉）+ 可选评估 + 可选发布。当前缺 standalone 创作+评估+发布路径。
- 优化应聚焦"让 free 模式真能创作"，而非再加隔离护栏（隔离已完成）。

## Decision 1 — 能力范围（已定）

**对话 + standalone 创作/发布**：free 模式要真能产出并发布内容，兑现 banner 承诺。
不选纯对话（banner 撒谎）、不选只创作不发布（半兑现）。

**Consequences**: 需新增 thread-less 创作后端入口 + omp 工具；工作量最大但完整。

## Decision 2 — 数据模型 + 发布路径（已定）

**草稿持久化**：复用 BaseStore，命名空间 `accounts/{id}/free_drafts`，key=draft_id。
不新建 PG 表 —— 草稿可弃，BaseStore 已支持语义召回，migration 偏重（YAGNI）。

**发布**：新建 `free_publish` 后端路由包装 XHSPublisher.publish_note，额外记发布结果到
account 记忆（store_content_record）。不走 omp xhs_publisher 工具直连 —— 包装层提供
可观测性 + 记忆沉淀。

## Decision 3 — 暴露方式 + /start + UX 范围（已定）

**暴露方式**：在 `omp_bridge.py` `XHS_HOST_TOOLS` 加三个 host tool
（`xhs_free_draft_create` / `xhs_free_evaluate` / `xhs_free_publish`）+ `_execute_xhs_host_tool`
加分支调新 thread-less 后端路由。agent 经 WS 自动拿到。不动 TS ext（避免双套维护）。

**/start 语义**：free 模式 `/start` 改义为「开始新会话」（omp `new_session`），清空对话上下文。
提供明确会话重置入口，对齐 banner「对话编排」心智。

**UX 范围**：TUI + 入口。
- TUI：解文本拦截、banner 文案对齐兑现、`/start` 改义为 new_session、草稿/评估/发布反馈展示
- 入口：free 表单补「我要发布」选项 / 入口文案微调（让用户预期 free 可发）

## Open Questions

（已全部收敛，无 blocking）

## Requirements (final)

### Free 模式解锁
- 普通文本输入解锁：路由到 omp agent WS 对话（去掉 AgentTUI.vue:701 `freeAgentUnavailable` 拦截）
- `/start` 在 free 模式改义为 omp `new_session`（清上下文）；非 free 仍启动 trend 工作流
- 非 free 工作流 slash 命令（/status /pause /resume /cancel /approve /reject）保持禁用

### Standalone 创作后端（thread-less）— 新路由
- `POST /api/free/draft`：body {account_id, title, body, hashtags, image_paths} → 存 BaseStore
  命名空间 `accounts/{account_id}/free_drafts`，key=draft_id（uuid）→ 返回 {draft_id, draft}
- `POST /api/free/evaluate`：body {account_id, draft_id} → 取草稿 → 合成最小 XHSGrowthState
  （copy_content=草稿、niche、account_id）→ 调 `EvaluatorAgent.execute` → 返回 EvaluationResult（不入 checkpoint）
- `POST /api/free/publish`：body {account_id, draft_id} → 取草稿 → 调
  `XHSPublisher.publish_note` → 记发布结果到 `store_content_record` → 返回 {post_id, post_url, status}

### omp host tools — 暴露给 agent
- `xhs_free_draft_create`（参数: account_id, title, body, hashtags, image_paths）
- `xhs_free_evaluate`（参数: account_id, draft_id）
- `xhs_free_publish`（参数: account_id, draft_id）
- 加到 `XHS_HOST_TOOLS` + `_execute_xhs_host_tool` 分支

### 不破坏
- 非 free 模式（trend/brief）行为完全不变
- omp bridge 单 session 模型不变；TS ext 工具集不动

## Acceptance Criteria (final)

- [ ] Free 模式输入普通文本进入 agent 对话，不再被 `freeAgentUnavailable` 拦死
- [ ] `/start` 在 free 模式触发 omp new_session（清上下文），非 free 不变
- [ ] `POST /api/free/draft` 创建草稿持久化到 BaseStore，返回 draft_id
- [ ] `POST /api/free/evaluate` 调 EvaluatorAgent 返回 EvaluationResult（不依赖 thread）
- [ ] `POST /api/free/publish` 调 XHSPublisher 发布 + 记录到 account 记忆，返回 post_id/url
- [ ] 三个 host tool 注册进 omp，agent 能调用完成「创作→评估→发布」闭环
- [ ] TUI 展示草稿/评估/发布反馈；banner 文案兑现
- [ ] free 表单「我要发布」选项 + 入口文案微调
- [ ] 非 free 模式行为完全不变
- [ ] 前端 build+typecheck 过；后端 mypy/pytest 过；omp typecheck 过；ruff 过

## Definition of Done (team quality bar)

- Tests: 前端 build+typecheck 过；后端 mypy/pytest 过；omp typecheck 过
- Lint / CI green
- 行为变更自明，无需额外 docs
- Rollout: 前端改动 deploy.sh rebuild；后端改动 restart

## Out of Scope (explicit)

- 不新建 PG free_drafts 表（用 BaseStore）
- 不动 TS ext 工具集（xhsagent-ext/src/tools/）—— host tool 路径已够，避免双套维护
- 不给 free 草稿加版本管理/AB 测试（草稿可弃，YAGNI）
- 不动 omp bridge 单 session 模型
- 不改非 free 模式的任何行为
- 不接入 Ripple CAS（free 创作不需模拟，发布后真实数据走 analytics）
- 不做 free 草稿的定时发布调度（scheduled_time 透传给 publisher 即可，不另建调度）

## Technical Approach

3 个 thread-less 后端路由 + 3 个 omp host tool + AgentTUI 解锁/UX + 入口微调。

**数据流**：
```
用户输文本 → omp agent WS → agent 调 xhs_free_draft_create
  → POST /api/free/draft → BaseStore(accounts/{id}/free_drafts) → draft_id
agent 调 xhs_free_evaluate → POST /api/free/evaluate
  → 取草稿 → EvaluatorAgent.execute(合成 state) → EvaluationResult
agent 调 xhs_free_publish → POST /api/free/publish
  → 取草稿 → XHSPublisher.publish_note → store_content_record → post_id/url
```

**关键复用**（均已验证 thread-less）：
- `XHSPublisher.publish_note` — 接 title/body/hashtags/image_paths，无 thread 依赖
- `EvaluatorAgent.execute(state, store)` — 读 state["copy_content"]，thread 仅 checkpoint 存储方式
- `MemoryManager.store_content_record(store, post_id, record)` — namespace `accounts/{id}/content_history`

## Decision (ADR-lite)

**Context**: Free 模式 banner 承诺对话编排创作+发布，但 TUI 拦死文本、agent 无 thread-less 工具
→ 兑现不了。需补 standalone 能力。

**Decision**:
1. 能力 = 对话+standalone 创作/发布（兑现 banner）
2. 草稿存 BaseStore（YAGNI，不新建表）
3. 发布走新 free_publish 路由包装（可观测+记忆沉淀，不走工具直连）
4. 暴露 = omp host tool + 新后端路由（不动 TS ext）
5. /start free 语义 = omp new_session
6. UX = TUI + 入口

**Consequences**:
- 后端新增 3 路由 + bridge 加 3 host tool —— 中等工作量但全部复用已有原语
- 草稿不进 LangGraph checkpoint → 不参与工作流 resume/retry，符合 free「不碰工作流」隔离
- 发布结果进 account 记忆 → free 创作沉淀可被未来 trend/brief 工作流召回（正向联动）

## Implementation Plan (small PRs)

- **PR1 — 后端 standalone 路由 + 测试**：
  新建 `backend/api/routes/free.py`（draft/evaluate/publish）+ 注册到 app；
  BaseStore free_drafts 命名空间 helper；pytest 覆盖三路由
- **PR2 — omp host tool 暴露**：
  `omp_bridge.py` XHS_HOST_TOOLS 加 3 工具 + `_execute_xhs_host_tool` 加 3 分支；
  验证 agent 经 WS 能调到
- **PR3 — AgentTUI 解锁 + UX + 入口**：
  去 701 拦截、/start free 改 new_session、banner 文案兑现、草稿/评估/发布反馈展示；
  free 表单「我要发布」选项 + 入口文案；i18n；前端 build+typecheck

## Technical Notes

- 文件：
  - `backend/api/routes/free.py`（新建）
  - `backend/api/routes/__init__.py`（注册 free router）
  - `backend/services/omp_bridge.py`（XHS_HOST_TOOLS + _execute_xhs_host_tool）
  - `frontend/src/views/AgentTUI.vue`（701 拦截、720 /start、1023 banner、反馈展示）
  - `frontend/src/components/WorkflowStartForm.vue`（free 表单「我要发布」）
  - `frontend/src/i18n/locales/*.ts`（free 模式新文案）
  - `backend/agents/evaluator.py`（复用，不改）
  - `backend/services/xhs_publisher.py`（复用，不改）
  - `backend/memory/store.py`（复用 store_content_record，不改）
- 约束：不破坏非 free 模式；保持 omp bridge 单 session 模型
- env：`XHS_AGENT_API_BASE`（默认 localhost:8889）— host tool 内调后端用
- 测试：pytest 后端三路由；前端 typecheck；omp typecheck（host tool 在 Python bridge 不涉 TS）
