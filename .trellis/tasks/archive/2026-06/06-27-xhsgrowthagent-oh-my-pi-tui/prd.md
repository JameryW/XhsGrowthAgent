# 封装 XhsGrowthAgent 为 oh-my-pi 扩展工具 + TUI 交互

## Goal

将 XhsGrowthAgent 的核心创作能力封装为 oh-my-pi (omp) 扩展，使用户在 omp TUI 终端里直接调用小红书创作能力，无需切换到 Web 界面。

## What I already know

* oh-my-pi 是终端 AI 编码 agent，有扩展系统（TypeScript 模块，导出 factory 函数）
* 扩展通过 `pi.registerTool()` 注册工具，`pi.registerCommand()` 注册命令，`pi.on()` 注册事件
* 工具用 Zod 定义参数 schema，execute 返回 `{ content, details }` 结构
* 已有 quantagent-ext 作为参考模板
* XhsGrowthAgent 后端已有 FastAPI 服务（`backend/api/app:app`），端口 8000
* API 路由：POST /workflow/start, GET /workflow/status/{id}, POST /workflow/pause/resume/cancel, POST /review/approve/reject
* SSE 流：GET /workflow/stream/{id}
* WorkflowMode: 'trend' | 'brief'
* WorkflowStatus: idle/running/stale/awaiting_review/awaiting_choice/awaiting_draft/...

## Decisions

* **工具粒度：按操作拆分** — 每个 omp 工具对应一个 API 端点
* **命令设计：2 个** — /xhs 启动创作，/xhs-review 查看审核
* **SSE 实时进度** — xhs_workflow_start 内部订阅 SSE 流，通过 onUpdate 实时推送给 TUI
* **API 降级** — 工具调用前检测 API 连通性，不可用时返回友好错误 + 启动提示
* **多端共存** — 工具返回中包含完整 status 快照，LLM 可判断 workflow 是否被其他端修改
* **扩展位置：backend/omp/extensions/xhsagent-ext/**
* **双端覆盖** — omp 扩展自定义 renderCall/renderResult 渲染终端卡片；Web 前端新增 /tui 页面提供完整终端风格交互

## Requirements

### 工具（7 个）

1. **xhs_workflow_start** — 启动工作流，内部订阅 SSE 实时推送进度
2. **xhs_workflow_status** — 查询状态，返回完整快照（含 phase/progress/agent/数据摘要）
3. **xhs_workflow_pause** — 暂停工作流
4. **xhs_workflow_resume** — 恢复工作流
5. **xhs_workflow_cancel** — 取消工作流
6. **xhs_review_approve** — 通过审核
7. **xhs_review_reject** — 驳回审核（含修改意见）

### 命令（2 个）

* `/xhs [topic]` — 启动小红书创作工作流
* `/xhs-review` — 查看待审核内容

### 事件钩子

* `before_agent_start` — 注入小红书创作上下文提示词
* `session_start` — 检测 API 连通性，不可用时 notify 提示

### 基础设施（omp 扩展）

* `api_client.ts` — HTTP + SSE 客户端，含连通性检测
* `config.ts` — XHS_AGENT_API_BASE 环境变量
* `types.ts` — API 响应类型定义

### 自定义 TUI 渲染（omp 扩展）

* `xhs_workflow_start` — renderCall 显示参数摘要，renderResult 显示进度条+最终结果
* `xhs_workflow_status` — renderResult 显示状态卡片（phase/progress/agent/数据摘要）
* `xhs_review_approve/reject` — renderResult 显示审核结果确认

### Web 前端 TUI 页面

在现有 Vue 前端新增 TUI 风格页面，仿终端界面，提供完整交互体验：

* **路由**：`/tui` 或 `/agent`
* **TUI 布局**：左侧命令输入区 + 右侧输出展示区，仿终端风格（深色背景、等宽字体）
* **核心交互**：
  - 命令输入：支持自然语言 + 快捷命令（/start, /status, /review, /approve, /reject）
  - 工作流进度：实时显示 phase 变化、agent 执行状态、进度百分比
  - 审核交互：展示生成内容，提供 approve/reject 按钮和修改意见输入
  - 内容预览：文案、视觉方案的结构化展示
* **实时通信**：复用现有 SSE/WebSocket 基础设施
* **与 omp 扩展共用 API**：同一套后端 API，同一套数据格式

## Acceptance Criteria

* [ ] `xhsagent-ext` 扩展可被 omp 加载（package.json + omp.extensions 正确）
* [ ] 工具注册成功，omp 可见 xhs_* 工具
* [ ] xhs_workflow_start 可启动工作流并通过 SSE 实时推送进度
* [ ] xhs_workflow_status 返回完整状态快照
* [ ] xhs_review_approve/reject 可完成人工审核
* [ ] /xhs 命令可触发创作流程
* [ ] API 不可用时工具返回友好错误信息
* [ ] 多端操作同一 workflow 时 status 返回一致数据
* [ ] omp 扩展自定义 renderCall/renderResult 正确渲染
* [ ] Web 前端 /tui 页面可访问，仿终端风格
* [ ] Web TUI 支持命令输入（自然语言 + 快捷命令）
* [ ] Web TUI 实时显示工作流进度
* [ ] Web TUI 展示审核内容并提供 approve/reject 交互

## Definition of Done

* 扩展代码通过 TypeScript 类型检查
* Lint / typecheck green
* README 更新：omp 扩展使用说明

## Out of Scope

* 直接调用 Python 函数（不走 HTTP）
* Workflow replay / checkpoint 高级功能
* Ripple CAS 模拟相关工具
* Memory / Creative Memory 相关工具
* Brief PDF 上传交互
* Blogger 选择交互

## Technical Notes

* 参考模板：/home/admin/heuristic-agent-framework/backend/omp/extensions/quantagent-ext/
* XhsGrowthAgent API：backend/api/routes/workflow.py, backend/api/routes/review.py
* SSE 端点：GET /workflow/stream/{thread_id}
* API 基础 URL：http://localhost:8000（XHS_AGENT_API_BASE 覆盖）
* 扩展放置位置：backend/omp/extensions/xhsagent-ext/
* omp 扩展 package.json 格式：`{ "omp": { "extensions": ["./src/index.ts"] } }`
* 工具命名约定：xhs_ 前缀
* SSE 模式：xhs_workflow_start 内部用 EventSource 订阅，通过 onUpdate 推送 phase 变化，工作流完成后返回最终结果
