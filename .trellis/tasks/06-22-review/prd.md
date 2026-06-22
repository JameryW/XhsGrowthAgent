# review 环节选择发布账号

## Goal

在审核（review_gate）环节增加账号选择器，让用户针对**当前这条笔记**选择用哪个小红书账号发布，而不是只能用全局"活跃账号"。支持多账号场景下按笔记切换发布主体。

## What I already know

- `XHSGrowthState` 已有 `account_id`（schema.py:125）和 `publish_options`（schema.py:132）字段，但 publisher 没用来选账号
- `publisher` 节点的 `_get_publisher()`（tools/xhs/publisher.py:13）直接读 `Settings().platform.cookie` —— 即全局活跃账号的 cookie（由 `activate_credentials` 注入 os.environ）
- 账号系统：DB 存账号 + 加密凭证（`backend/db/accounts.py`），`activate_credentials(account_id)` 把某账号凭证热加载进 os.environ，全局只有一个"活跃账号"
- review_gate 是 human-in-the-loop 中断点（`compile_graph_dev` 在 review_gate interrupt），用户审核后 resume
- `HumanFeedback` 子状态（substates.py:109）有 decision/comments/revisions/reviewer，可扩展放选中账号
- 前端 Review.vue 有审核 UI + 发布确认弹窗（showPublishConfirm），已有 NeonButton 操作区
- 账号列表 API 已有：`GET /accounts`（list_accounts）返回所有账号

## Assumptions (temporary)

- 用户希望"每条笔记独立选账号"，而非"切换全局活跃账号"
- 账号列表从现有 `GET /accounts` 取，复用已有账号管理
- 发布时按选中账号临时加载该账号 cookie，不改变全局活跃账号状态

## Requirements (evolving)

- review 审核页可看到所有 XHS 账号列表
- 用户为当前笔记选定一个发布账号
- 发布节点**按选中 account_id 从 DB 取解密 cookie**，传给 XHSClient，不动全局 os.environ
- 不改变全局活跃账号状态（其他笔记/并发发布互不干扰）
- 需新增按 account_id 取 cookie 的 DB 函数（复用 `list_credentials(account_id)` 解密逻辑）
- 账号选择器放在**发布确认弹窗**（showPublishConfirm）内，与发布动作同上下文
- 扩展 `PublishOptions` 加 `account_id` 字段，随 review submit 写入 state，publisher 读取
- 默认选中当前全局活跃账号

## Technical Approach

**数据流**：
1. Review.vue 发布确认弹窗 → 拉账号列表（`GET /accounts`）→ 下拉选账号
2. submit_review 时 `PublishOptions.account_id` 随 decision 传入
3. `submit_review`（review.py:127）把含 account_id 的 publish_options 写入 state
4. `PublisherAgent.execute` 读 `publish_options.account_id`：
   - 有值 → 从 DB 取该账号解密 cookie/user_id → 构造 XHSClient
   - 无值 → fallback 到 `settings.platform.cookie`（兼容旧路径）
5. 发布完成，cookie 失效时返回 auth_failed 错误

**改动文件**：
- `backend/api/routes/review.py`：`PublishOptions` 加 `account_id: str | None`
- `backend/db/accounts.py`：新增 `get_account_cookie(account_id) -> (cookie, user_id)` 复用解密
- `backend/agents/publisher.py`：execute 按 account_id 取 cookie
- `frontend/src/types/review.ts`：`PublishOptions` 加 `account_id`
- `frontend/src/views/Review.vue`：发布确认弹窗加账号选择器
- `backend/api/generated/models.py`：OpenAPI 同步（contract test）

## Acceptance Criteria (evolving)

- [ ] review 页发布确认弹窗展示账号选择器，默认选中当前活跃账号
- [ ] 用户选定账号后，发布使用该账号 cookie
- [ ] 不改变全局活跃账号状态（其他笔记不受影响）
- [ ] 选中的账号 cookie 失效时返回 `auth_failed`，未配 cookie 返回 `no_cookie` 明确错误
- [ ] dry_run 模式下账号选择器仍可用（记录 account_id 到 publish_result，但不真发）
- [ ] needs_revision/rejected 决策时账号选择器隐藏/禁用
- [ ] OpenAPI contract test 同步（generated/models.py）

## Definition of Done (team quality bar)

- Tests added/updated（publisher 按账号取 cookie 的单测）
- Lint / typecheck / CI green
- 前端 i18n 文案补充
- Rollout/rollback 考虑（多账号并发发布场景）

## Technical Notes

- 关键文件：`backend/tools/xhs/publisher.py`、`backend/services/xhs_publisher.py`、`backend/agents/nodes/review_gate.py`、`backend/agents/nodes/publisher.py`、`backend/state/substates.py`、`frontend/src/views/Review.vue`
- 约束：`activate_credentials` 是全局 os.environ 注入，并发发布时多账号会互相覆盖 —— 这是核心设计难点
- 账号凭证读取：`list_credentials(account_id)` 返回解密后的 `cred.value`
