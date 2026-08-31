# 自由草稿历史快速预览抽屉

## Goal

让用户在账号隔离的 History 页面内完整核对自由草稿正文、评估建议和发布/表现状态，再决定是否进入 TUI 执行下一步。预览必须保留列表上下文，不自动编辑、评估、发布或采集数据。

## What I already know

- `FreeDraftHistoryPanel` 目前只渲染摘要；主按钮会直接跳转到 `/tui?mode=free`。
- `getFreeDraft(accountId, draftId)` 已提供账号隔离的完整详情读取，返回正文、图片路径、创作元数据、评估、锚点、发布结果和最近表现。
- 项目已有 Analytics / Evaluation 右侧抽屉与 `useFocusTrap`，约定 `Teleport`、`z-modal`、Esc/遮罩关闭、焦点恢复和 44px 触控目标。
- 既有自由创作 PRD 多次明确：History 不复制完整编辑器，编辑和发布确认仍由 TUI 负责。
- 当前主按钮的安全深链会先展示详情，再按状态进入发布预览或表现采集；新预览不能放宽这条安全边界。

## Requirements

### History card entry

- 每张自由草稿卡新增双语“预览”次要动作，保留现有上下文主动作与删除动作。
- 预览只读取数据并打开抽屉，不改变筛选、搜索、账号范围、滚动位置或路由。
- 同一张卡的标题与操作布局在 320px 以上不产生页面级横向溢出；所有按钮保持至少 44px 触控目标。

### Detail drawer

- 新建聚焦的 `FreeDraftDetailDrawer` 组件，接收 `accountId`、`draftId` 与打开状态，使用现有 typed API 读取详情。
- 桌面从右侧显示宽抽屉；移动端使用全宽/全高面板。抽屉包含稳定的标题栏、滚动内容区和底部下一步动作区。
- 展示以下已有字段，缺失项不制造假数据：
  - 标题、完整正文、hashtags、创建/更新时间；
  - niche、content angle、target audience、图片数量；
  - 评估分数、decision、summary、degraded 状态与 revision hints；
  - style/play/material 锚点；
  - 发布状态、失败类型/原因、真实帖子链接；
  - 最近 views/likes/collects/comments/shares、采集时间与浏览量趋势。
- 加载时保留稳定抽屉壳并显示骨架；失败时显示本地错误与重试；详情不存在或返回空记录时显示不可用状态。
- `accountId` 或 `draftId` 改变时中止旧请求并以 generation guard 防止迟到响应覆盖；账号切换时关闭旧抽屉。
- Esc、遮罩和关闭按钮均可关闭；打开时 trap focus，关闭时恢复到触发按钮；使用 `role=dialog`、`aria-modal` 和可本地化标题。

### Safe next step

- 抽屉底部主动作复用当前卡片的上下文文案与 TUI 深链规则。
- 已加载的完整详情可直接用于验证真实 `post_id`，不再为同一次点击重复请求详情。
- 发布动作仍只打开 `/publish <id>` 预览，不携带 `confirm`；analytics 仍只允许 `published=true` 且 `post_id` 非空、非 `mock_*`。
- 关闭抽屉或详情读取失败不触发任何命令。

### Localization and tests

- 所有新增可见文案同时加入 `en.json` 与 `zh-CN.json`。
- 增加 drawer 组件测试与 History 集成测试，覆盖正常、加载、错误/重试、字段缺失、账号/草稿切换、迟到响应、关闭/焦点和安全下一步。
- 更新前端组件规范，记录账号隔离详情抽屉与“详情数据复用后再生成动作深链”的约定。

## Acceptance Criteria

- [ ] 用户可从任意自由草稿卡打开完整预览，并在关闭后保留原列表上下文。
- [ ] 抽屉在桌面和 320px 移动端均无横向溢出，键盘焦点被约束且关闭后恢复。
- [ ] 详情字段按真实数据渲染；缺失、degraded、加载和失败状态均清晰且双语。
- [ ] 快速切换草稿或账号时，旧请求不能覆盖当前抽屉，旧账号抽屉会关闭。
- [ ] 抽屉主动作保留 `mode=free`、`account_id`、`draft_id`，发布只进入预览，analytics 只面向真实帖子。
- [ ] 打开、关闭或读取预览本身不执行 PATCH、publish、analytics 或 delete 请求。
- [ ] 聚焦测试、type-check、i18n parity、production build 与 `git diff --check` 通过。

## Definition of Done

- 组件、API 类型使用和测试完成；不引入新依赖。
- 视觉与可访问性复用现有 drawer/focus-trap 约定。
- 前端规范记录新增的可执行契约。
- Trellis check 复核通过并提交。

## Technical Approach

- `FreeDraftHistoryPanel` 继续拥有列表、筛选和选中草稿 ID；账号变化时清空选择。
- `FreeDraftDetailDrawer` 独立拥有详情请求、abort/generation guard、展示状态和焦点陷阱，并通过 `close` / `continue(detail)` 事件与父组件通信。
- 父组件把 `continueDraft` 扩展为接受完整 `FreeDraftRecord`；如果详情已经带真实 `post_id`，直接决定 action，否则沿用现有保守详情验证。
- 复用静态 Tailwind class、`dark-explicit`、语义 z-index 和 `useFocusTrap`，不新增 UI 框架。

## Decision (ADR-lite)

**Context**: 需要在不打断 History 浏览的前提下展示完整草稿，同时避免复制 TUI 编辑器或新增路由状态。

**Options considered**:

1. 独立右侧详情抽屉；
2. 卡片内联展开；
3. 新增完整详情路由。

**Decision**: 采用独立抽屉。它与现有 Analytics/Evaluation 模式一致，能容纳长正文和状态区块，并在关闭后自然回到原筛选/滚动位置。

**Consequences**: 增加一个专用组件和详情请求状态；暂不提供内联编辑，后续若需要编辑可在抽屉底部增加显式入口，而不改变当前只读契约。

## Expansion Sweep

- Future evolution: 可预留“比较版本”或“复制正文”入口，但本轮不实现。
- Related scenarios: 与 Analytics/Evaluation 抽屉保持焦点、关闭与移动端行为一致；与现有 TUI 下一步动作保持安全语义一致。
- Failure/edge cases: 重点处理账号切换、快速切换草稿、详情删除后失效、mock 发布和无 `post_id` 的旧记录。

## Out of Scope

- 不在 History 内编辑、保存、评估、发布、删除或采集表现。
- 不新增/修改后端接口、草稿模型或发布协议。
- 不新增详情路由、浏览器历史状态或抽屉深链。
- 不实现版本对比、图片预览画廊或复制到剪贴板。

## Technical Notes

- Likely files: `frontend/src/components/history/FreeDraftHistoryPanel.vue`, new detail drawer component, `frontend/src/api/free.ts`, both locale files, focused component tests, and `.trellis/spec/frontend/component-patterns.md`.
- Reference patterns: `EvaluationView.vue` note drawer, `Analytics.vue` post drawer, `frontend/src/composables/useFocusTrap.ts`.
- Complexity: moderate; multiple files with async and accessibility edge cases, but no new backend or dependency choice.
