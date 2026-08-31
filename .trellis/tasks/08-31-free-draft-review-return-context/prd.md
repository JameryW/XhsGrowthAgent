# Preserve Free Draft Review Return Context

## Goal

让用户从 History 的自由草稿筛选/预览队列进入 Free Creation TUI 后，能通过显式入口安全返回原账号、筛选、搜索和草稿位置，继续审阅而不必重建上下文。

## Problem

当前 History 已支持账号隔离、搜索、状态筛选、预览抽屉和连续上一条/下一条，但这些状态只保存在 `FreeDraftHistoryPanel` 的本地响应式变量中。用户点击“继续写作 / 审阅发布 / 采集表现”进入 TUI 后：

- TUI 没有返回该审阅队列的显式入口；
- 浏览器返回会重新挂载 History，搜索和草稿筛选丢失；
- 无法可靠恢复刚才正在预览的草稿；
- History 和 TUI 若各自手写 query，会重复账号、筛选和输入校验规则。

## Requirements

### Deep route-context module

- 新建一个纯前端、无 I/O 的深模块，统一拥有自由草稿审阅上下文的接口、白名单、规范化和路由 query 编解码。
- 上下文只包含：账号、状态筛选、搜索文本和可选草稿 ID；不得接受任意返回 URL、路由名或重定向目标。
- 状态筛选只接受现有 `all / needs_attention / unpublished / published / publish_failed / evaluated / unevaluated`。
- 所有 query 只接受单个字符串；数组、未知状态、空白账号/草稿 ID 和超长搜索文本必须安全降级或截断。
- 模块输出 History query 时固定 `tab=free-drafts`，账号始终来自已解析的当前 owned account，不信任原始返回账号。
- 模块输出 TUI 来源 query 时使用命名空间字段，不能覆盖 `mode / account_id / draft_id / action`。

### History URL state and restoration

- `FreeDraftHistoryPanel` 从安全 query 初始化草稿状态筛选、搜索和待恢复草稿 ID。
- 搜索、筛选和预览选择变化时，通过 `router.replace` 同步命名空间 query；不得为每次输入或上一条/下一条制造浏览器历史栈噪声。
- 首次从 TUI 返回时保留 query 上下文；普通账号切换仍按现有契约清空筛选、搜索和预览，且移除旧账号的草稿 query。
- 草稿列表加载完成后，仅当待恢复 ID 仍属于当前账号的当前过滤结果时打开抽屉；不存在或被过滤掉时清除待恢复 ID，不跨筛选寻找。
- 路由 back/forward 或外部 query 更新应重新应用安全上下文，不触发额外写 API。
- 现有刷新移除、账号切换、迟到响应和抽屉焦点安全继续成立。

### TUI return entry

- History 的“新建草稿”和所有草稿下一步深链都携带安全来源上下文。
- TUI 仅在 `mode=free` 且来源上下文有效时显示双语“返回草稿审阅”入口。
- 返回入口导航到 `history`，带显式账号、`tab=free-drafts`、状态筛选、搜索和可选草稿 ID；不得使用任意 `return_to` 字符串。
- TUI 必须使用已经解析为 owned account 的账号，而不是未经验证的 `account_id` query。
- 返回入口不执行命令、不自动提交 prompt、不调用后端，也不改变工作区 active account。
- 桌面与移动端入口均键盘可达、具备清晰焦点样式；移动端触控目标至少 44px。

### Localization and tests

- 新增所有可见文案的英中 locale key，并保持 key parity。
- 为深模块编写接口级测试，覆盖合法往返、未知/数组/空白/超长 query、固定 History 目标和字段冲突隔离。
- 扩展 History panel 测试：query 初始化与同步、返回后恢复、目标不存在、筛选外目标、账号变化清理、路由更新和无额外写请求。
- 扩展 AgentTUI 测试：来源入口显隐、使用 resolved owned account、安全返回 query、不自动执行命令、移动端可操作语义。

## Acceptance Criteria

- [ ] 从任意草稿下一步进入 TUI 后，可一键返回同一账号的 Free Drafts tab，并恢复搜索、状态筛选和原草稿抽屉。
- [ ] 新建草稿入口也可返回原审阅列表，但不会伪造草稿选择。
- [ ] 无来源、非 free 模式或无有效 owned account 时不显示返回入口。
- [ ] 未知/恶意/数组 query 不能控制任意导航目标，也不能跨账号恢复草稿。
- [ ] 返回、恢复和 query 同步不调用草稿写 API、不自动提交 TUI prompt、不切换 workspace active account。
- [ ] 普通账号切换和目标被过滤/删除时清除旧上下文；刷新与迟到响应安全不回退。
- [ ] 聚焦测试、type-check、i18n parity、production build 和 `git diff --check` 全部通过。

## Technical Approach

- 增加 `utils/freeDraftReviewContext.ts`，以少量纯函数作为唯一接口：解析 History/TUI query、构造 History query、构造 TUI 来源 query；内部隐藏字段名、白名单和长度限制。
- `FreeDraftHistoryPanel` 增加 `useRoute`，初始化安全上下文，并用小型 query 同步器更新自身拥有的字段；父 History 继续拥有账号和 tab 的大范围路由状态。
- 使用单独的 `pendingPreviewId` 恢复列表加载前的选择；列表响应成功后再按 `draft_id` 解析摘要，不保存数组索引。
- `continueDraft` / `newDraft` 从当前响应式状态构建来源 query，因此不依赖异步 URL replace 是否已经完成。
- `AgentTUI` 增加 `useRouter`，通过深模块解析来源上下文，并将 resolved owned account 传回模块构建 History query。
- 搜索 query 同步使用短 debounce；离开 History 前的 TUI query 直接读取当前值，避免最后一个字符丢失。

## Decision (ADR-lite)

**Context**: 需要跨 History 与 TUI 保存短期审阅状态，同时不能引入开放重定向、跨账号内容或全局 store。

**Options considered**:

1. 在 query 中传递任意 `return_to` 完整 URL；
2. 将草稿筛选与选择保存到 Pinia/sessionStorage；
3. 使用白名单审阅上下文模块，在两个路由间编码有限字段。

**Decision**: 采用选项 3。路由 query 是可刷新、可分享、浏览器导航友好的短期状态；深模块把验证和字段映射集中到一个 seam，History 与 TUI 只处理经过规范化的上下文。

**Consequences**: URL 会出现少量命名空间 query；搜索文本有明确长度上限；本轮不保存精确像素滚动位置。

## Expansion Sweep

- Future evolution: 可在明确需要时加入焦点返回标记或分页游标，但必须继续通过白名单接口演进。
- Related scenarios: 账号 local view 优先级、TUI account ownership 解析、抽屉 ID 派生队列位置、History tab query。
- Failure cases: 非法 query、账号被删除、返回期间列表为空、草稿被删除/过滤、快速切换账号、搜索 debounce 未触发即离开。

## Out of Scope

- 不保存或恢复页面像素滚动位置。
- 不增加草稿编辑、评估、发布、采集、删除或预取请求。
- 不新增后端字段、数据库、Pinia store、sessionStorage/localStorage。
- 不支持任意页面返回地址或跨账号聚合队列。
- 不改变 `/publish` 的显式 confirm 安全语义。

## Definition of Done

- 深模块、History/TUI 接入、双语和聚焦测试完成。
- 前端质量检查全部通过，Trellis check 逐条核验 PRD。
- 必要规范更新、提交、任务归档和会话记录完成。
