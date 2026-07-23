# 停止生成与队列反馈审查

## 当前证据

- `handleTermData` 的 Ctrl+C 只调用 `sendAgentMessage({type: "abort"})`，没有清除 `isProcessing`。
- 自由模式 quick actions 在 `isProcessing` 时全部禁用，因此没有可点击的停止生成入口；移动输入栏也只有发送按钮。
- 自然语言消息队列是普通数组，终端会输出“消息已暂存”，但模板没有响应式队列长度。
- Agent 事件目前分别更新 `isProcessing`，但没有独立的“已发送 Agent turn”状态，无法区分本地 `/suggest` 等操作和 Agent 生成。

## 设计决策

### 1. 独立追踪 Agent turn

新增 `agentTurnProcessing`，仅在自然语言消息真正发送或收到 Agent `running` 状态时置为 true；在 abort、完成、idle、错误、session_end、断线时置为 false。停止按钮只由该状态驱动，避免干扰自由草稿 API 命令。

### 2. 统一停止路径

Ctrl+C、slash `/abort` 和自由模式快捷按钮复用同一个 `requestAgentAbort`。该函数负责发送 abort、立即复位本地状态、输出反馈并重绘 prompt；发送失败时使用已有 Agent 不可用文案，仍然释放本地忙碌状态。

### 3. 响应式队列计数

用 `ref` 镜像组件实例内的待发送数组长度，并通过入队、出队、清空三个辅助路径统一维护。计数只用于当前入口的可见反馈，不改变既有最多 5 条和不持久化约束。

## 风险与验证

- abort 后服务端可能仍发送一个迟到的完成事件；事件处理必须保持幂等，不重新显示 spinner。
- `/suggest`、`/drafts` 等本地命令不应显示停止按钮。
- 需要验证队列在新会话、重连 flush 和移动端按钮场景下的计数变化。
