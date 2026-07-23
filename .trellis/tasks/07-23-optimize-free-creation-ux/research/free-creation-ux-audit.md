# 自由创作模式交互审计

日期：2026-07-23

## 现状证据

审计对象：`frontend/src/views/AgentTUI.vue`、`frontend/src/locales/{zh-CN,en}.json`、`.trellis/spec/backend/free-creation.md`。

### 1. 默认 Agent 分发缺少 `/start`

- 首屏自由模式提示 `tui.freeCmdStart` 把 `/start` 说明为“开启新会话”。
- `SLASH_COMMANDS` 已包含 `/start`，命令模式的 `processSlashCommand` 也已将自由模式 `/start` 映射到 `sendAgentMessage({ type: 'new_session' })`。
- 默认 Agent 模式的 `processAgentCommand` 只有 `/status`、`/new`、`/abort`、`/mode`、`/help`、`/clear` 及草稿命令，没有 `/start`，因此自由模式默认路径与提示不一致。

### 2. 未连接时普通输入无反馈

- `processAgentCommand` 先把 `isProcessing` 设为 true，然后对普通文本直接调用 `sendAgentMessage`。
- `sendAgentMessage` 在 socket 不存在或不是 OPEN 时直接 return，没有返回值；调用方因此不知道消息未发送，也不会恢复 `isProcessing`。
- 自由模式首次挂载会先渲染终端再异步建立 WebSocket，用户很容易在连接窗口提交首条创作目标。

### 3. 自动重连结束后缺少恢复路径

- `onclose` 在重试次数耗尽后切换到命令模式并写入终端文案，但模板只显示断开圆点，没有 retry 按钮或连接状态文字。
- 移动端 placeholder 只判断 `mode === 'agent' && wsConnected`，自由模式断开后显示普通“输入命令”，与仍可输入创作目标/暂存消息的产品语义不符。

## 设计结论

本轮将改动限定在 TUI 交互层：增加显式连接状态、有限的会话内待发送队列、手动重连与新会话快捷操作，并修复 Agent 分发器的 `/start`/工作流隔离提示。后端 free 路由、omp host tool 和账号/草稿数据契约无需变化。

## 风险与验证

- 队列只在自由模式普通文本路径启用；固定工作流模式不改变发送语义。
- socket 只允许一个 CONNECTING/OPEN 实例；重试前清除 pending timer。
- 队列在组件卸载时随实例销毁，不持久化，避免旧消息误发到新账号。
- 通过 i18n parity、Vue 类型检查、现有前端测试和针对连接/命令逻辑的回归检查验证。
