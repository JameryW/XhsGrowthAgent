# 前端博主选择 UI

## Goal

在前端支持 `blogger_gate` 中断状态——当后端暂停等待用户选择博主时，前端显示候选博主卡片列表，用户选择或跳过后 resume 工作流。

## What I already know

* 后端已实现 `blogger_scout` + `blogger_gate` 节点（hot-blogger-reference 任务）
* 后端 `WorkflowStatus` 新增 `AWAITING_BLOGGER_SELECTION` 状态
* 后端 `blogger_gate` 使用 `interrupt_before` 机制，resume 时通过 `Command(resume=selection)` 传递选择
* 后端还没有 blogger 选择的 API 端点（需新增 `/optimization/blogger-select/{thread_id}`）
* 前端 `WorkflowStatus` 类型缺少 `awaiting_blogger_selection`
* 前端 `WorkflowState` / `WorkflowStateResponse` 缺少 `blogger_candidates`, `selected_blogger`, `blogger_notes` 字段
* 前端各组件（ProgressPhase, WorkflowHeader, ActionButtons, WorkflowTabBar, WorkflowTimeline, Navbar）都硬编码处理 awaiting 状态
* 类似模式：choice_gate（selectVersion）、draft_gate（submitDraft）、ripple_gate（submitRippleDecision）

## Requirements

### 后端（API 端点）

* 新增 `POST /api/optimization/blogger-select/{thread_id}` 端点
  - 请求体：`{ user_id: string, nickname: string }` 或 `{ skip: true }`
  - 当 `blogger_gate` 在 `state.next` 中时，resume 工作流
  - 返回标准 `ApiResponse` 格式
* 新增 `GET /api/optimization/blogger-pending/{thread_id}` 端点
  - 返回候选博主列表和配置（candidate_limit, note_limit）

### 前端

* 类型定义
  - `WorkflowStatus` 新增 `'awaiting_blogger_selection'`
  - 新增 `BloggerProfile` 和 `BloggerNote` 接口
  - `WorkflowStateResponse` 新增 `blogger_candidates`, `selected_blogger`, `blogger_notes` 字段
* API 函数
  - `selectBlogger(threadId, selection)` — 选择/跳过博主
  - `getPendingBloggerSelection(threadId)` — 获取候选列表
* Store
  - `workflow.ts`: 新增 `isAwaitingBloggerSelection` computed
  - `workflow.ts`: 处理 `awaiting_blogger_selection` 状态的 toast 通知
  - `workflow.ts`: 存储 `bloggerCandidates` 列表
* UI 组件
  - 新增 `BloggerSelectionPanel.vue` — 候选博主卡片列表 + 选择/跳过按钮
  - `WorkflowTimeline.vue`: 新增 `blogger_scout` 和 `blogger_gate` 步骤
  - `ProgressPhase.vue`: 处理 `awaiting_blogger_selection` 状态显示
  - `WorkflowHeader.vue`: 处理 awaiting blogger 状态文案
  - `ActionButtons.vue`: 处理 awaiting blogger 状态文案
  - `WorkflowTabBar.vue`: 处理 awaiting_blogger_selection 状态图标/颜色
  - `Navbar.vue`: 处理 awaiting blogger 状态
* 国际化
  - `en.json` / `zh-CN.json`: 新增 blogger 相关翻译 key
* ContentCards / Dashboard
  - 当 `awaiting_blogger_selection` 时显示 BloggerSelectionPanel

## Acceptance Criteria

* [ ] `POST /api/optimization/blogger-select/{thread_id}` 端点可用
* [ ] `GET /api/optimization/blogger-pending/{thread_id}` 端点可用
* [ ] 前端 `WorkflowStatus` 包含 `awaiting_blogger_selection`
* [ ] 前端 `BloggerProfile` / `BloggerNote` 类型定义
* [ ] `BloggerSelectionPanel.vue` 显示候选博主卡片，支持选择和跳过
* [ ] 工作流暂停在 blogger_gate 时，前端正确显示 awaiting 状态
* [ ] 选择博主后工作流正确 resume
* [ ] 跳过选择后工作流正确 resume
* [ ] WorkflowTimeline 包含 blogger_scout 和 blogger_gate 步骤
* [ ] 所有 awaiting 状态组件处理 awaiting_blogger_selection
* [ ] 中英文翻译完整
* [ ] Lint / typecheck 通过

## Definition of Done

* Tests added/updated (unit/integration where appropriate)
* Lint / typecheck / CI green
* Docs/notes updated if behavior changes

## Out of Scope

* 博主详细信息页面（点击跳转小红书主页）
* 博主历史数据趋势图表
* 多博主对比功能
* 博主收藏/黑名单功能

## Technical Approach

### 后端新增文件
* `backend/api/routes/blogger.py` — 博主选择 API 端点

### 后端修改文件
* `backend/api/app.py` — 注册 blogger router

### 前端新增文件
* `frontend/src/components/dashboard/BloggerSelectionPanel.vue` — 博主选择面板

### 前端修改文件
* `frontend/src/types/workflow.ts` — 新增类型
* `frontend/src/api/workflow.ts` — 新增 API 函数
* `frontend/src/stores/workflow.ts` — 新增状态和 computed
* `frontend/src/components/ProgressPhase.vue` — 处理 awaiting_blogger_selection
* `frontend/src/components/dashboard/WorkflowHeader.vue` — 处理状态文案
* `frontend/src/components/dashboard/ActionButtons.vue` — 处理状态文案
* `frontend/src/components/dashboard/WorkflowTabBar.vue` — 处理状态图标/颜色
* `frontend/src/components/dashboard/WorkflowTimeline.vue` — 新增步骤
* `frontend/src/components/dashboard/ContentCards.vue` — 显示 BloggerSelectionPanel
* `frontend/src/components/Navbar.vue` — 处理状态
* `frontend/src/views/Dashboard.vue` — 集成 BloggerSelectionPanel
* `frontend/src/locales/en.json` — 英文翻译
* `frontend/src/locales/zh-CN.json` — 中文翻译
