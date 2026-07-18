# Dashboard 工作台（工作流实时展示页）UX 现状审计

审计日期：2026-07-17。审计范围：`frontend/src/views/Dashboard.vue`（路由 `/dashboard/:threadId?`）、`components/dashboard/` 8 个组件、被引用基础组件、`stores/workflow.ts`、`stores/realtime.ts`、`realtime/websocket.ts`、`api/workflow.ts`。`ProgressPhase.vue`/`StepIndicator.vue`/`WorkflowCardBody.vue`/`CelebrationEffect.vue` 未被 Dashboard 引用（仅 Review 页用），不纳入本审计。此页面为首次系统审计。

## 1. 页面结构与数据流

**组件树**（渲染顺序即首屏层级，`Dashboard.vue:191-441`）：

```
Dashboard.vue
├─ WorkflowTabBar            多工作流标签（≤8 个+overflow，store TAB_FOLD_LIMIT）
├─ DashboardSkeleton         isLoading && !workflowState 时整页骨架（:52）
├─ ErrorState                workflowStore.error（:53, :209）
├─ ErrorCard                 errorStore API 错误（:212-219）
├─ 状态 Hero（内联 section）  dashboardHero = getDashboardHero(phase/status/progress/isReplay)（:101-108, :222-260）
├─ nextAction 卡片            审核/等待/空闲/错误 四分支（:55-99, :263-274）
├─ Stale 恢复条（:277）/ 发布失败恢复卡（:296，按 recovery.action 渲染 5 种按钮）
├─ WorkflowHeader            CircularProgress+阶段名+ETA+状态徽章+MiniProgress
├─ 回放模式 banner（:351）
├─ Brief 内容摘要（:369）/ BriefFileUpload（:411）
├─ WorkflowTimeline          6 阶段节点+子步骤+agent_timeline 明细
├─ ContentCards              按阶段展示产物（trend/plan/copy/shooting/publish/analytics）+ RipplePanel（内含 accept/reangle/retopic 决策按钮）
├─ BloggerSelectionPanel     awaiting_blogger_selection（:431）
├─ OptimizationPanel         awaiting_draft/choice（DraftInput/VersionCompare/StyleCompare）
├─ ActionButtons             状态来源指示+等待文案+暂停/恢复/审核/查看帖子
└─ CelebrationModal          phase→completed 时弹 confetti（:115-124, :437）
```

**数据流**：`onMounted`（`Dashboard.vue:160-184`）从路由参数 `setThreadId` → `realtimeStore.connect()` → `refreshAllTabs()`（`workflow.ts:823` 并行刷新所有标签、自动关闭 404 标签）→ 对每个有效 tab `subscribeWorkflow` → `startPolling(3000|5000)`（`workflow.ts:969`，仅 `isRunning` 时续 poll，否则自停）。WS 事件经 `websocket.ts`（心跳 25s、指数退避重连 ≤5 次、`get_missed` 按 seq 恢复）→ `workflow.ts:444-678` 注册的 9 类 handler 增量更新 `workflowStates` Map。渲染统一读 `effectiveState`（`workflow.ts:188`，回放快照覆盖实时态），回放层级：`replayState` 合成状态（status 恒 `completed`）→ `liveWorkflowState` 保留实时语义。

**状态机映射**：`getDashboardHero`（`composables/dashboardHero.ts:35-115`）isReplay→violet / completed→emerald / error→rose / awaiting_review→violet / awaiting_*|paused|stale→amber / running→cyan / idle→pink，输出 icon+title+description+status+progress（clamp 0-100）。

## 2. 已具备能力

- **状态 Hero 六态切换**，纯函数可测，i18n 文案齐备（`dashboardHero.ts:35`、`zh-CN.json:249-268`、`en.json:249` 同步）
- **下一步动作卡**四分支（审核/等待输入/空闲开始/错误），`Dashboard.vue:55-99`
- **多工作流标签**：切换/关闭（带确认弹窗）/双击改名/overflow 折叠/localStorage 持久化（`WorkflowTabBar.vue`、`workflow.ts:339-388`）；404 标签自动清理（`workflow.ts:811-813, 849-852`）
- **进度高水位**：`_maxProgress` 防回退，reangle/retopic 不回退（`workflow.ts:207-209, 420-434`），有测试（`workflow.spec.ts:97`）
- **实时进度**：阶段进度条（hero `:252`、timeline `:374`）、ETA 估算（`WorkflowHeader.vue:76-113`）、当前 agent 徽章（`WorkflowTimeline.vue:361`）、agent 耗时明细可折叠（`:477-522`，含 formatDuration）
- **六类等待状态引导**：review→`/review` CTA；brief→上传组件+跳过（`Dashboard.vue:410-427`）；draft/choice→OptimizationPanel；blogger→选择面板（`BloggerSelectionPanel.vue`）；ripple→RipplePanel 决策按钮（`RipplePanel.vue:309-350`）；ActionButtons 等待文案条（`ActionButtons.vue:115-123`）
- **完成庆祝**：confetti+toast+焦点管理+Esc 关闭（`Dashboard.vue:115-128`、`CelebrationModal.vue:53-71`）；完成 CTA 去历史（`Dashboard.vue:255-259`）
- **错误恢复**：ErrorState 按错误类型给建议+重试/返回（`ErrorState.vue:17-60`）；结构化 publishError 5 种恢复动作（`Dashboard.vue:296-346`、`workflow.ts:392-400`）；stale 检测+恢复（`Dashboard.vue:277`）；ErrorCard API 重试（`:212`）
- **回放模式**：checkpoint 去重、有意义快照默认选中、sessionStorage 缓存 30s、分页加载、深链 `?replay=true`（`workflow.ts:1092-1221`、`Dashboard.vue:29-33`、`History.vue:99-102`）；节点点击切换快照（`WorkflowTimeline.vue:22-34`）
- **连接状态**：单一来源 `realtimeStore.connectionStatus`；connecting/reconnecting 顶部轻提示（`ConnectionStatus.vue:56`）；断线由 OfflineRecovery 承担（`App.vue:192`，符合文档约定）；恢复 toast（`realtime.ts:23-30`）；ActionButtons 状态来源指示（`:41-69`）
- **可访问性**：hero `aria-live`（`:232`）、progressbar role（`:252, :374`）、timeline 键盘导航 ←→/Home/End（`WorkflowTimeline.vue:317-337`）、状态徽章 `role="status"`（`WorkflowHeader.vue:175`）、hero 进度条 `motion-safe` 降级（`Dashboard.vue:253`）、按钮 min-h-11（`:256, :271`）
- **加载/空态区分**：整页骨架 vs 内容卡骨架 vs idle 空态（`ContentCards.vue:151-175`）

## 3. UX 问题与优化机会

### P0
- **回放深链时机错乱**：setup 阶段（`Dashboard.vue:30-33`）读 `activeThreadId` 时路由参数尚未写入（`onMounted:162` 才 `setThreadId`）。后果：新会话打开 `/dashboard/X?replay=true` 时 `activeThreadId` 为 null → `enterReplayMode` 静默 return（`workflow.ts:1093`），回放根本不进入；若 localStorage 残留另一线程 Y → 加载 Y 的快照却把 X 设为活跃，状态混杂。History 的回放入口（`History.vue:99-102`）恰受此 bug 影响。
- **回放模式误触发庆祝**：`watch(currentPhase)`（`Dashboard.vue:115-124`）基于 `effectiveState`；运行中进入「phase=completed 的检查点」回放时 phase 由非 completed→completed，弹庆祝窗+发"已完成"toast，直接违反文档"不把快照误标为已完成"（`docs/frontend-ux-optimization.md:24`）。hero 有 isReplay 守卫，庆祝没有。

### P1
- **进度高水位被旁路**：三处进度显示都优先读 `effectiveState.progress_percent`（`Dashboard.vue:105`、`WorkflowHeader.vue:31-34`、`WorkflowTimeline.vue:145-148`），该值来自后端原始数据；`_maxProgress` 只在 `progress_percent` 为 null 时兜底。reangle/retopic 阶段回退时用户可见进度条倒退，与 `workflow.ts:207-209` 的设计意图相悖。
- **等待态 CTA 是死链**：nextAction 对 awaiting_brief/draft/choice/ripple/blogger 统一 `path: '/dashboard'`（`Dashboard.vue:72-78`）——已在 dashboard，点击仅清掉 URL 里的 threadId，无滚动/聚焦到对应操作面板。`ActionButtons.vue:161-173` 的"编辑草稿"按钮同样 push `/dashboard`，是 Dashboard 页内的空操作按钮。
- **错误恢复路径分裂且文案错配**：错误时同时可能出现 4 个错误面（ErrorState `:209`、ErrorCard `:212`、hero rose 态、timeline 错误横幅 `WorkflowTimeline.vue:368`）；nextAction 错误分支（`Dashboard.vue:89-97`）复用 `startCta`（"开始创作"）文案跳 `/start`，与 ErrorState 的"重试=resume"（`ErrorState.vue:45-52`）指向相反动作，用户无所适从。
- **长页面无锚点/折叠策略**：运行到 creating 后页面顺序为 hero→下一步→header→brief 摘要→时间线→多张产物卡→blogger→optimization→按钮，等待决策面板（OptimizationPanel/BloggerSelectionPanel/Ripple 决策）位于 ContentCards 之后，需长滚动才能触达，与"下一步动作明确"冲突；无"跳转到待办"机制。
- **时间线运行中信息弱**：子步骤仅图标+pulse，无耗时累计；ETA 用 `progress%20` 的粗略启发（`WorkflowHeader.vue:92-98`）误差大；agent 明细默认折叠且正在运行的 entry 只显示 `—`。

### P2
- **进度可视化冗余**：hero 进度条+CircularProgress+MiniProgress+timeline 进度线四处同值重复（`Dashboard.vue:252`、`WorkflowHeader.vue:125,148`、`WorkflowTimeline.vue:374`）。
- **标签页触控与可发现性**：关闭按钮 `p-0.5` 约 20px（`WorkflowTabBar.vue:228`）、回放子步骤 28px 点击目标（`WorkflowTimeline.vue:431,442`）低于 44px 规范（`docs/frontend-ux-optimization.md:36`）；双击改名在触屏不可用。
- **切标签不同步 URL**：`switchTab`（`workflow.ts:339-349`）不 `router.replace`，深链刷新后回到旧 threadId。
- **WS 永久断连无入口**：重连次数用尽后（`websocket.ts:314-317`）ConnectionStatus 不显示 disconnected（`ConnectionStatus.vue:56`），页面仅剩 ActionButtons 底部小字指示，无手动重连按钮。
- **庆祝模态硬编码 emoji/静态数据**：统计格是 ✓/100%/🎉 装饰（`CelebrationModal.vue:124-137`），非真实数据，且无"查看帖子/再来一篇"转化 CTA，只有"返回工作台"。
- **庆祝 confetti 无降级**：`animate-confetti`/`bounce-slow`（`CelebrationModal.vue:178-205`）无 `prefers-reduced-motion` 媒体查询，违反文档动效降级原则。
- **ContentCards 骨架歧义**：运行中无数据时 3 张脉冲骨架（`:160-175`）在 creating 长阶段会一直显示，无"当前在做什么"文案；draft/optimization 区块用硬编码 blue-* 而非主题 token（`:406-413`）。
- **性能**：`RIPPLE_PROGRESS` 高频事件每次重建 map 并触发 ContentCards 整树重渲（`workflow.ts:549-571`），无节流；`WorkflowTimeline` 每个 substep 渲染调用多次 `getStatus`/`agentIndex`（O(n²)，n 小可接受）；`startPolling` 与 WS 双通道同时更新无去抖。
- **i18n 回退文案**：`ContentCards.vue:606-607` 用 `|| '分析传播效果'` 硬编码中文兜底，绕开 t() 缺失告警。

## 4. 技术约束

- **样式**：Tailwind + 自定义 token（`neon-pink/peach/cyan`、`liquid-glass-*`、`btn-sm`），暗色 `html.dark` + `dark:` 变体；Hero 六 tone 渐变硬编码于模板（`Dashboard.vue:224-231`），新状态需同步该 class map。主样式入口 `styles/main.css:968` 已有全局 reduced-motion 规则。
- **i18n**：所有文案经 `t()`，`zh-CN.json:244-`/`en.json:244-` 双文件同步；store 内用 `i18n.global.t`（`workflow.ts:22-24`）。新增 key 必须双语。
- **动效降级**：约定 `motion-safe:` 或 `@media (prefers-reduced-motion: reduce)`（示例 `CheckpointRail.vue:170`）；CelebrationModal/timeline substep-expand（`WorkflowTimeline.vue:528-548`）当前未降级。
- **测试**（`frontend/tests/`）：`composables/dashboardHero.spec.ts`（clamp/回放不误标完成）、`components/WorkflowTimeline.spec.ts`（gate 等待不误标 running）、`stores/workflow.spec.ts`（进度单调、标签管理、回放状态隔离/深链/缓存水合）、`components/WorkflowReplay.spec.ts`、`integration/theme1-loading/theme2-error/theme3-animation.spec.ts`、`ErrorCard.spec.ts`、`SkeletonLoader.spec.ts`。**缺口**：无 Dashboard.vue 整页测试、无 ActionButtons/ContentCards/WorkflowTabBar/nextAction/庆祝触发条件测试——改 P0/P1 项前应补。
- **不可违背的既有约定**（`docs/frontend-ux-optimization.md`）：状态来源只用 `workflowStore.effectiveState`；`connectionStatus` 是连接状态唯一来源，断连条由 OfflineRecovery 统一渲染；API 重试只刷新当前 threadId；空态需区分"无数据/加载失败"；改动不得改变工作流 API 语义。
