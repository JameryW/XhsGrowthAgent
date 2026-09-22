# 质量评估页（/evaluation）UX 现状审计

审计日期：2026-07-17。审计范围：`frontend/src/views/EvaluationView.vue`、`components/evaluation/`、`charts/EvaluationRadar.vue`、`charts/TrendChart.vue`、`StyleCompare.vue`、`VersionCompare.vue`、`api/evaluation.ts`、`types/evaluation.ts`、关联 i18n/测试/后端契约。此页面此前未做过系统 UX 审计。

## 1. 页面结构与数据流

### 路由与组件树

- `frontend/src/router/index.ts:51-60`：`/evaluation` 与 `/evaluation/:threadId` 共用 `EvaluationView.vue`（`requiresAuth`）。
- 组件树：
  - `EvaluationView.vue`
    - `PageHeader` + tab 切换（creator / workflow，`route.query.tab` 驱动，默认 creator）— `EvaluationView.vue:25-36, 284-309`
    - tab=creator → `CreatorQualityWorkspace.vue`
      - `settings/CreatorQualityPanel.vue`（账号级历史质量报告，走 `api/analytics.getCreatorQuality`）
      - `settings/CreatorNoteQualityPanel.vue`（单篇笔记质量 + 手动 RQGM 评估，复用 `EvaluationRadar`）
    - tab=workflow（列表态）→ 趋势卡（`TrendChart`）+ 搜索框 + 工作流评估列表
    - `/evaluation/:threadId`（详情态）→ 总分卡 + `EvaluationRadar` + 偏倚告警 + 维度明细 + 修订建议

### 数据来源与深链

- 列表：`GET /evaluation/list`（`api/evaluation.ts:11-23`），20 条/页手动"加载更多"（`EvaluationView.vue:76-81`）。
- 详情：`GET /evaluation/result/{threadId}`（`api/evaluation.ts:26-28`）；`watch(detailThreadId, immediate)` 触发加载（`EvaluationView.vue:221-227`），深链直接可用。
- 趋势：`GET /evaluation/trend?limit=100`（`api/evaluation.ts:39-47`）。
- 手动单篇评估：`POST /evaluation/note`（`api/evaluation.ts:31-36`，LLM 调用，thread-less）。
- 无 Pinia store 参与评估数据（`stores/` 下无 evaluation 相关文件），仅 `accountsStore` 用于 creator tab 账号选择。后端 `/evaluation/*` 由 omp 服务提供（`backend/omp/extensions/xhsagent-ext/src/tools/evaluation_result.ts:45`、`evaluation_trend.ts:37` 引用）。

### 评估数据契约（前后端）

- `types/evaluation.ts`：`EvaluationResult { overall_score(0-100 加权), dimensions[], decision(approved/needs_revision/rejected), revision_hints[], bias_warning, summary }`；`DimensionScore { dimension, score, bias_severity?, rationale, issues[], is_blocking }`。
- 维度全集 10 个（`types/evaluation.ts:5` 注释）：9 个加权维 + `bias_check`（惩罚项，不参与加权，`bias_severity` 与 `score` 语义相反）。
- 权重与阈值在后端可配：`backend/db/evaluator_config.py:34-45`（copywriting 0.18、visual 0.13、compliance 0.14、reach 0.13、audience 0.13、altruism 0.09、ai_taste 0.08、image_quality 0.07、commercial_tone 0.05）、`:64-67`（pass 70 / reject 50 / bias 罚分阈值 60、罚 5 分）。旧部署可能只有 8 维（无 altruism，`:52-63`）。
- `StyleCompare.vue` / `VersionCompare.vue` **不属于评估页**：仅被 `dashboard/OptimizationPanel.vue:142-150` 在 choice_gate 使用（风格/版本选择），与 `/evaluation` 无数据通路。

## 2. 已具备能力

- 列表/详情双视图 + threadId 深链 + 返回列表 — `EvaluationView.vue:23-24, 95-101`
- 评估历史趋势图 + 各维度均值 chip（按分数着色）— `EvaluationView.vue:315-336`
- 前端搜索（标题/thread_id/account_id）+ 结果计数 — `EvaluationView.vue:84-93, 339-347`
- 分页"加载更多"/"已全部加载" — `EvaluationView.vue:401-408`
- 列表三态：加载中 / 错误（role=alert + 重试）/ 空 — `EvaluationView.vue:350-368`
- 详情三态 + 无评估结果的空态说明（含触发方式说明）— `EvaluationView.vue:430-444`
- 9(10）维雷达图（ECharts，autoresize）— `EvaluationRadar.vue:78-86`
- 每维度 rationale + issues 列表 + "硬性失败"标记 — `EvaluationView.vue:478-495`
- 修订建议区、对抗偏倚告警卡 — `EvaluationView.vue:467-473, 499-504`
- decision 徽章三态配色（列表 + 详情一致）— `EvaluationView.vue:127-141, 629-632`
- tab 用 `role=tablist/tab` + `aria-selected`，列表项为 `<button>` 带 aria-label — `EvaluationView.vue:285-308, 372-378`
- 移动端：tabs 全宽均分（`EvaluationView.vue:545-548`）、入口收纳在"更多"菜单（`MobileTabBar.vue:23,139`）、`min-h-11` 触控目标
- 与审核页联动：Review 卡片内嵌评估结果，保存文案后自动重评估 — `Review.vue:85-86, 258-308, 348-366, 917-979`
- Creator tab：账号切换默认跟随 active account、无账号引导去设置、单篇手动 RQGM 评估（含雷达/维度/建议）— `CreatorQualityWorkspace.vue:21-47, 131-152`；`CreatorNoteQualityPanel.vue:71-88, 459-531`
- `TrendChart` 有无障碍描述 + sr-only 数据表 — `TrendChart.vue:41-49, 144-159`
- zh-CN/en 双语 key 基本齐全 — `zh-CN.json:2051-2111`、`en.json:2051+`

## 3. UX 问题与优化机会

### P0

1. **详情页完全缺失评估上下文**。PageHeader 只有通用"评估详情"，不显示笔记标题、账号、threadId、评估时间；用户深链进来无法确认"这是哪篇的评估"。违反 `docs/frontend-ux-optimization.md:12`（"页面显示…评估上下文"）。证据：`EvaluationView.vue:413-427`（标题硬编码 `evaluation.list.detailTitle`）；列表项有标题但 `openDetail` 不带任何上下文（`:95-97`）。
2. **趋势"加载失败"与"没有数据"不区分**。`loadTrend` 出错时静默置 `db_ready:false`，UI 一律渲染"暂无历史评估数据"。违反 `docs/frontend-ux-optimization.md:31`（空状态需区分无数据/加载失败并给出下一步）。证据：`EvaluationView.vue:182-191`（catch 吞错）、`:335`。
3. **评估结果没有行动出口**。decision 为 needs_revision/rejected 时，`revision_hints` 只是纯文本列表，没有"去审核页改稿"（`/review/:threadId` 才是改稿+自动重评估的入口，`Review.vue:348-366`）或"重新生成"按钮。评估页到工作流的联动是断的。证据：`EvaluationView.vue:499-504`；全文件无 `/review` 引用。

### P1

4. **分数档位阈值前端硬编码 70/50，与后端可配阈值脱节**。后端 `threshold.pass/reject` 可按账号覆盖（`evaluator_config.py:64-65, 90-93`），前端 `scoreTier` 写死（`EvaluationView.vue:143-147`，维度行内联判断 `:486`）；后端调阈值后颜色/徽章会误导。
5. **"无分"渲染成"0 分"**。列表 `overall_score ?? 0` 会显示红色 `0.0`（`EvaluationView.vue:391-393`）；详情 `overall_score ?? 0` 同理（`:230, 452`）。缺失数据被可视化为"最差分数"。
6. **bias_check 维度在雷达图与其他维度同向同尺度展示**，但其 `bias_severity`（越高越糟）与 `score` 语义相反（`types/evaluation.ts:9-13`），且 `bias_severity` 前端从未使用（全 src 仅类型定义一处）。雷达形状对偏倚维度有误导风险。证据：`EvaluationRadar.vue:38-45`（indicators 无差别映射全部 dimensions）。
7. **"9 维评分雷达"标题与事实不符**：维度数由后端数组决定，旧数据可能 8 维（无 altruism，`evaluator_config.py:47-63`）；en 的 review 雷达标题还是 "6-Dimension Radar"（`en.json:691`）vs zh "9 维"（`zh-CN.json:691`）。证据：`zh-CN.json:2070`、`EvaluationRadar.vue`（标题由父级传入固定 key）。
8. **维度含义与权重不可解释**。维度只有名称翻译（文案/视觉/合规…），无 tooltip 解释每维评什么；overall 是加权平均但 UI 不展示权重（copywriting 0.18 vs commercial_tone 0.05 影响悬殊），用户无法理解"为什么得这个分"。证据：`EvaluationView.vue:247-262, 478-495`（仅 rationale 文本，无维度说明/权重）。
9. **历史浏览能力弱**：搜索只在已加载页内前端过滤（`EvaluationView.vue:84-93`），服务端不查；无 decision/分数段/时间筛选；趋势图 100 个点不可点击跳详情；无账号过滤（API 支持 `account_id` 参数但 UI 未传，`api/evaluation.ts:21`、`EvaluationView.vue:57-62`）。
10. **Review 页维度映射缺 `altruism`**，该维度在审核页会回退显示原始 key，与评估页不一致。证据：`Review.vue:332-342` vs `EvaluationView.vue:247-258`。
11. **加载态为纯文本**，无骨架屏（项目已有 `SkeletonLoader` 组件且 Review 用了 `ReviewSkeleton`）。证据：`EvaluationView.vue:357-359, 430`。

### P2

12. 搜索无匹配与"真无数据"共用空态文案"暂无有评估结果的工作流"（`EvaluationView.vue:361-368`），搜索场景文案错误。
13. 雷达图维度顺序跟随后端数组顺序，顺序变化会导致形状跳动；tooltip 只有数值，没有每维 rationale 入口（`EvaluationRadar.vue:38-48`）。
14. 趋势 x 轴日期用 `slice(5,16)` 手切 ISO 字符串，未本地化、跨年无年份（`EvaluationView.vue:175`）。
15. `DIMENSION_LABEL_KEYS` 在 4 个文件重复维护（`EvaluationView.vue:247`、`EvaluationRadar.vue:25`、`CreatorNoteQualityPanel.vue:239`、`Review.vue:332`），已出现 #10 的漂移。
16. 遗留未使用的旧 i18n key（旧"输入 threadId 查询" UI 已删）：`zh-CN.json:2053(subtitle), 2065-2068(inputPlaceholder/search/searching/initialHint)`。
17. 列表项标题单行截断、移动端无法读全；aria-label 不含分数（`EvaluationView.vue:377, 579-582`）。
18. 详情页 320px 雷达图在 <768px 单列布局中偏高；`result-grid` 仅一档断点（`EvaluationView.vue:617-618, 653-654`）。
19. **dark mode 不一致**：`EvaluationView.vue` scoped 样式全部硬编码 hex 无 dark 变体，而同页的 `CreatorQualityWorkspace/Panels` 使用 `dark:` 类——暗色主题下两个 tab 观感割裂（`EvaluationView.vue:510-663` vs `CreatorQualityWorkspace.vue:57`）。
20. `VersionCompare.vue:237` 用 `analytics.avgEngagementRate`（平均互动率）作为 predicted_score 的进度条 label——分数被误标（属 choice_gate，但同属"分数误导"类问题，可顺带修）。
21. `CreatorNoteQualityPanel` 手动 RQGM 评估是 LLM 调用，运行期间仅按钮 loading，无预计耗时/成本提示；评估结果切换笔记即丢弃，不持久（`CreatorNoteQualityPanel.vue:71-88, 169-172`）。

## 4. 技术约束

- **样式**：双体系并存——`EvaluationView.vue` 为 scoped CSS + 硬编码 hex（主色 `#F43F5E` rose、`#16a34a/#d97706/#dc2626` 三档分色，`EvaluationView.vue:626-628`）；`CreatorQuality*` 组件为 Tailwind utility + `dark:` 变体。设计 token 在 `frontend/tailwind.config.js` 与 `src/styles/main.css`（全局字体/背景，`main.css:6-46`）。触控目标惯例 `min-h-11`。新代码应优先 Tailwind + dark 变体，与同页 creator tab 保持一致。
- **i18n**：`frontend/src/locales/{zh-CN,en}.json`。评估页 key：`evaluation.*`（`:2051-2111`）、`creatorQuality.*`、`creatorNoteQuality.*`、`review.evaluation.*`（`:684-702`）。维度 label key 集合以 `types/evaluation.ts:5` 的 10 维为准，新增维度需同步 4 处映射表（见问题 15）。修改文案必须双语同步（已有"6-Dimension"/"9 维"漂移先例）。
- **API/类型**：`frontend/src/api/evaluation.ts`（4 个端点）、`frontend/src/types/evaluation.ts`；`updateCopy` 响应内嵌 `evaluation_result`（`frontend/src/types/review.ts:26`）。后端契约源头：`backend/db/evaluator_config.py`（权重/阈值）、`backend/agents/evaluator.py`；`scripts/evolve_evaluator_prompt.py`、`train_evaluator_weights.py` 会改维度权重——前端不应假设维度集合和阈值固定。
- **测试**：**无 EvaluationView 专用 spec**。邻近覆盖：`frontend/tests/components/CreatorQualityWorkspace.spec.ts`（账号默认选中/布局）、`frontend/tests/components/CreatorNoteQualityPanel.spec.ts`、`frontend/tests/api/review.spec.ts:29-83`（评估契约 + evaluator 降级）。测试栈：Vitest + @vue/test-utils + createMemoryHistory router。改动 EvaluationView 需新建 spec（挂路由 param/query 模拟列表/详情两态）。
