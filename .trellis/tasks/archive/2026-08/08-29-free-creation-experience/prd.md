# Free Creation history next-step deep links

## Goal

让自由草稿历史页的状态文案与点击行为一致。当前卡片已经根据草稿状态显示“继续写作 / 检查并发布 / 修复并重试”等上下文动作，但所有动作都只打开 `/draft <id>` 详情，用户仍需手动寻找下一条命令。本轮把安全的下一步带入 TUI：通过草稿详情后，再按状态打开发布预览或表现采集。

## Requirements

### History panel

1. 保留现有状态判断与按钮文案。
2. 点击卡片主按钮时：
   - 已通过且未发布：跳转到自由创作深链，并携带 `action=publish`；
   - 上次发布失败且尚未发布：携带 `action=publish`，让 TUI 展示可再次确认的发布预览；
   - 已发布真实帖子：携带 `action=analytics`，让 TUI 直接刷新表现数据；
   - 普通草稿、需修订草稿、已发布但无真实帖子（如 dry-run）：保持现有仅打开详情的行为。
3. 普通草稿的既有路由参数保持不变，避免破坏书签和现有调用方。

### AgentTUI

4. 读取并白名单校验 `action` 查询参数，只接受 `publish` / `analytics`，未知值按普通草稿深链处理。
5. 深链初始化时先渲染 `/draft <id>` 详情；详情完成后：
   - `publish` 执行 `/publish <id>`（仅预览，不带 `confirm`，绝不自动发布）；
   - `analytics` 执行 `/analytics <id>`；
   - 无动作时不追加命令。
6. `/analytics` 仅对真实帖子触发。History 只能从 `published` 且 `post_id` 不以 `mock_` 开头的详情记录生成该动作；mock 发布仍只打开详情并展示 dry-run 提示。
7. 深链追加命令使用终端已有的命令回显风格，并继续沿用现有账号解析、错误处理和 i18n。

### Tests and docs

8. 增加 History 路由动作映射测试，以及 AgentTUI 的发布预览 / 表现采集深链测试。
9. 更新 `.trellis/spec/frontend/component-patterns.md` 的自由草稿历史导航约定，记录动作深链必须保持账号和 draft_id，并且发布动作只能进入二次确认预览。

## Acceptance criteria

1. History 中“检查并发布”和“修复并重试”点击后会展示详情并自动显示发布预览，`client.post('/free/publish')` 在没有用户输入 `confirm` 时不会调用。
2. 已发布真实帖子点击后会展示详情并触发表现采集；mock 发布、普通草稿和需修订草稿不触发额外命令。
3. `action` 非法或缺失时行为与现有 `draft_id` 深链完全一致。
4. 账号参数始终保留，且现有自由模式命令、History 过滤、TUI 初始欢迎页不回归。
5. 前端 focused tests、type-check、i18n 检查和 production build 通过。

## Out of scope

- 不改变后端 API、草稿数据模型或发布确认协议。
- 不自动确认发布，不新增批量发布或批量采集。
- 不把普通草稿详情改造成新的富文本编辑器。
