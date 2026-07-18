# 公开页面（Showcase / WorkflowReplay）UX 现状审计

审计日期：2026-07-17。基线：分支 `feat/analytics-visual-polish`（含 UX V2 全部落地代码）。结论先行：**V2 的数据契约重构（公开 DTO、manifest+detail、final-summary）真实落地且质量不错；但 PRD 声称的组件拆分、转化路径、移动端结果优先、埋点漏斗和 Playwright/axe 门槛均未实现或只实现了一半，且遗留约 1,300 行死代码未清理。**

## 1. 页面结构与数据流

**Showcase（`frontend/src/views/Showcase.vue`，418 行，路由 `/`，懒加载 `router/index.ts:9-13`）**

- 单文件组件，无子组件拆分（PRD §15.1 的 `components/showcase/` 不存在）。仅复用 `AppIcon`、`ThemeToggle`、`PublicReplayResult`。
- 数据流：全部走本地 `ref`（无 store 参与，仅 `useAuthStore` 判登录）：
  - `listPublicCases({limit:100})` → 列表（`Showcase.vue:167`）
  - `getPublicCase(publicId)` → 只给首个案例 + 精选案例拉详情（`:128-129`），30s sessionStorage 缓存 `showcase:public-cases:v2`（`:36-38`）
  - 筛选/搜索/排序全部前端内存计算（`filteredCases` `:50-63`），URL query 双向同步（`:81-104`）
- **WorkflowReplay（`frontend/src/views/WorkflowReplay.vue`，487 行，路由 `/replay/:publicId`）**
- 同样单文件，无 PRD §15.2 的 `ReplayHeader/PhaseNav/Rail/Drawer/ResultCanvas/SequenceControls/FinalSummary` 拆分。
- 数据流：`getPublicReplayManifest`（分页 20/页）+ `getPublicFinalSummary` 并发首屏（`:278-286`），选中后 `getPublicReplayCheckpoint` 按步加载详情；30s sessionStorage 步骤缓存、容量 24（`:112-122`）；AbortController + requestToken stale guard 完备（`:208-260`）。

**公开 DTO 契约**（`frontend/src/types/publicShowcase.ts`；后端 `backend/api/routes/public_showcase.py`）

- `GET /api/public/showcase/cases` → `PublicCaseListResponse`（cases/total/featured_public_id）
- `GET /api/public/showcase/cases/:publicId` → `PublicCase`（含完整 `result`）
- `GET /api/public/replays/:publicId/manifest?include_technical&limit&offset` → steps 仅导航元数据（`public_showcase.py:740-769`，limit 上限 20）
- `GET .../checkpoints/:checkpointPublicId` → 详情带 `result`；认证+`include_technical` 时附加安全 `technical{phase,step,has_next}`（`:818-824`）
- `GET .../final-summary` → 独立稳定 DTO（`:827-856`）
- 后端脱敏：`public_id` 用 HMAC 派生不暴露 threadId（`:123-136`），邮箱/电话/UUID 正则脱敏（`:145-148`），URL 域名白名单（`:151-167`），错误只映射 5 类 category（`:170-182`），调色板颜色白名单防 CSS 注入（`:227-242`），ETag + `Cache-Control: public, max-age=30`（`:185-211`）。可见性默认 private + `XHS_SHOWCASE_PUBLIC_IDS` 灰度（`:101-120`）。契约层扎实。

## 2. 已具备能力（带证据）

- 公开路由免 token 首屏阻塞：`router/index.ts:99-105`
- Showcase：列表优先+skeleton（`Showcase.vue:351-353`）、缓存先渲染后台刷新（`:158-165`）、精选去重（`:53`）、URL 归一化（`:86-88`，有测试）、空/错/筛选空三态区分（`:354-370`）、失败重试（`:191-198`）、案例卡真实 `<a href>` 可新标签打开（`:379`）
- Replay：manifest+detail 模型首屏只 3 请求（`:278-294`）、`?step=` 深链跨分页回填（`:175-180`）、关键/全部步骤切换且全部步骤要求登录（`:333-342`）、上一步/下一步带边界 disabled（`:327-331`, `:448`）、`aria-current="step"` + ol/li/button 原生语义（`:432-433`）、阶段导航 roving tabindex + 方向键/Home/End（`:187-202`）、`aria-live` 选择播报（`:426`）、404/manifest/detail/loadMore 四类错误各自可恢复（`:419-420`, `:436`, `:444`）、复制案例/当前步骤链接（`:360-373`）、稳定最终摘要不随选择变化（`:451-456`）
- 状态/阶段/错误全部 i18n 化，无 raw status/JSON 输出；`auth_failed` → `authorization` → “发布授权需要处理”（`zh-CN.json replay.publicErrorCategory`）
- 字号治理达标：两页无 9–11px 用户可见文字（最小 `text-xs`）
- 触控目标：按钮普遍 `min-h-11`（44px）；双语 key 数量一致（showcase 71、replay 149）
- 暗黑模式：全量 `dark:` 类 + `darkMode:'class'`（`tailwind.config.js`）；首屏前内联主题脚本防闪烁（`index.html`）
- 性能：路由级懒加载、manifest limit≤20、`vue-vendor`/`axios` manualChunks（`vite.config.ts`）
- 埋点：隐私白名单属性（`interactionTelemetry.ts:39-58`），默认真实上报 `/api/public/telemetry`（`:83-92`），后端有事件名+类别白名单（`public_telemetry.py:23-58`），含首案例/首结果耗时事件
- 测试约定：vitest+`@vue/test-utils`+happy-dom，`Showcase.spec.ts`（3 例：精选去重/URL 归一化/缓存水合）、`WorkflowReplay.spec.ts`（4 例：并发首载、下一步深链、渲染不等 URL、分页保滚动）

## 3. PRD 声称实现但缺失/不一致

1. **组件拆分未做**：PRD §0/§15 称 PR-3/PR-5 落地拆分，实际无 `components/showcase/`、无 `Replay*.vue`、无 `presenters/`、无 `composables/useShowcaseCases.ts`/`useReplayManifest.ts`；两 route 文件仍是全部逻辑所在（好处是行数已从 1,988/1,396 降到 418/487）。
2. **Playwright+axe 门槛未建**（PRD §13.4、PR-6）：`@axe-core/playwright` 在 devDependencies 但无 playwright.config、无 e2e 用例、无 npm script。
3. **筛选工具栏与 PRD 不符**（SHOW-05）：要求 `精选/全部/趋势/Brief/已发布` chips + 推荐排序；实际是 status 下拉（含运维味的 `attention`/“需要说明”）+ mode 下拉 + `最近更新/按标题` 排序（`Showcase.vue:345-347`）。`featured_rank` 字段在类型里但前端不用。搜索始终显示，未实现“≥8 条才出现”。
4. **结果数不随筛选更新**（SHOW-05 明确要求）：`resultCount = totalCases || cases.length`（`:65`），筛选后仍显示总数。
5. **Hero 右侧是静态装饰卡而非精选案例**（SHOW-03）：`Showcase.vue:292-308` 是硬编码四步示意，真实精选案例在 `mt-10` 的下一屏；移动端首屏 620px 内**看不到真实案例标题**（违反 PR-3 完成标准，需实测确认但结构必然如此）。
6. **认证用户 CTA 分流错误**（REPLAY-12）：已登录主 CTA 应为“开始新创作 → `/start?source=replay&mode=…`”，实际跳 `dashboard`（`WorkflowReplay.vue:411`, `goWorkspace:355-358`）；所有 CTA 均不带 `source`/`mode` 参数（Showcase `:208-215`、Replay `:349-353`），漏斗无法归因。
7. **返回上下文恢复缺失**（REPLAY-11）：`openReplay` 硬编码 `from:'/'`（`Showcase.vue:219,223`），不含筛选 query；router 无 `scrollBehavior`，返回后筛选保留（在 URL 上）但滚动/焦点不恢复。
8. **阶段导航选“该阶段第一个 step”而非“最近有业务数据的关键 checkpoint”**（REPLAY-03）：`phaseGroups` reduce 取每阶段首个（`:61-70`）；无业务数据阶段直接消失而非禁用+说明。
9. **移动端无步骤抽屉**（REPLAY-05）：49 步时步骤卡网格在 DOM 中排在结果区之前（`:428-459`），移动端需滚过全部步骤卡才到结果——违反“结果优先”线框（§7.5）。
10. **结果四层结构缺两层**（REPLAY-06）：详情面板没有“这一步做了什么”（`step.summary` 只在卡片里，详情 header `:442` 不显示）和“为什么重要”；长文案无“展开全文/复制”，`replay_result_expand/copy` 事件不存在。
11. **新增埋点事件大半未接**（§14.2）：缺 `showcase_case_impression`、`showcase_featured_open`、`replay_step_navigate`（含 method）、`replay_result_expand`、`replay_result_copy`、`replay_share`、`replay_cta_click`；`showcase_filter_change` 虽在事件表里但筛选变更从未上报（只报了 `showcase_filters_clear`）；`showcase_case_open` 只带常量 `has_public_id:true`（`:218`），无信息量。
12. **无效 step 深链静默回退**（REPLAY-10 要求“提示一次”）：`preferredStep` 直接 fallback（`:124-130`）。
13. **死代码未清**（PR-6“删除无引用 legacy UI”）：`AgentResult*.vue` 7 个（868 行）、`CheckpointRail.vue`（175 行）、`useWorkflowReplay.ts`（283 行）全仓无引用；`styles/main.css:1933-1942` 的 `.replay-section` 暗色样式随之失效；`zh-CN/en.json` 里大量 legacy `replay.*`/`showcase.*` key（如 `showcase.workflowCount`、`replay.badge*`）只服务死组件。
14. **旧基线能力回退**：上轮审计称“详情最多 3 并发 + 局部详情重试 + `showcase_detail_retry` 事件”，现只剩首卡+精选两路详情、卡片无详情失败重试 UI（`detailState.error` 在列表模板里无分支）。

## 4. 剩余 UX 问题与优化机会

**P0**

- P0-1 移动端两页转化路径断裂：Replay 已登录 CTA 指错页面、全部 CTA 无 `source` 归因（证据见 §3-6）；Showcase 已登录 CTA 跳 `/start` 但文案仍可能误导（`Showcase.vue:273` 与 `:286` 同一 `startCreating` 文案两种去向）。
- P0-2 移动端 Replay 结果区被步骤网格推到 N 屏之后（`WorkflowReplay.vue:428-459`）；390px 下首屏仅 header+步骤卡。建议移动端默认折叠步骤列表为“第 N 步 · 打开步骤”按钮。
- P0-3 Showcase 首屏无真实证据（§3-5）：390×844 下真实案例标题在 hero 静态卡之后。
- P0-4 埋点漏斗断环（§3-11）：筛选、曝光、阶段选择、展开/复制、CTA auth_state 均缺，`replay_first_result_visible` 语义是“请求完成”而非“进入视口”（`:245-249`）。

**P1**

- P1-1 筛选工具栏产品形态与 PRD 不符、结果数不更新、搜索无防抖且范围仅 title+summary（`Showcase.vue:50-65, 344-347`）。
- P1-2 详情区缺“这一步做了什么/为什么重要”叙事层；无结果复制（`PublicReplayResult.vue` 无 copy 按钮，prediction 用原生 `<details>` 但未埋点）。
- P1-3 阶段导航移动端无自动滚入视口、无边缘渐隐（`:431` 仅 `overflow-x-auto`）；键盘选择步骤后焦点不移到结果标题（`#replay-results` 有 `tabindex="-1"` 但无 `.focus()` 调用）；步骤卡无 Home/End。
- P1-4 返回体验：筛选 query 不带入 `from`、无滚动/焦点恢复（§3-7）。
- P1-5 边界态文案缺失：上一步/下一步 disabled 无“已到起点/终点”说明；无效深链无提示（§3-12）；`replay_available=false`/`has_final_summary` 等 DTO 字段前端完全未消费（卡片无法表达“无完整回放”）。
- P1-6 精选案例 fallback 可选中 `attention` 案例（`Showcase.vue:45-48` 兜底 `cases[0]`），与 SHOW-04“不推荐需人工处理案例”冲突。
- P1-7 对比度风险：精选卡渐变底上 `text-white/75`、`text-white/80`（`Showcase.vue:315-318`）约 2.8:1，不达 AA；未实测，建议 axe 验证。无 `prefers-contrast` 策略。

**P2**

- P2-1 死代码与死 i18n key 清理（§3-13）。
- P2-2 无 OG/Twitter meta（REPLAY-11 P1 可选项）；`index.html` 仅静态 description。
- P2-3 无下一步预取（REPLAY-13 可选）；DTO 无 approved media，案例/结果无图。
- P2-4 reduced-motion 用全局 `0.01ms !important` 一刀切（两页 style 块），能降级但也杀死了必要反馈过渡；无语言切换入口（SHOW-02 P1）。
- P2-5 Showcase 列表 `limit:100` 一次性取，无分页/加载更多；`formatPercent` 不走 locale formatter（`PublicReplayResult.vue:18-21`）。

## 5. 技术约束（新优化必须遵守）

- **样式**：Tailwind utility-first，`darkMode:'class'`；品牌色在 `tailwind.config.js` 的 `neon.*`（pink #F43F5E / cyan #14B8A6），两公开页实际用 slate+rose+teal 语义色；全局样式在 `styles/main.css`（2,014 行，含死代码段）。不要新增全局 dark wildcard。
- **i18n**：`frontend/src/locales/{zh-CN,en}.json` 扁平嵌套 JSON，公开页命名空间 `showcase.*`、`replay.public*`；新增 key 必须双语同步（现有测试含 key 存在性断言的习惯）。
- **动效**：`prefers-reduced-motion` 降级为页面级 `:deep(*)` 强制短时长；新增持续动画每页 ≤2 组、只动 transform/opacity（PRD §11.3）。
- **状态边界**：公开页不引 Pinia 业务 store（仅 auth），请求层统一 `api/client.ts`（axios 包装，`suppressToast`/`signal` 选项）；所有异步必须带 AbortController + token stale guard（现有范式）。
- **测试**：vitest + happy-dom + `@vue/test-utils`，测试在 `frontend/tests/components/`，约定 mock `vue-router`/`@/api/publicShowcase`/`@/stores/auth`、stub AppIcon/ThemeToggle/PublicReplayResult；验证命令 `npm -C frontend run type-check && npm -C frontend run test:run && npm -C frontend run build`。无 e2e 基建（axe 仅有依赖未接线）。
- **埋点**：新增事件名和属性 key 必须同时加进 `interactionTelemetry.ts` 白名单与 `backend/api/routes/public_telemetry.py` 白名单，否则被静默丢弃。

**一句话**：数据契约和加载骨架已是 V2 形态，V3 的真正缺口是：移动端结果优先重排、CTA/归因修正、筛选工具栏对齐 PRD、结果叙事层（做了什么/为什么重要/复制）、埋点漏斗补环、死代码清理，以及把 Playwright+axe 门槛真正建起来。
