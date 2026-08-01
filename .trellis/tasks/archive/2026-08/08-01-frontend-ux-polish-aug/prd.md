# 前端多页面布局 / 交互 / 视觉整体优化

## 背景

对前端六个区域（全局 shell、首页/登录、工作台、审核、分析与评估、次级页面）做了系统走查，发现约 70 个用户可感知的问题。本任务按优先级分批修复，不改工作流状态语义、实时连接单一来源或任何 API 形状。

## 硬约束（所有改动必须满足）

- 所有可见文案走 `t()`，`en.json` 与 `zh-CN.json` 同步补齐。
- 动画遵循 `prefers-reduced-motion` 降级（`.trellis/spec/frontend/animation-patterns.md`）。
- 触控目标 ≥ 44px；状态不得仅靠颜色传达。
- 不改 `workflowStore.effectiveState` 语义、realtime 连接状态来源、账号上下文来源。

## P0 — 跨页面高价值修复（本批必做）

### A. 全局 reduced-motion 补全（多区域共同命中，spec 违规）
- `main.css` reduced-motion 块未覆盖：Tailwind `animate-pulse` / `animate-spin` / `animate-spin-slow`、`.scale-bounce-animation`、`.mesh-drift-3`、`review-spin`、modal scale 过渡；`html { scroll-behavior: smooth }` 无降级。
- `AccountScopeBar.vue:102` `scrollIntoView({behavior:'smooth'})` 未走 `useReducedMotion`。

### B. 移动端固定元素堆叠
- `App.vue:178` ThemeToggle（`fixed right-3 top-3 z-[80]`）压住 ConnectionStatus 药丸（含重连按钮）与 Toast → 按断点错开 + 收敛 z 层级。
- `Review.vue:1530` 审核吸底操作栏被 `MobileTabBar`（fixed bottom-0 z-50）遮挡 → `bottom-[calc(4.5rem+env(safe-area-inset-bottom))] md:bottom-0`。

### C. 触控目标 < 44px（统一补齐）
- `ConnectionStatus.vue:80` 重连按钮、`StatusFilterBar.vue:39` 筛选 chip、`WorkflowStartForm.vue:410` 赛道 chip、`Dashboard.vue:515` 待办 chip、`EvaluationView.vue:785` 决策 chip、`Review.vue:1341` 图片移除 ×（加 aria-label）、`WorkflowStartForm.vue:526-572` switch（加 aria-label）。

### D. i18n 泄漏
- `PageTransition.vue:36` 硬编码英文 aria-label。
- `WorkflowCardBody.vue:89-94` / `ContentCard.vue:136`：`views`/`likes`/`% viral`/`+N more` 硬编码。
- 原始枚举直出：`Review.vue:1190` workflow_mode、`ContentCards.vue:422,583` severity/status、`VersionCompare.vue:132` severity。
- `TrendChart.vue:50` SR 摘要硬编码 "avg"。

### E. 死路 / 功能性 bug
- `ActionButtons.vue:214` "Edit Draft" 从 dashboard 跳 `/dashboard` 死按钮 → 锚点滚动到草稿输入。
- `NotFound.vue:43` `router.back()` 直达坏链时死路 → 无历史时回 `/start`。
- `Showcase.vue:132` `restoreQuery` 不同步 `searchInput`（URL 带 q 时搜索框为空）。
- `History.vue:1076-1094` 移动端纯图标按钮无 aria-label。
- `Login.vue:82-159` 版本号桌面端渲染两次。
- `WorkflowStartForm.vue:94-98` 账号 API 失败时静默回退 `default` 伪账号（spec 禁止）→ 空/错误态 + 引导去账号管理。

### F. 暗色模式破坏
- `ContentCards.vue:600-608` amber 渐变无 dark 变体（白字奶油底不可读）。
- `VersionCompare.vue` / `StyleCompare.vue` 系统性缺 dark 变体。
- `main.css:1014-1022` `.action-card` 未加入暗色卡片覆盖列表。
- `Review.vue:1698-1705` 分数/决策徽章 raw hex 无 dark 变体。
- `PreLaunchChecklist.vue:202` 暗色单元格底色破碎感。

### G. Tailwind 动态类名被 purge（视觉从不渲染）
- `MetricCard.vue:61`、`MiniProgress.vue:55`、`skeletons/ContentCardSkeleton.vue:19`、`TrendChart.vue:133`、`EngagementChart.vue:130` → 静态映射表。

### H. 交互反馈缺失
- `Analytics.vue:511-544,973-981` 导出 CSV 无 loading/成功失败 toast。
- `Review.vue:1557` Reject 无 loading（转的是 Approve/Revise）。
- `History.vue:604-624,1049-1075` 行操作 await 无 pending 态、可双击重发。
- `Showcase.vue:566-574` load-more 无 "已加载 X / 共 Y" 与完成态，无 aria-live。
- `EvaluationView.vue:810-813` 筛选无结果与真空列表未区分（违反文档约定）。
- `EngagementChart.vue:143` 全 0 数据不显示空态。
- `EvaluationRadar.vue:50-64` tooltip  dump 全部维度 rationale（死代码分支 + 未转义 HTML 注入）→ 只显名称+分数并转义。

### I. 响应式布局修复
- `WorkflowStartForm.vue:259` 模式卡片 `grid-cols-3` 全断点 → 窄屏单列。
- `Analytics.vue:867` 5 张指标卡孤儿行 → 第 5 张 `col-span-2 sm:col-span-1`。
- `PreLaunchChecklist.vue:198` `grid-cols-2` 全断点 → `grid-cols-1 sm:grid-cols-2`。
- `XhsAccountsPanel.vue:362-397` 工具行窄屏溢出 → flex-wrap。
- `SystemConfigPanel.vue:117-121` 配置行窄屏溢出。
- 图表卡片 chrome 不统一（TrendChart/EngagementChart/Suspense fallback/AnalyticsSkeleton 四种 padding/圆角）→ 统一。
- `App.vue:160` `h-screen` → `h-dvh` 渐进。

### J. 关键弹窗语义（ConfirmStartModal / Review 发布弹窗）
- `role="dialog"` `aria-modal` `aria-labelledby`、Escape 关闭、打开聚焦、关闭还原焦点（项目既有约定）。

## P1 — 本批选做（时间允许）

- `MobileTabBar.vue:145` 更多菜单 scrim/外部点击关闭 + 焦点管理。
- `WorkflowTabBar.vue:136-226` tab 语义 + 键盘可达 + 溢出菜单 Escape/外部点击。
- 表单 label for/id 关联（WorkflowStartForm、BriefFileUpload）。
- `BriefFileUpload.vue:107` 拖拽区键盘可达；`Review.vue:1347` 图片上传 label 键盘可达。
- `Dashboard.vue` 各状态 CTA 去重（stale/completed/error 多 CTA 稀释）。
- `Dashboard.vue:467` / `WorkflowHeader.vue:143` 高频 aria-live 噪音。
- 骨架屏形状对齐真实内容（DashboardSkeleton、EvaluationSkeleton）。
- `History.vue:357` 50 条硬上限 → offset 分页或 "显示 50/N" 提示。
- `AppIcon.vue:157` 无 ariaLabel 时默认 aria-hidden。
- `Review.vue:183,1203` 详情加载失败静默 → 失败态 + 重试。
- `Home.vue:23,246` checklist readiness 未消费（CTA 门控或提示）。
- `EvaluationView.vue:982` note drawer 缺 focus trap；两个 drawer 缺 Escape 关闭。
- 移动端/平板缺语言切换入口（More 菜单 + 平板底栏）。
- `Navbar.vue:439` 平板连接状态点仅颜色 → role=status + sr-only。
- `EvaluationOverview.vue:246` 110px 迷你 trend 隐藏轴 + 骨架占位。
- `Review.vue:965` 决策后卡片瞬移 → TransitionGroup 退场。
- `VersionCompare/StyleCompare/Review.vue:1177` 键盘焦点不可见 → focus-visible 环。

## P2 — 架构级（本批不做，记录）

- 暗色模式 ~900 行 `!important` 全局重映射收缩为 CSS 变量 + 显式 dark: 兜底。
- z-index 魔法值 → 语义 token。
- `cards.css` 与 `main.css` 重复（.card 复制 .liquid-glass、重复 @tailwind、滚动条覆盖）。
- `index.html` lang 静态不同步 locale；theme 三态循环。
- `StepIndicator.vue` / `ProgressPhase.vue` 死代码删除。
- `Analytics.vue:375-424` 趋势图（≤20 条）与互动图（周期总量）口径不一致加注。
- `History.vue:1038` 移动端进度 % 不可见。
- `HelpView.vue` tablist 语义补全 + selectSection 清 query 问题。
- `WorkflowTimeline.vue` 键盘导航不可达 + 重复 progressbar。

## 验收

- `cd frontend && npm run type-check && npm run test:run && npm run build` 全绿。
- 改动的交互约定同步到 `docs/frontend-ux-optimization.md`。
- 新发现写入 `.trellis/spec/frontend/`（如需要）。
