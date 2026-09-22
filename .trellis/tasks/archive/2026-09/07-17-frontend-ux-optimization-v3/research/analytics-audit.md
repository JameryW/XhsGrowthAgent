# 数据分析页（/analytics）UX 现状审计

审计日期：2026-07-17。审计对象：`frontend/src/views/Analytics.vue` 及其引用组件、store、API。当前分支有 3 个未提交文件改动（DataTable.vue / EngagementChart.vue / Analytics.vue，已在文中标注）。此页面此前未做过系统 UX 审计。

## 1. 页面结构

**组件树**（路由 `/analytics`，`requiresAuth`，`frontend/src/router/index.ts:45-48`；移动端从"更多"菜单进入，`MobileTabBar.vue:23,131`）：

```
Analytics.vue (538 行)
├─ PageHeader（meta: 账号/周期/最后更新时间；actions: 刷新 + 周期切换）
├─ AnalyticsSkeleton（首载骨架）
├─ 错误态卡片 + CreatorStatsPanel(compact)
├─ 空态卡片 + CreatorStatsPanel(compact)
└─ 数据态（Analytics.vue:341-536）
   ├─ CreatorStatsPanel（创作者中心导入，自带 7d/30d 周期选择器）
   ├─ 5 × MetricCard（发帖数/总浏览/总互动/平均互动率/AI 费用）
   ├─ TrendChart（异步 + Suspense，ECharts 折线，"互动趋势"）
   ├─ EngagementChart（异步 + Suspense，ECharts 柱状，"互动构成"）
   ├─ 成本卡片（3 数字 + 预算进度条 + 按模型条形，纯 DOM 非图表库）
   ├─ 增长洞察卡片（insights 列表 + 热门话题按钮 → /start）
   └─ DataTable（TOP 10 笔记表，可排序，最佳笔记行高亮）
```

**数据流**：

- Store：`frontend/src/stores/analytics.ts`。`fetchAllData()` 单次请求 `GET /analytics/dashboard/{accountId}?period&limit=20`（`api/analytics.ts:28-34`，store:78-93），一次拿回 report/performance/costs 三份。
- 账号：`accountId = accountsStore.activeAccountId ?? 'default'`（store:23），跟随全局活跃账号，无页面级账号切换器。
- 周期：`period: 'daily'|'weekly'|'monthly'`，默认 weekly；`setPeriod` 直接重取（store:128-131）。后端语义 daily=24h、weekly=7d、monthly=30d（`backend/api/routes/analytics.py:97-105`）。
- 实时：WS 三类事件（报告更新/成本告警/新笔记）直接改 state 并弹 toast（store:48-75）。
- 首载：`onMounted` 先 `fetchAccounts()` 再按需 `refreshData()`（Analytics.vue:23-30）。

**图表渲染**：echarts ^5.5.0 + vue-echarts ^6.6.8（package.json:23,27），按需注册模块 + CanvasRenderer，`autoresize`，固定高 220px。注意：`trendData` 并非时间序列——它把 ≤20 篇帖子按**星期几分桶求平均互动**（Analytics.vue:46-78）；`engagementData` 是赞/评/藏/转四项总计（80-100）。

## 2. 已具备能力（含证据）

- 账号/周期/最后更新时间上下文显示在页头（Analytics.vue:230-238）——符合交互文档"增长页显示当前账号与周期"
- 三态区分：加载骨架 / 加载失败（含重试）/ 无数据（含引导）互不混淆（Analytics.vue:32-34, 272-338）——符合文档"空状态区分没有数据和加载失败"
- 空态双路径引导：开始创作 + 创作者中心导入提示（Analytics.vue:316-337）
- 错误态下仍保留 CreatorStatsPanel 导入入口（Analytics.vue:296-302）
- 周期切换按钮组带 `aria-pressed`、`aria-label`，触控高 min-h-11（Analytics.vue:252-268）
- 图表代码分割 + Suspense 骨架 fallback（Analytics.vue:14-15, 367-392）
- 图表无障碍：`role="figure"` + 自动生成的趋势摘要 aria-label + sr-only 数据表（TrendChart.vue:41-49,128-159；EngagementChart.vue:48-53,121-156）
- 表格列排序（DataTable.vue:59-66）、最佳笔记行高亮（Analytics.vue:532-533）
- 互动率色彩分级（≥5% 绿 / 1-5% 黄 / <1% 灰）——本分支新增，`DataTable.vue:15` cellClass 钩子 + Analytics.vue:118-131
- 预算进度条三色预警 >70%/>90%（Analytics.vue:424-436）
- 热门话题一键带参跳转 `/start` 发起创作（Analytics.vue:500-512, 214-218）
- WS 实时推送新笔记/成本告警（stores/analytics.ts:48-75）
- i18n 双语齐全：analytics 31 键、charts 11 键（en.json / zh-CN.json 均验证存在）
- 图表自适应容器 resize（两图均 `autoresize`）

## 3. UX 问题与优化机会

### P0 — 误导性/功能性缺陷

1. **"互动趋势"不是趋势，且零值误导**。按周一~周日分桶平均（Analytics.vue:62-77），无帖子的星期画 0，被误读为"当天互动为 0"；≤20 篇样本下多数桶为 0；x 轴无日期，切周期后图表语义不变，无法回答"最近表现在变好还是变差"。应改为按日发布量/互动量时间序列，无数据天空缺而非画 0。
2. **暗黑模式下图表不可读**。tooltip 硬编码白底 `#FFFFFF` + 深字 `#1E293B`（TrendChart.vue:88-91；EngagementChart.vue:87-94）；轴标签固定 `#64748B`（TrendChart.vue:69,82）；分割线 `rgba(0,0,0,0.05)` 在暗底近不可见（TrendChart.vue:79）。容器有 `dark:` class 但 canvas 内部配色不随主题——图表组件完全未接 `useThemeStore`（stores/theme.ts:34 有 `isDark`，grep 证实 charts/ 零引用）。
3. **排序排的是格式化字符串，结果错误**。`views_display`（"1,234"）和 `engagement_rate_display`（"10.0%"）列标了 sortable（Analytics.vue:114-131），DataTable 数值分支取不到原始数字，退化为字典序——"9.0%" > "10.0%"、"999" > "1,234"（DataTable.vue:51-56）。应对原始 `views`/`engagement_rate` 字段排序。
4. **周期按钮标签与后端语义错位**。UI 把 daily→"本周"、weekly→"本月"、monthly→"全年"（Analytics.vue:261,265），但后端 daily=24h、monthly=30 天（analytics.py:97-105）——"全年"名不副实。指标卡 subtitle 还写死"本周"（Analytics.vue:39-42），monthly 周期下仍显示"本周"。

### P1 — 核心问题回答能力不足

5. **首屏无涨粉指标**。5 张指标卡无粉丝数/涨粉；`fans` 只出现在 CreatorStatsPanel 内部（CreatorStatsPanel.vue:544-545；类型在 api/analytics.ts:87）。用户核心问题"涨没涨粉"首屏无答案。
6. **无任何对比**。指标卡只有绝对值，无环比/同比 delta；切周期直接覆盖数据（store:128-131），无法对比两周期。
7. **无数据下钻**。表格行不可点击（DataTable 无行 click emit，仅列头排序 @click，DataTable.vue:85）；而单篇详情 API 与组件都已存在——`getCreatorNote`/`getCreatorNoteQuality`（api/analytics.ts:274-293）、`CreatorNoteQualityPanel.vue` 目前只被 evaluation/CreatorQualityWorkspace.vue 使用——Analytics 未接线。
8. **有缓存时刷新失败被静默**。`hasError` 要求 `!posts.length`（Analytics.vue:33），已有数据时 fetch 失败只写 `error.value`（store:89），界面无任何提示，用户看到旧数据以为刷新成功。
9. **结论不靠前**。页面顺序：指标 → 图表 → 成本 → 增长洞察 → 表格（Analytics.vue:341-535），"增长洞察"这一结论区排在成本之后；且 AI 成本（运维指标）占首屏 1/5 指标位（Analytics.vue:43）。
10. **同页两套互不联动的周期**。页面级 daily/weekly/monthly 与 CreatorStatsPanel 自带 7d/30d 选择器（CreatorStatsPanel.vue:46,437-441）并存，语义不同步。
11. **最佳笔记高亮无解释**。整行淡红无图例、无"最佳"徽标（Analytics.vue:532-533；DataTable.vue:112），用户不知高亮含义。
12. **表格只露出一半数据**。`slice(0, 10)`（Analytics.vue:135）+ 无分页/"查看全部"，但 API limit=20（store:83），后 10 篇不可达。

### P2 — 打磨项

13. EngagementChart 无障碍描述硬编码英文 `Total: ..., top: ...`（EngagementChart.vue:52），i18n 漏网。
14. 图表 data 为空时 ECharts 渲染空坐标轴，无可视化"暂无数据"占位（仅 aria 层有，TrendChart.vue:42）。
15. 无导出/分享：未注册 ECharts toolbox，无 CSV/图片导出。
16. `AnimatedCounter` 存在但未用于此页（仅 ProgressPhase.vue 引用），指标数字静态；MetricCard 的 `aria-live="polite"`（MetricCard.vue:63）会让每次刷新朗读全部数字。
17. TrendChart 注册了 LegendComponent 却未配置 legend（TrendChart.vue:7,11），无效代码；折线 `symbol:'none'` 无数据点，移动端难以精确读值；无 dataZoom。
18. 切周期无局部加载反馈：有数据时只有刷新按钮转圈（Analytics.vue:245-249），图表/表格区域无 busy 态。
19. `lastUpdatedAt` 仅 `refreshData()` 设置（Analytics.vue:163-166），WS 推送更新数据后不刷新该时间戳。
20. 表格列头排序按钮未暴露排序状态（无 `aria-sort`/`aria-pressed`，DataTable.vue:83-93）；`role="table"` 用在 div grid 上，语义弱于原生 table。
21. 重新进页不自动重试：onMounted 条件含 `!error`（Analytics.vue:27），上次失败后回退再进页面停在错误态；有缓存时无"数据可能过期"提示。
22. 分享数（shares）进了构成图但表格无该列（Analytics.vue:112-133），数据可得性不一致。

## 4. 技术约束

- **图表栈**：echarts ^5.5.0 + vue-echarts ^6.6.8，按需 `use([...])` 注册，CanvasRenderer；经 `defineAsyncComponent` + `Suspense` 懒加载；`charts/index.ts` 仅导出 TrendChart/EngagementChart（EvaluationRadar.vue 存在但不在 charts 出口）。改图表需保持按需注册以控制包体。
- **样式**：Tailwind（dark 模式靠 `document.documentElement` 的 `.dark` class，stores/theme.ts:76）+ 自定义 `liquid-glass*`/`card` 类。图表色板为组件内硬编码 hex（TrendChart.vue:34-38；EngagementChart.vue:34-43，含本分支新增 CATEGORY_COLORS），无设计 token 层——做暗色适配需先建图表主题机制。
- **i18n**：`frontend/src/locales/{en,zh-CN}.json`；analytics/charts/dataTable/metricCard 键双语齐全；新增文案须双语言（文档 §可访问性）。
- **类型**：`frontend/src/types/analytics.ts`（GrowthReport/PerformanceData/CostData/PostPerformance）；creator-stats 丰富类型在 api/analytics.ts:38-220。
- **测试现状**：无 Analytics.vue、analytics store、TrendChart/EngagementChart/DataTable/MetricCard 的单测；仅 `frontend/tests/integration/theme1-loading.spec.ts:8,46` 断言 AnalyticsSkeleton 结构（改布局会挂）；CreatorStatsPanel/CreatorNoteQualityPanel 有组件测试。验证命令：`cd frontend && npm run type-check && npm run test:run && npm run build`。
- **本分支在途改动**（未提交）：DataTable 增加 `cellClass` 钩子、EngagementChart 多彩柱 + 标题栏总计、Analytics 互动率配色（`git diff` 可见，注释标记 "ponytail"）。
- **交互文档红线**（docs/frontend-ux-optimization.md）：增长入口留在移动端"更多"；页面须显示账号与周期上下文；空态区分无数据/失败并提供下一步；触控 ≥44px；新动效须 `prefers-reduced-motion` 降级（当前图表/CSS 过渡均未做降级，grep 无匹配）。
- **后端契约**：`GET /analytics/dashboard/{accountId}?period&limit`（backend/api/routes/analytics.py）；无对比周期、无时间序列端点——做真趋势图/环比需后端配合或前端按 `published_at` 自行分桶（现有帖子数据含 `published_at`，可前端实现）。
