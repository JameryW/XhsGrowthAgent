# 排查思连康健展示页与回放展示问题

## 背景

- 目标工作流：`xhs_default_b101cc38`
- 展示标签：`思连康健`
- 模式：`brief`
- 当前状态：`awaiting_choice` / `creating`
- 当前 agent：`version_generator`
- API 验证时间：2026-06-12 22:32 Asia/Shanghai

## 复现与观测

1. `/api/workflow/list?limit=100` 能返回目标工作流，列表元数据正常：
   - `label=思连康健`
   - `workflow_mode=brief`
   - `progress_percent=40`

2. `/api/workflow/status/xhs_default_b101cc38` 返回的数据并不缺失：
   - `brief_content` 有品牌、产品、卖点、内容方向等结构化字段。
   - `shooting_plan` 有标题候选、正文、标签、拍摄角度等字段。
   - `optimization_analysis` 有 gaps / suggestions / viral_patterns。
   - `content_versions` 有 A/B/C 版本。
   - `copy_content` 为空对象。
   - `visual_plan` 为空对象。

3. `/api/workflow/history/xhs_default_b101cc38?limit=50` 返回 checkpoint 历史正常：
   - 最新 checkpoint 是 step 9，`current_agent=version_generator`。
   - 最新 checkpoint 带有 `optimization_analysis` 和 `content_versions`。
   - `copy_content` 仍为空对象。

4. Headless Chromium 截图确认：
   - Showcase 页面底部卡片能出现“思连康健”，但详情内容不可读/不完整。
   - Replay 页面能进入目标工作流，但 `version_generator` 标签显示为 `dashboard.timeline.short.versionGen`。
   - 页面中文在当前运行环境中渲染成方块，说明字体栈或运行环境缺 CJK 字体。

## 根因

### 1. Showcase 卡片没有 brief-mode 内容分支

`frontend/src/components/WorkflowCardBody.vue` 主要展示：

- `content_plan`
- `copy_content`
- `trend_data`
- `visual_plan`
- `publish_result`
- `analytics`
- `ripple_*`

但“思连康健”的有效内容集中在：

- `brief_content`
- `shooting_plan`
- `optimization_analysis`
- `content_versions`

所以列表卡片拿到了详情，却没有匹配的展示分支。

### 2. Replay 创作详情被 `copy_content` 空对象误拦截

`frontend/src/components/replay/AgentResultCreative.vue` 中，Draft、Optimization Analysis、Content Versions 都被包在：

```vue
<template v-if="cp.copy_content && Object.keys(cp.copy_content).length > 0">
```

“思连康健”处于 `version_generator` checkpoint，`content_versions` 已存在，但 `copy_content={}`，因此优化分析和版本列表被隐藏。

### 3. `version_generator` 缺少 short i18n key

代码调用：

```ts
t('dashboard.timeline.short.versionGen')
```

但 `frontend/src/locales/zh-CN.json` 和 `frontend/src/locales/en.json` 的 `dashboard.timeline.short` 里没有 `versionGen`，导致回放 rail 和 header 直接显示 key。

### 4. Dashboard 回放仍有部分组件绕过 `effectiveState`

`workflowStore` 已有 replay-aware `effectiveState`，但 Dashboard 子组件仍有多处使用 `workflowStore.workflowState`，例如：

- `frontend/src/components/dashboard/ContentCards.vue`
- `frontend/src/components/dashboard/WorkflowTimeline.vue`
- `frontend/src/components/dashboard/OptimizationPanel.vue`
- `frontend/src/components/dashboard/ShootingPlanPanel.vue`

这会导致 dashboard replay 模式下某些内容仍展示实时状态，而不是选中 checkpoint。

### 5. CJK 字体渲染缺口

全局字体栈是：

```css
font-family: 'Inter', system-ui, -apple-system, sans-serif;
```

当前 Linux/headless 环境没有可用 CJK fallback，截图中中文全成方块。真实用户机器若缺中文字体也会出现同类问题。

## 修复方案

1. 在 `WorkflowCardBody.vue` 增加 brief-mode 展示分支：
   - 优先展示 `brief_content.brand_name/product_name/content_direction/selling_points`。
   - 展示 `shooting_plan.title_candidates/body_copy/required_hashtags/optional_hashtags`。
   - 展示 `content_versions` 的标题、正文摘要、分数和标签。
   - 展示 `optimization_analysis` 摘要。
   - 对 `visual_plan` 使用 meaningful data 判断，避免空对象展示 undefined。

2. 拆开 `AgentResultCreative.vue` 的门禁：
   - `copy_content` 只控制 copy block。
   - `draft_content`、`optimization_analysis`、`content_versions` 分别按自身字段判断。
   - `version_generator` checkpoint 应直接展示 `content_versions`，即使 `copy_content` 为空。

3. 补齐 i18n：
   - `dashboard.timeline.short.versionGen`
   - `dashboard.timeline.short.choiceGate`
   - 如后续需要，也补齐 `publisher` 与已有 key 的命名一致性测试。

4. 统一 replay-aware 数据源：
   - 在 Dashboard 子组件中优先使用 `workflowStore.effectiveState`。
   - `workflowMode/currentAgent/briefContent/shootingPlan/optimizationAnalysis/contentVersions/draftContent` 都从 `effectiveState` 派生。
   - `WorkflowTimeline` 的节点状态也应基于 `effectiveState.current_agent` 与 selected checkpoint。

5. 补强字体栈：
   - CSS / Tailwind fontFamily 增加 CJK fallback：
     `Noto Sans SC`, `Microsoft YaHei`, `PingFang SC`, `Hiragino Sans GB`, `Source Han Sans SC`, `WenQuanYi Micro Hei`。
   - 部署镜像中安装 CJK 字体包，保证截图/服务器侧 headless 验证可读。

## 验收标准

- Showcase 中“思连康健”卡片能展示 Brief 摘要、拍摄方案、版本候选或优化分析摘要。
- `/replay/xhs_default_b101cc38` 的最新 `version_generator` checkpoint 能展示 A/B/C 版本。
- 回放 rail/header 不再出现 `dashboard.timeline.short.versionGen` 原始 key。
- Dashboard replay 模式选中不同 checkpoint 时，内容卡片、时间线和右侧内容一致切换。
- Headless Chromium 截图中中文不再显示为方块。

