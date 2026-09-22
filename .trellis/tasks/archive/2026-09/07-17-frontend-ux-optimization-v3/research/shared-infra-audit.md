# 跨页面共享基础设施审计

审计日期：2026-07-17。范围：样式系统、i18n、通用组件、性能与构建、可访问性与动效、测试约定、类型契约。

## 1. 样式系统

**关键事实**
- 设计 token 主要在 `frontend/tailwind.config.js`：`neon.*` 五色体系（pink/cyan/purple/peach + 辅助色）、`light.*` 背景、`text.*` 文字色（`tailwind.config.js:10-70`）；字号梯度 `display/title/body/caption`、自定义 `boxShadow.neon-*`（约 75-95 行）；`darkMode: 'class'`。
- CSS 变量很少：仅 6 个 `--theme-*`（bg/surface/surface-strong/border/ink/muted），定义在 `frontend/src/styles/main.css:997-1004`（light）和 `:1006-1014`（`html.dark`）。
- 暗黑模式实现：`stores/theme.ts:70-80` 切换 `html.dark` class + `data-theme` + `color-scheme` + meta theme-color，支持 light/dark/system 三态并持久化到 `localStorage('xhs-theme-mode')`；`html.theme-switching` 双 rAF 过渡抑制（`main.css:1018-1023`）。
- `main.css`（2014 行）承载大量"liquid glass"组件类（`.glass`、`.liquid-glass*`、`page-header-shell`、`liquid-mesh-bg`）；暗黑适配靠 `html.dark :is(...)` 对 Tailwind 浅色工具类做覆盖层（`main.css:1098-1230+`），属兼容层而非 token 驱动。
- `cards.css`（429 行）、`animations.css`（150 行）为补充层。
- 断点：Tailwind 默认断点 + `useBreakpoints.ts:3-4` 硬编码 `(max-width: 767px)` / `768-1023px`，与 md(768)/lg(1024) 对齐但未共享常量。
- z-index 无 token 体系：散用 `z-10`(11 处）、`z-40`(4)、`z-50`(17)、`z-[80]`、`z-[100]`。

**缺口**
- P1: z-index 无分层约定（modal/overlay/nav 混用 z-50 与 z-[100] 魔法值）。
- P1: 暗黑适配靠覆盖 Tailwind 浅色类（`html.dark :is(.text-slate-900...)`），新组件若直接用浅色类会被隐式改写，行为不可预测；`--theme-*` 变量与 Tailwind `neon.*` 两套并存，无单一来源。
- P2: 无 spacing/radius/duration token，时长魔法值散落（PageTransition 200ms、main.css 0.3s 等）。

## 2. i18n

**关键事实**
- 结构：`locales/en.json` + `zh-CN.json` 各 2112 行、扁平 key 均为 1778 条，**双向零缺失**（脚本验证）。顶级 section 45 个，按页面/组件划分（`showcase` 129 条、`replay` 167、`dashboard` 256、`analytics` 58、`evaluation` 45）。
- 命名约定：`{section}.{camelCaseKey}`，插值用 `{count}` 等（如 `dataTable.records: '共 {count} 条记录'`）。
- 加载策略：`locales/index.ts:6-15` 默认 zh-CN 静态入 entry，en 懒加载（`loadLocaleMessages`，`stores/language.ts:12` 调用）；legacy: false（Composition API）。
- 五页硬编码中文抽查：**Showcase/Dashboard/Analytics/WorkflowReplay 零 Han 字符**（t() 调用 41/35/61/30 次）；EvaluationView 的 35 处 Han 全部为注释；`WorkflowReplay.vue:94` 有一处 `/not found|不存在/` 的正则兜底（匹配后端错误信息，非 UI 文案）。

**缺口**
- P2: 无 key 缺失/硬编码扫描的 CI 防护（目前靠人工，但现状干净）。

## 3. 通用组件 API 与使用约定

| 组件 | API（证据） | 使用点 |
|---|---|---|
| PageHeader | `title/description/eyebrow/icon/tone(5色)/titleId`，`aria-labelledby` 关联（`PageHeader.vue:7-21,61,71`） | Analytics:223、EvaluationView:276/414、Review:657、History:137、Settings:47、HelpView:50 |
| SkeletonLoader | `type: text/card/avatar/list` + lines/width/size（`SkeletonLoader.vue:4-14`）；页面级骨架在 `skeletons/`（`index.ts` 导出 8 个 + 2 wrapper） | Dashboard:207、Analytics:272、Review:674；**Showcase/WorkflowReplay/EvaluationView 未用** |
| ErrorState | 5 类错误的 i18n 建议映射（`ErrorState.vue:36-40`），绑定 workflowStore | **仅 Dashboard 使用** |
| ErrorCard | `type: api/timeout/unknown/retry_success` + retry/dismiss 事件（`ErrorCard.vue:35-45`） | **仅 Dashboard 使用** |
| MetricCard | `icon/title/value/subtitle/variant(4色)`（`MetricCard.vue:7-16`） | **仅 Analytics 使用** |
| DataTable | `columns[{key,label,align,sortable,cellClass}]/data/rowKey/highlight*`，客户端排序，无分页/虚拟滚动（`DataTable.vue:9-64`） | **仅 Analytics 使用** |
| PageTransition | 内置 `<RouterView>` + fade-slide，仅 `duration` prop，out-in 模式（`PageTransition.vue:9-33`）；路由 meta.transition 未被读取 | App.vue:213 |
| Toast | 经 `stores/toast.ts`，4 类型映射 icon/variant（`Toast.vue:13-34`） | Dashboard:121/147/153、HelpView:35-43 等 |
| TooltipHelper | `text + position(4向)` 自计算坐标（`TooltipHelper.vue:4-9`） | **零使用点（死代码）** |
| AppIcon | 静态注册 ~90 个 lucide 图标的白名单 map，`name/size(5档)/variant(5色)/ariaLabel`，未知名 fallback HelpCircle（`AppIcon.vue:99-146`） | Analytics 多处、WorkflowReplay:410 等 |
| NeonButton | `variant(5)/size(xs-lg)/title`，emit click（`NeonButton.vue:9-29`） | Dashboard、Login、NotFound、WorkflowStartForm 等 10+ 处 |
| RipplePanel | `variant: planning/analyzing`（`RipplePanel.vue:17-34`） | dashboard 子组件 |

**缺口**
- P0: **错误态无统一组件**——ErrorState/ErrorCard 仅 Dashboard 使用；Showcase:354、WorkflowReplay:420/436/444、EvaluationView:350/433 各自手写 `border-rose-200 bg-rose-50` 错误卡（EvaluationView 还有局部 `.error-card` class，`EvaluationView.vue:604`），五页三套实现。
- P1: 骨架屏不统一——EvaluationView 用内联加载、Showcase/Replay 用自定义 loading，未复用 skeletons/ 体系。
- P1: TooltipHelper 组件存在但零引用；Dashboard/Showcase 无 PageHeader（Replay 用裸 `<header>`，`WorkflowReplay.vue:422`），页面头部模式不一致。
- P2: DataTable 无分页/空态 slot 规范，仅一个消费方，约定未经过多页面验证。

## 4. 性能与构建

**关键事实**
- `vite.config.ts:31-47`：`manualChunks` 拆 `vue-vendor`/`axios`；`chunkSizeWarningLimit: 500`（唯一预算）；`reportCompressedSize: false`（注释注明为防低内存 OOM）；`sourcemap: false`。
- 路由全部 `() => import()` 懒加载（`router/index.ts:8-91`），showcase/replay 为 public 且跳过 auth 初始化（`:102`）。
- App.vue 用 `defineAsyncComponent` 把 Navbar/ConnectionStatus/OfflineRecovery/KeyboardShortcutsHelp 从 entry 剥离（`App.vue:11-14`）。
- echarts 按需引入 `echarts/core` + 具体 chart（`charts/EngagementChart.vue:5-8`、`TrendChart.vue:5-8`、`EvaluationRadar.vue:5-8`），未整包导入。
- 静态资源：`public/` 仅 favicon.svg；`<img>` 标签全项目零使用（仅 prop 名误命中），无 `loading="lazy"`；Showcase 案例内容走 API JSON。

**缺口**
- P1: 无 bundle 分析器（无 rollup-plugin-visualizer）与正式性能预算；500KB warning 是唯一护栏。
- P2: echarts 未进 manualChunks，可能被打进 Analytics/Evaluation 路由 chunk（两页面各自重复依赖无法去重验证）。

## 5. 可访问性与动效

**关键事实**
- `prefers-reduced-motion`：全局降级在 `main.css:968-989`（关动画、transition 压至 0.01ms、禁 hover transform）；组件级自查 6 处：PageTransition:68、Navbar:481、MobileTabBar:216、CheckpointRail:170、Showcase:411、WorkflowReplay:480。**无 JS 层 matchMedia 工具**（useAnimation 的 rAF 计数器不查 reduced-motion）。
- 焦点管理：无通用 focus-trap 工具/依赖；各 modal 自实现——ConfirmModal:83-85（Escape+Tab 循环）、CelebrationModal:66-68、KeyboardShortcuts:61-72（打开聚焦、关闭恢复焦点）；`main` 有 `tabindex="-1"`（App.vue:208）但无 skip-link。
- UX 工具：`utils/interactionTelemetry.ts` 为公开页（showcase/replay）专用埋点，事件名白名单 + key 白名单 + 隐私注释；`utils/cn.ts`（clsx+tailwind-merge）；`useBreakpoints`、`useAnimation`（rAF 计数器，代际 token 防竞态）、`useRetry`、`useShortcuts`、`useLoading`。
- 数字格式化无共享 util：各页自调 `toLocaleString()`（Analytics:40-41、Review:501、History:79、EvaluationView:153，locale 传参方式不一致）。
- a11y 测试依赖已装：`@axe-core/playwright`（package.json:32）。

**缺口**
- P1: 无 reduced-motion 的 JS/composable 层（AnimatedCounter/useAnimation 在减弱动效偏好下仍跑 rAF）。
- P1: 无共享 focus-trap/skip-link；焦点恢复逻辑散落各 modal。
- P2: 数字/日期格式化无统一 util；埋点仅覆盖 showcase/replay，Dashboard/Analytics/Evaluation 无追踪。

## 6. 测试约定

**关键事实**
- 结构：`frontend/tests/{components,composables,stores,integration,api}` + `setup.ts`（全局注册 i18n 插件，`setup.ts:1-7`）；vitest + happy-dom + `@vue/test-utils`（vite.config.ts:16-25，include `tests/**/*.spec.ts`）。
- scripts：`test`(watch) / `test:run` / `test:coverage`(v8) / `type-check`（package.json/package.json:6-12）。
- 五页覆盖：仅 `Showcase.spec.ts`、`WorkflowReplay.spec.ts`（组件级）+ integration `theme1-loading/theme2-error/theme3-animation/theme4-help-onboarding`；**Dashboard/Analytics/EvaluationView 无视图级测试**（仅 dashboardHero、workflow store 间接覆盖）。
- CI：`.github/workflows/ci.yml` 存在（未深入）。

**缺口**
- P1: Analytics/EvaluationView/Dashboard 三页无 spec，恰好是 DataTable/MetricCard/ErrorCard 的唯一消费方——共享组件改动无回归网。
- P2: axe-core 已装但 tests 内未见 a11y spec 引用。

## 7. 类型契约

**关键事实**（`frontend/src/types/`）
- `publicShowcase.ts`：showcase/replay 全套公开契约——`PublicCase`、`PublicReplayStep`、`PublicReplayManifestResponse`、`PublicMetrics`、`PublicVisualResult` 等（:1-96）。
- `analytics.ts`：`GrowthReport`/`PostPerformance`/`PerformanceData`/`CostData`（:2-39）。
- `evaluation.ts`：`EvaluationResult`/`EvaluationListItem`/`TrendPoint`/列表与趋势 Response（:4-78）。
- `workflow.ts`：`WorkflowPhase`/`WorkflowStatus` 联合类型、`CheckpointSnapshot`、`WorkflowListItem` 等。
- `review.ts`：`ReviewDecision`/`PendingReview` 等。
- 生成链路：`scripts/generate_types.sh` + `api/spec/` 存在（类型部分手写部分生成，未逐一核对）。

**缺口**
- P2: Analytics.vue 中 DataTable 行用 `Record<string, any>`（`DataTable.vue:15,20`），PostPerformance→表格行的映射无类型约束（`Analytics.vue:137` 手动拼 `views_display`）。

## 优先级汇总

- **P0**: 错误态组件未跨页复用（5 页 3 套手写实现，ErrorState/ErrorCard 仅 Dashboard 用）。
- **P1**: ① z-index 无分层；② 暗黑模式靠 Tailwind 类覆盖层、token 双轨；③ 骨架屏/页头模式不统一；④ TooltipHelper 死代码；⑤ 无 bundle 分析与正式预算；⑥ reduced-motion 无 JS 层；⑦ 无 focus-trap/skip-link；⑧ Analytics/Evaluation/Dashboard 无视图测试。
- **P2**: 无 i18n CI 扫描；无格式化 util；埋点仅公开页；DataTable 行类型 `any`；路由 meta.transition 定义了但 PageTransition 未消费。
