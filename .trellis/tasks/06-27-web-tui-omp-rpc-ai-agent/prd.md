# Web TUI 对接 omp RPC 实现网页端 AI Agent 交互

## Goal

让 Web TUI 页面通过后端中转连接到 omp 进程，实现浏览器里的 AI Agent 对话式交互——用户输入"帮我写一篇母婴笔记"，omp agent 自动调用 xhs_* 工具完成创作流程。

## What I already know

* omp 有 RPC 模式：`omp --mode rpc`，NDJSON 输入/输出协议
* 输入：30+ 命令类型（prompt, new_session, get_state, set_host_tools 等）
* 输出：ready → response + AgentEvent 流（message_start/update/end, tool_execution_start/update/end）
* Host tool 机制：server 发 `host_tool_call`，host 执行后回 `host_tool_result`
* 需要 bun 运行时启动 omp
* 已有 xhsagent-ext 扩展注册了 7 个 XHS 工具 + 2 个命令
* 当前 Web TUI 直接调后端 API，不走 omp
* 后端是 Python FastAPI，前端是 Vue 3

## Decisions (resolved)

* **架构：后端中转** — Python 后端管理 omp 子进程，前端通过 WebSocket 与后端通信，后端中转 NDJSON 协议到 omp
* **omp 生命周期：常驻进程** — 后端启动时 spawn omp --mode rpc，断开 WebSocket 不关闭 omp，重启后端时优雅关闭
* **前端协议：高层抽象** — 前端发抽象消息（send_message/get_status/new_session/abort），后端翻译为 omp NDJSON 命令；后端向前端推送抽象事件（agent_message/tool_call/tool_result/status），不直接透传 omp 原始事件

## Assumptions (validated)

* bun 在部署环境中可用（或容器镜像中安装）
* omp 已安装且 xhsagent-ext 扩展已加载
* 单用户场景（MVP），一个 omp 会话对应一个浏览器 TUI 连接
* omp 常驻进程在 FastAPI lifespan 中启动/关闭

## Open Questions

* omp 子进程生命周期管理：按需启动 vs 常驻？
* 前端 WebSocket 消息格式：直接透传 omp NDJSON 还是抽象为更高层协议？

## Requirements (evolving)

### 后端：omp RPC 桥接服务

* 新增 `backend/services/omp_bridge.py` — omp 子进程管理器
  - 启动 `omp --mode rpc` 子进程（bun 运行时）
  - 管理 stdin/stdout 的 NDJSON 通信
  - 会话管理：new_session, get_state, get_messages
  - 发送 prompt 命令，接收 AgentEvent 流
  - 优雅关闭（SIGTERM + 超时 kill）

* 新增 `backend/api/routes/agent.py` — Agent WebSocket 端点
  - `WS /api/agent/ws` — 前端连接，双向消息
  - 前端消息 → 转为 omp NDJSON 命令 → 写入 omp stdin
  - omp stdout 事件 → 转为前端 WebSocket 消息 → 推送前端
  - 连接断开时清理 omp 会话

### 前端：Web TUI Agent 模式

* 改造 `frontend/src/views/AgentTUI.vue` — 新增 Agent 模式
  - WebSocket 连接到 `/api/agent/ws`
  - 用户输入 → 发送 prompt 命令
  - 接收 AgentEvent → 渲染 AI 消息、工具调用卡片、进度
  - 保留现有命令模式作为 fallback（直接调 API）

### 消息协议

* 前端→后端：`{ type: "send_message" | "get_status" | "new_session" | "abort", content?: string, session_id?: string }`
* 后端→前端：`{ type: "agent_message" | "tool_call" | "tool_result" | "status" | "ready" | "error", ... }`
* 后端内部将 send_message 翻译为 `{"type":"prompt","message":"..."}` NDJSON
* 后端内部将 omp 的 AgentEvent 翻译为高层抽象事件推送前端

## Acceptance Criteria (evolving)

* [ ] 后端能启动 omp --mode rpc 子进程并完成 NDJSON 握手
* [ ] 前端 WebSocket 连接成功后收到 ready 事件
* [ ] 用户输入 prompt → omp agent 响应 → 前端显示 AI 消息
* [ ] omp 调用 xhs_workflow_start 工具 → 前端显示工具调用卡片
* [ ] omp 工具结果 → 前端显示结果
* [ ] 连接断开后 omp 会话正确清理

## Definition of Done

* 后端 omp bridge 通过类型检查
* 前端 Agent 模式功能可用
* Lint / typecheck green
* README 更新

## Out of Scope

* 多用户并发（MVP 单会话）
* Host tool 机制（omp 调用前端工具）
* omp 扩展 UI 交互（extension_ui_request）
* 会话持久化/恢复
* omp collab 模式

## Technical Notes

* omp RPC 协议详见 research/omp-rpc-protocol.md
* 需要 bun 运行时
* NDJSON 格式：每行一个 JSON 对象
* omp 启动后首先输出 `{"type":"ready"}`
* AgentEvent 类型：agent_start/end, turn_start/end, message_start/update/end, tool_execution_start/update/end
* xhsagent-ext 扩展在 omp 启动时自动加载（通过 omp.extensions 配置）
