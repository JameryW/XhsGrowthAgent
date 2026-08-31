# 自由草稿预览连续审阅队列

## Goal

把现有自由草稿快速预览抽屉升级为连续审阅体验：用户在保持 History 当前账号、搜索和筛选上下文的同时，可直接在抽屉内切换上一条/下一条草稿，不必反复关闭、重新定位卡片和再次打开预览。

## What I already know

- `FreeDraftHistoryPanel` 已拥有账号隔离的 `filteredDrafts` 顺序和当前 `previewTarget`。
- `FreeDraftDetailDrawer` 已支持 `draftId` 变化时 abort 旧请求、generation guard、稳定壳层和焦点陷阱，因此可安全承载同一抽屉内的草稿切换。
- 抽屉当前只读，并通过 `continue(FreeDraftRecord)` 把完整详情交回 History 生成安全 TUI 下一步。
- 搜索和筛选是当前用户可见工作队列；连续审阅不应偷偷跳到筛选外草稿。

## Requirements

### Queue ownership

- `FreeDraftHistoryPanel` 以当前 `filteredDrafts` 为唯一审阅队列，保持现有排序，不额外请求、不跨账号聚合。
- 选中草稿的队列位置由 `draft_id` 派生；不得保存可能在筛选/刷新后失真的数组索引。
- 当筛选结果重排时重新计算位置；当刷新或数据变化使当前草稿不再属于队列时关闭抽屉。
- 账号变化继续立即关闭抽屉并中止旧详情读取。

### Drawer navigation

- 抽屉稳定标题区显示双语队列位置“第 N 条，共 M 条”。
- 提供至少 44px 的“上一条”“下一条”按钮；首条禁用上一条，末条禁用下一条，不循环。
- 点击导航只更新 `previewTarget`，保持抽屉、History 路由、搜索、筛选和页面滚动不变。
- 切换草稿时保留抽屉壳层并展示现有 loading 状态；旧响应继续由 abort + generation/account/draft guards 丢弃。
- 支持 `Alt+ArrowLeft` / `Alt+ArrowRight` 键盘导航；在禁用边界无动作。事件来自 input、textarea 或 contenteditable 时不得劫持。
- 导航控件和计数在 320px 移动端可换行、无横向溢出，并保留显式 dark variants。

### Current-detail safety

- 切换后底部上下文主动作必须使用当前草稿摘要文案；加载完成后只接受当前 `draftId` 的详情 `continue` 事件。
- 下一步仍复用当前完整详情，不重复读取；publish 只进入预览，analytics 只允许当前真实、非 `mock_*` `post_id`。
- 导航本身保持只读，不调用 PATCH、evaluate、publish、analytics 或 delete API。

### Localization, spec, and tests

- 新增所有队列计数、上一条/下一条和键盘提示文案的英中 locale keys。
- 扩展 drawer 与 History 测试：单条队列、边界禁用、前后切换、筛选顺序、刷新移除、账号变化、Alt+方向键、旧详情丢弃、当前详情下一步和无写请求。
- 更新前端组件规范，记录“父列表拥有过滤队列、抽屉只发导航意图、位置由 ID 派生”的约定。

## Acceptance Criteria

- [ ] 用户可在抽屉中连续查看当前筛选结果，位置计数准确且首尾不循环。
- [ ] 前后切换不改变 History 路由、搜索、筛选或滚动上下文。
- [ ] 快速切换时旧详情不能覆盖当前草稿，当前详情的下一步不会使用上一条身份。
- [ ] 当前草稿被刷新移除或账号切换时抽屉关闭，不导航也不写数据。
- [ ] 鼠标、触摸和 `Alt+←/→` 均可操作；边界禁用、焦点陷阱和 320px 布局正确。
- [ ] 单条队列可理解地显示 `1 / 1`，两个导航按钮均禁用。
- [ ] 聚焦测试、type-check、i18n parity、production build 和 `git diff --check` 通过。

## Definition of Done

- 只修改前端队列/抽屉表现、双语、测试与组件规范；不引入依赖或后端变化。
- 实现与 Trellis check 均逐条验证 PRD。
- 变更提交，任务归档，会话记录完成。

## Technical Approach

- 在 History 中新增 `previewIndex`、`previewPosition`、`canPreviewPrevious/Next` 等 computed，索引每次从 `previewTarget.draft_id` 在 `filteredDrafts` 中查找。
- 父组件处理 `previous` / `next` emit 并替换 `previewTarget`；drawer 接收位置、总数和边界 props，只负责展示与发意图。
- drawer 在现有 dialog keydown 上增加守卫后的 Alt+方向键处理，调用 emit 前检查边界 props。
- watch 当前过滤队列的 ID 集合：打开期间若目标 ID 消失则关闭；目标仍存在时保留抽屉。
- 沿用现有详情加载、焦点、只读和安全深链逻辑，不新建 store 或 API adapter。

## Decision (ADR-lite)

**Context**: 连续审阅需要明确“下一条”属于哪个集合，并应避免索引在过滤/刷新后漂移。

**Options considered**:

1. 当前 `filteredDrafts` 作为队列、按 `draft_id` 派生位置；
2. 打开时复制固定快照队列；
3. 后端分页式详情游标。

**Decision**: 采用当前 `filteredDrafts` + ID 派生位置。它与用户当前可见结果一致，不新增服务端协议；队列变化时可明确关闭失效目标。

**Consequences**: 筛选结果变化会实时改变总数/位置；本轮不支持跨服务器 100 条上限或固定快照式审阅。

## Expansion Sweep

- Future evolution: 可在有明确收益后增加相邻详情预取或“待处理队列”，本轮保持零额外读取。
- Related scenarios: 继续遵循 Analytics/Evaluation 抽屉的焦点和移动端模式，并保持 Free Draft 安全下一步语义。
- Failure/edge cases: 单条队列、过滤后目标消失、快速多次切换、迟到响应、账号变化和当前详情/摘要身份不一致。

## Out of Scope

- 不循环导航、不随机跳转、不跨筛选或跨账号。
- 不预取相邻详情、不新增后端分页/游标。
- 不把队列位置写入 URL、浏览器历史或全局 store。
- 不增加编辑、复制、删除、评估、发布或表现采集动作。

## Technical Notes

- Likely files: `FreeDraftHistoryPanel.vue`, `FreeDraftDetailDrawer.vue`, their focused specs, both locale files, and `.trellis/spec/frontend/component-patterns.md`.
- Existing stale-response and focus-trap tests are the baseline; new tests should extend rather than duplicate them.
- Complexity: moderate; frontend-only state composition with async identity and accessibility boundaries.
