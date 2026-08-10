# 前端用户体验全面优化 PRD（UX V3：展示 / 工作流 / 数据分析 / 质量评估）

## 0. 文档信息

| 字段 | 内容 |
| --- | --- |
| 状态 | Confirmed — 已定稿，进入实施 |
| 日期 | 2026-07-17 |
| 优先级 | P0 |
| 产品目标 | 每个页面回答一个核心问题并给出明确的下一步行动；消除一切误导性 UI；收敛跨页面体验基础设施 |
| 核心路由 | `/`（展示页）、`/replay/:publicId`（工作流回放）、`/dashboard/:threadId?`（工作台/工作流实时展示）、`/analytics`（数据分析）、`/evaluation`、`/evaluation/:threadId`（质量评估） |
| 主要范围 | Showcase、WorkflowReplay、Dashboard、Analytics、EvaluationView 五页及其子组件、共享组件（错误态/骨架/图表/表格/指标卡）、埋点、测试与质量门槛 |
| 非主要范围 | 工作流执行逻辑与 API 语义、评估模型与权重算法、后端公开 DTO 脱敏契约（V2 已扎实落地）、全站换肤/视觉改版、Login/Review/History/Settings/Help/TUI 页面（仅在联动点涉及） |
| 当前基线 | `feat/analytics-visual-polish` 分支；UX V2（`07-16-showcase-replay-ux-master-plan`）已落地能力为基线不重做；分支上有 Analytics 未提交的视觉打磨（DataTable cellClass、EngagementChart 多彩柱、互动率配色），实施前需先落地或合入 |
| 证据材料 | `research/showcase-replay-audit.md`、`research/dashboard-audit.md`、`research/analytics-audit.md`、`research/evaluation-audit.md`、`research/shared-infra-audit.md`（2026-07-17 全量代码审计，所有结论带 文件:行号） |
| 建议投入 | 1 名前端主责 + 0.2 名后端（2 个可选配合点）+ QA/设计评审，约 25–35 人日 |

与 V2 的关系：V2 完成了公开数据契约（脱敏 DTO、manifest+detail、final-summary、灰度可见性）、Showcase/Replay 的加载骨架、深链、错误恢复与响应式基线。本 PRD 只在其上做增量，已落地能力不重复实现；Dashboard / Analytics / Evaluation 三页为首次系统优化。

---

## 1. 执行摘要

五页审计（证据见 research/）给出同一个结论：**功能基本可用，但存在一批"误导性 UI"和"断掉的路径"，它们比美观问题更伤害信任。**

各页一句话现状：

- **展示页 Showcase**：契约与骨架已是 V2 形态，但首屏用静态装饰卡代替了真实案例证据，筛选工具栏与 V2 PRD 产品形态不符，转化 CTA 无归因，还留着约 1,300 行死代码。
- **工作流回放页 WorkflowReplay**：桌面端可理解性已达标；移动端 49 步时结果区被推到 N 屏之后，已登录 CTA 指错页面，结果缺"这一步做了什么/为什么重要"的叙事层。
- **工作台 Dashboard**：有两个 P0 正确性 bug（回放深链失效、回放误触发"已完成"庆祝），等待态 CTA 是死链，错误恢复路径分裂成 4 个错误面，进度高水位被三处显示旁路。
- **数据分析页 Analytics**：头号图表"互动趋势"不是时间序列（按星期几分桶且零值误导），暗黑模式下图表不可读，表格排序排的是格式化字符串（"9.0%" > "10.0%"），周期标签与后端语义错位（"全年"实为 30 天）。
- **质量评估页 Evaluation**：详情页没有评估上下文（不知道评的是哪篇），趋势加载失败被吞成"暂无数据"，needs_revision 没有通往改稿的行动出口，"无分"被渲染成红色"0 分"。

本轮三个转变：

1. **正确性先于美观。** 先清零误导性 UI（假趋势、错排序、0 分当无分、回放误庆祝、CTA 死链、阈值漂移），再谈体验增强。每个 P0 都是"用户看到了错误的信息或点了没有反应的按钮"。
2. **每页回答一个核心问题并给出下一步。** Showcase 回答"这东西真有用吗"→ 开始创作；Replay 回答"它是怎么做出来的"→ 我也做一篇；Dashboard 回答"现在进行到哪、要我做什么"→ 直达待办面板；Analytics 回答"最近表现变好还是变差、哪篇最好"→ 下钻与再创作；Evaluation 回答"这篇好不好、差在哪"→ 去改稿。
3. **收敛跨页面基础设施。** 错误态五页三套实现、骨架屏两套、图表无暗色主题、格式化各写各的、reduced-motion 只有 CSS 一刀切——这些统一一次，五页同时受益。

---

## 2. 目标与衡量指标

| # | 目标 | 衡量指标（验收时核查） |
| --- | --- | --- |
| G1 | 清零误导性 UI | §5–§10 中所有标【误导】的条目关闭；code review 无新增硬编码阈值/假数据 |
| G2 | 移动端首屏有效 | 390×844 下：Showcase 首屏可见真实案例标题；Replay 首屏可见结果区；Dashboard 首屏可见状态 Hero + 下一步动作 |
| G3 | 转化路径可度量 | 公开页漏斗事件（曝光→打开案例→步骤导航→结果展开→CTA）全部上报且带 `source` 归因；CTA 跳转带 `source`/`mode` 参数 |
| G4 | 每页有行动出口 | Dashboard 等待态 CTA 100% 落到可交互面板；Evaluation needs_revision/rejected 有改稿入口；Analytics 表格可下钻单篇 |
| G5 | 体验基建统一 | 五页统一错误态组件与骨架屏；图表全部随暗色主题；数字/日期格式化走统一 util；reduced-motion 有 JS 层 |
| G6 | 质量门槛可执行 | Dashboard/Analytics/Evaluation 各有视图级 spec；公开页 axe 扫描 0 critical；新增 i18n key 双语同步率 100% |

---

## 3. 范围

**范围内**：五个页面的信息架构、状态与加载、交互修正、可解释性、移动端、暗色、无障碍、埋点、性能、测试；共享组件（错误态、骨架、图表主题、DataTable、MetricCard）与 util（格式化、reduced-motion、focus）；死代码清理。

**范围外（非目标）**：

- 工作流/评估/分析的后端业务逻辑、API 语义变更（两个可选后端配合点见 §16，均有前端先行方案，不阻塞）
- 评估维度、权重、算法本身的调整（前端只做正确展示与解释）
- 全站视觉改版、品牌色更换、设计系统重建
- Login / Review / History / Settings / Help / AgentTUI 页面本身的优化（仅在与五页的联动点涉及，如 EV-03 跳 `/review/:threadId`）
- V2 已落地的公开 DTO 脱敏、灰度可见性、manifest+detail 加载模型（不返工）

---

## 4. 全局产品决策（本文已拍板，实施不再等待）

- **D1** Showcase Hero 右侧静态四步示意卡替换为**真实精选案例卡**；精选 fallback 永不选中 `attention`（需人工处理）状态案例。
- **D2** CTA 归因与去向：公开页所有 CTA 带 `source` 参数（`showcase`/`replay`）；未登录 → `/login?redirect=/start`；已登录 → `/start?source=…&mode=…`（Replay 带当前案例模式）。Showcase 同一文案不得指向两种去向。
- **D3** 移动端 Replay 结果优先：步骤列表在 `<md` 默认折叠为"第 N/共 M 步 · 选择步骤"抽屉按钮，结果区（最终摘要 + 当前步结果）在 DOM 与视觉上均前置；桌面端保持现有左右结构。
- **D4** Dashboard 状态来源仍唯一 `workflowStore.effectiveState`；**回放快照永不触发"已完成"语义**（庆祝、toast、hero 完成态全部由 isReplay 守卫）；不改变任何工作流 API 语义。
- **D5** Analytics 趋势图改为**按日时间序列**：前端用现有 `PostPerformance.published_at` 分桶（日粒度，周期内无数据日期空缺不画 0），不新增后端端点；若后期数据量不足再评估后端聚合端点。
- **D6** 评估分数语义：无分显示 `—`（不渲染 0）；分数档位阈值与维度权重集中在 `frontend/src/constants/evaluation.ts` 单一模块并注释与 `backend/db/evaluator_config.py` 同步（P1）；后端随 `/evaluation/result` 返回 thresholds/weights（P2，可选配合）。
- **D7** `bias_check` 不进入雷达图（其 `bias_severity` 与 `score` 语义相反），独立偏倚告警卡展示 severity；雷达图只画加权维度，维度顺序由前端固定（不随后端数组漂移）。
- **D8** 五页统一接入泛化后的错误态组件与 skeletons 骨架体系；新代码只用 Tailwind + `dark:` 变体，scoped 硬编码 hex 逐步淘汰（EvaluationView 本轮完成迁移）。
- **D9** 建立图表主题机制：ECharts option 的颜色/轴线/tooltip 全部经 `useChartTheme()` composable 读取 `useThemeStore.isDark`，暗色切换即时重渲染，不刷新页面。
- **D10** 埋点：公开页补全 V2 事件表全部事件；登录页域（Dashboard/Analytics/Evaluation）复用 `interactionTelemetry` 机制新增轻量事件（仅 ID 与计数，无内容）。新事件名与属性 key 必须同步进前端 `interactionTelemetry.ts` 白名单与后端 `public_telemetry.py` 白名单。
- **D11** 不做视觉改版；触控目标 ≥44px、i18n 双语同步、`prefers-reduced-motion` 降级为所有条目的通用验收条件，不再逐条重复。
- **D12** 新建 `utils/format.ts`（`Intl.NumberFormat`/`Intl.DateTimeFormat`，locale 感知），五页的数字、百分比、日期逐步收敛；本轮先覆盖五页新增与修改处。
- **D13** 组件拆分不做为独立目标：V2 声称的 `components/showcase/`、`Replay*.vue` 拆分不再补做（418/487 行的单文件当前可维护）；仅在改动触及区域自然抽取。

---

## 5. 展示页 Showcase（/）— V2 增量

> 核心问题："这东西真的有用吗？" → 答案必须是**首屏可见的真实案例**，而不是装饰示意图。证据详见 `research/showcase-replay-audit.md`。

| 编号 | 优先级 | 事项 |
| --- | --- | --- |
| SH-01 | P0 | **首屏真实证据前置**【说服力】现状：Hero 右侧为硬编码四步静态卡（`Showcase.vue:292-308`），真实精选案例在下一屏，移动端首屏看不到任何案例标题。方案：Hero 右侧替换为精选案例卡（标题、核心指标、模式徽章、打开回放链接）；无精选时回退为列表首个非 attention 案例；再无则隐藏右侧卡。验收：390×844 与 1440×900 首屏均可见真实案例标题；`showcase_featured_open` 事件随点击上报。 |
| SH-02 | P0 | **CTA 归因与去向统一**【断链】现状：同一 `startCreating` 文案两种去向（`Showcase.vue:273,286`），所有 CTA 无 `source`。方案：按 D2 统一；已登录/未登录文案可同词但去向按 D2；全部 CTA 上报 `showcase_cta_click`（含 auth_state、position）。验收：点击任一 CTA 后 `/start` 或 `/login` URL 带 `source=showcase`。 |
| SH-03 | P0 | **埋点漏斗补环**【断链】现状：缺曝光/精选打开/筛选变更事件，`case_open` 只带常量参数（`Showcase.vue:218`）。方案：新增 `showcase_case_impression`（IntersectionObserver，去重）、`showcase_featured_open`、`showcase_filter_change`（含筛选值）、`case_open` 带 mode/status/位置。验收：事件名与属性 key 进前后端白名单；手工触发验证上报。 |
| SH-04 | P1 | **筛选工具栏对齐 V2 产品形态**【误导】现状：status 下拉含运维味 `attention`、结果数不随筛选更新（`:65`）、搜索无防抖且仅搜 title+summary。方案：chips（精选/全部/趋势/Brief/已发布）+ 推荐排序（消费 `featured_rank`）；结果数实时反映筛选后数量；搜索 300ms 防抖、范围含标签/赛道；案例 ≥8 条才显示搜索框。验收：筛选后计数=可见卡片数；`attention` 不出现在任何筛选项。 |
| SH-05 | P1 | **精选 fallback 排除 attention**【误导】现状：兜底取 `cases[0]`（`Showcase.vue:45-48`）可能推荐需人工处理的案例。方案：fallback 过滤 `status==='attention'`。验收：仅含 attention 案例的数据集下精选区隐藏。 |
| SH-06 | P1 | **返回上下文恢复** 现状：`openReplay` 硬编码 `from:'/'`（`:219,223`），返回后筛选在 URL 上但滚动/焦点丢失。方案：`from` 带当前完整 query；router 增加 `scrollBehavior`（savedPosition 恢复）；返回后焦点落到原案例卡。验收：列表→回放→返回，筛选、滚动位置、焦点均恢复。 |
| SH-07 | P1 | **对比度达标**【误导-无障碍】现状：精选卡渐变底上 `text-white/75`、`text-white/80`（`:315-318`）约 2.8:1。方案：提升至 `text-white`/90%+ 或加底衬；纳入 axe 验证。验收：axe 无 color-contrast 违规。 |
| SH-08 | P1 | **详情加载失败局部重试** 现状：V2 基线的局部详情重试回退丢失，`detailState.error` 无 UI 分支。方案：案例卡详情失败时卡内重试按钮 + `showcase_detail_retry` 事件。验收：断网下打开过详情的卡片显示内联重试，恢复后成功。 |
| SH-09 | P2 | **列表分页** 现状：`limit:100` 一次取（`:167`）。方案：20/页"加载更多"（与 Evaluation 列表同模式）。验收：>20 条时可逐页加载且筛选跨页生效。 |
| SH-10 | P2 | **死代码清理** 删除：`AgentResult*.vue` 7 个（868 行）、`CheckpointRail.vue`（175 行）、`useWorkflowReplay.ts`（283 行）、`main.css:1933-1942` 死样式、仅服务死组件的 legacy `showcase.*`/`replay.*` i18n key。验收：grep 无引用；`type-check`/`test:run`/`build` 全绿；bundle 缩小。 |
| SH-11 | P2 | **OG/Twitter meta** 现状：`index.html` 仅静态 description。方案：Showcase/Replay 路由级更新 document.title + og meta（静态值即可，无 SSR）。验收：view-source 与分享调试器可见。 |

---

## 6. 工作流回放页 WorkflowReplay（/replay/:publicId）— V2 增量

> 核心问题："它是怎么做出来的？结果是什么？" → 移动端也必须先看到结果。证据详见 `research/showcase-replay-audit.md`。

| 编号 | 优先级 | 事项 |
| --- | --- | --- |
| RP-01 | P0 | **移动端结果优先**【断链】现状：49 步时步骤卡网格在 DOM 中先于结果区（`WorkflowReplay.vue:428-459`），390px 首屏只有步骤卡。方案：按 D3，`<md` 步骤区默认折叠为抽屉按钮（显示"第 N/共 M 步"），结果区（最终摘要+当前步详情）前置；抽屉内复用现有步骤卡与键盘导航。验收：390×844 首屏可见最终摘要；抽屉打开后原有导航/aria 行为不变。 |
| RP-02 | P0 | **已登录 CTA 修正**【断链】现状：已登录主 CTA 跳 `dashboard`（`WorkflowReplay.vue:411,355-358`）。方案：按 D2 改跳 `/start?source=replay&mode={当前案例模式}`；次要入口保留"回到工作台"。验收：已登录点击主 CTA 落在 `/start` 且带参。 |
| RP-03 | P0 | **结果叙事层**【可理解性】现状：详情 header 无"这一步做了什么"（summary 只在卡片）、无"为什么重要"、长文案无展开/复制。方案：详情区顶部加 step.summary 与重要性说明（i18n 模板按 phase 映射）；长结果加"展开全文/收起"与"复制结果"按钮；上报 `replay_result_expand`/`replay_result_copy`。验收：任一关键步骤详情可见 summary；复制按钮写剪贴板成功。 |
| RP-04 | P0 | **无效深链提示** 现状：`?step=` 无效时静默 fallback（`:124-130`）。方案：toast 提示一次"指定步骤不存在，已为你定位到最新关键步骤"。验收：无效 step 参数出现一次性提示且选中兜底步骤。 |
| RP-05 | P1 | **阶段导航选中有意义的 checkpoint**【误导】现状：`phaseGroups` 取每阶段第一个 step（`:61-70`），无业务数据阶段直接消失。方案：选每阶段"最近有业务数据的关键 checkpoint"；无数据阶段显示为禁用态+原因 tooltip。验收：点击阶段落在有结果的步骤；空阶段可见但不可选。 |
| RP-06 | P1 | **键盘与焦点闭环** 现状：键盘选步后焦点不移到结果（`#replay-results` 有 tabindex 但未 focus）；阶段导航移动端不自动滚入视口、无边缘渐隐；步骤卡无 Home/End。方案：选步后 `.focus()` 结果标题；选中阶段 `scrollIntoView({inline:'nearest'})`；导航容器边缘渐隐；步骤卡补 Home/End。验收：纯键盘操作可选步并听到/看到结果更新。 |
| RP-07 | P1 | **边界态文案** 现状：上一步/下一步 disabled 无说明；`replay_available`/`has_final_summary` DTO 字段未消费。方案：边界 disabled 加"已到起点/终点"aria 与 title；`replay_available=false` 案例卡表达"无完整回放"。验收：首步/末步有明确边界说明。 |
| RP-08 | P1 | **埋点补环** 现状：缺 `replay_step_navigate`（含 method：click/keys/prev/next）、`replay_share`、`replay_cta_click`（含 auth_state）；`replay_first_result_visible` 语义是"请求完成"而非进入视口（`:245-249`）。方案：按 V2 事件表补齐；first_result 改 IntersectionObserver。验收：全部事件在白名单并可上报。 |
| RP-09 | P2 | **下一步预取** 现状：无预取。方案：选中步骤后空闲预取下一步详情（沿用现有 24 容量缓存）。验收：连续"下一步"无加载闪烁。 |
| RP-10 | P2 | **reduced-motion 精细化** 现状：页面级 `0.01ms !important` 一刀切杀死必要反馈。方案：改为仅禁用装饰性动画，保留状态反馈的透明度淡入（≤100ms）。验收：reduced-motion 下无位移动画，状态切换仍可感知。 |

---

## 7. 工作台 Dashboard（/dashboard/:threadId?）— 首次系统优化

> 核心问题："现在进行到哪一步？需要我做什么？" → 下一步动作必须真实可达。证据详见 `research/dashboard-audit.md`。

### 7.1 P0 正确性修复

| 编号 | 事项 |
| --- | --- |
| DB-01 | **回放深链时机修复**【断链】现状：setup 阶段读 `activeThreadId` 时路由参数尚未写入（`Dashboard.vue:30-33` vs `onMounted:162`），新会话打开 `/dashboard/X?replay=true` 静默失败或加载错线程快照。方案：改为在 `setThreadId` 完成后（onMounted 内或 watch activeThreadId）再判断 `route.query.replay` 进入回放。验收：新会话直接打开 History 的回放链接进入正确线程的回放；新增回归测试。 |
| DB-02 | **回放不触发完成语义**【误导】现状：`watch(currentPhase)` 无 isReplay 守卫，回放 completed checkpoint 弹庆祝窗+发"已完成"toast（`Dashboard.vue:115-124`）。方案：庆祝与 toast 触发条件加 `!isReplay`；按 D4 复核所有 completed 派生语义。验收：回放完成态 checkpoint 无庆祝无 toast；`dashboardHero.spec` 补用例。 |

### 7.2 P1 路径与状态一致性

| 编号 | 事项 |
| --- | --- |
| DB-03 | **进度高水位不被旁路**【误导】现状：三处显示优先读原始 `progress_percent`（`Dashboard.vue:105`、`WorkflowHeader.vue:31-34`、`WorkflowTimeline.vue:145-148`），reangle/retopic 时进度条倒退。方案：store 暴露统一的 `displayProgress`（高水位 clamp 后），三处显示只读它。验收：reangle 后进度不倒退；`workflow.spec` 已有单调性测试扩展覆盖。 |
| DB-04 | **等待态 CTA 落地**【断链】现状：nextAction 对 awaiting_* 统一 `path:'/dashboard'`（`:72-78`）是空操作；"编辑草稿"同病（`ActionButtons.vue:161-173`）。方案：等待面板挂锚点 id，CTA 点击滚动到对应面板并聚焦首个可交互控件（`scrollIntoView` + focus，reduced-motion 下瞬时滚动）。验收：每个 awaiting_* 状态下点 CTA 后目标面板进入视口且焦点正确。 |
| DB-05 | **错误恢复路径收敛**【误导】现状：错误时同时可能出现 4 个错误面（ErrorState/ErrorCard/hero rose/timeline 横幅），nextAction 错误分支复用"开始创作"跳 `/start`（`:89-97`）与 ErrorState"重试=resume"相反。方案：错误信息单一来源——hero 显示错误态、页面只保留一个错误操作区（重试=resume 当前 threadId + 查看历史 + 开始新创作为次级）；nextAction 错误分支删除或改指向 resume。验收：任一错误下页面仅一个主恢复 CTA；重试只刷新当前 threadId（既有红线）。 |
| DB-06 | **"跳转到待办"机制** 现状：等待决策面板在长页面底部，需滚动寻找。方案：nextAction 卡片即锚点入口（同 DB-04）；运行中/等待时 Hero 下方固定"待办" chips 直达。验收：creating 完成后 1 次点击到达决策面板。 |
| DB-07 | **时间线运行中信息增强** 现状：子步骤无耗时、运行中 entry 显示 `—`、ETA 启发式粗糙（`WorkflowHeader.vue:92-98`）。方案：子步骤显示已耗时（live 累计）；agent 明细运行中 entry 显示进行时长；ETA 标注"约"并在样本不足时隐藏。验收：运行中可见当前 agent 已运行时长。 |
| DB-08 | **切标签同步 URL** 现状：`switchTab` 不 `router.replace`（`workflow.ts:339-349`），刷新后回到旧 threadId。方案：切换时 `router.replace(/dashboard/{threadId})`。验收：切标签后刷新停留在当前线程。 |
| DB-09 | **WS 断连手动重连** 现状：重连次数用尽后无入口（`websocket.ts:314-317`、`ConnectionStatus.vue:56`）。方案：断连态在 OfflineRecovery/ActionButtons 提供"重新连接"按钮（不新增第二条横幅，遵守连接状态单一来源）。验收：断网恢复后可手动重连且不重复渲染断连提示。 |

### 7.3 P2 打磨与性能

| 编号 | 事项 |
| --- | --- |
| DB-10 | **庆祝模态真实化** 现状：统计格是 ✓/100%/🎉 装饰（`CelebrationModal.vue:124-137`），无转化 CTA，confetti 无 reduced-motion 降级。方案：显示真实产物计数（如生成文案数/图片数）；加"查看帖子/再来一篇"CTA；confetti 加 `prefers-reduced-motion` 媒体查询。 |
| DB-11 | **进度可视化去重** 现状：hero 条+CircularProgress+MiniProgress+timeline 线四处同值。方案：hero 保留总进度条；WorkflowHeader 的 CircularProgress 改为阶段指示；MiniProgress 仅窄屏显示。 |
| DB-12 | **触控目标补齐** 现状：标签关闭钮 ~20px（`WorkflowTabBar.vue:228`）、回放子步骤 28px（`WorkflowTimeline.vue:431,442`）；双击改名触屏不可用。方案：可点区域扩至 ≥44px（视觉图标可小）；改名增加长按/菜单入口。 |
| DB-13 | **ContentCards 状态与样式收敛** 现状：creating 长阶段 3 张脉冲骨架无"当前在做什么"文案；draft 区块硬编码 blue-*；`ContentCards.vue:606-607` 硬编码中文兜底。方案：骨架配当前阶段说明文案；色值换主题 token；兜底走 i18n。 |
| DB-14 | **高频事件节流** 现状：`RIPPLE_PROGRESS` 每次重建 map 触发整树重渲（`workflow.ts:549-571`）。方案：200ms 节流 + 仅变更行更新。验收：高频事件下 CPU/重渲可测改善（不追求精确数值，code review + 手工验证）。 |
| DB-15 | **视图级测试补齐** 新建 `tests/views/Dashboard.spec.ts`：回放深链（DB-01）、回放不庆祝（DB-02）、nextAction 四分支、错误收敛（DB-05）。 |

---

## 8. 数据分析页 Analytics（/analytics）

> 核心问题："最近表现变好还是变差？哪篇笔记最好、为什么？" → 首屏先给结论，图表必须是真的趋势。证据详见 `research/analytics-audit.md`。

### 8.1 P0 正确性修复（四项均为误导性 UI）

| 编号 | 事项 |
| --- | --- |
| AN-01 | **真时间序列趋势图**【误导】现状："互动趋势"按周一~周日分桶平均（`Analytics.vue:62-77`），无帖星期画 0，切周期语义不变。方案：按 D5 用 `published_at` 做日粒度时间序列（发布量+互动量双轴或切换）；无数据日期 `connectNulls:false` 空缺；x 轴真实日期；标题改为"近期表现趋势"。验收：weekly 周期显示 7 个日期刻度；无帖日期无 0 值柱/点。 |
| AN-02 | **图表暗色主题**【误导-可读性】现状：tooltip 白底深字、轴 `#64748B`、分割线近不可见（`TrendChart.vue:69-91`、`EngagementChart.vue:87-94`），charts/ 零引用 themeStore。方案：按 D9 建 `useChartTheme()`，两图 + EvaluationRadar 全部接入；暗色切换即时更新。验收：暗色下 tooltip/轴/分割线清晰可读；切换主题无刷新。 |
| AN-03 | **排序按原始数值**【误导】现状：`views_display`/`engagement_rate_display` 按格式化字符串排序（`Analytics.vue:114-131`、`DataTable.vue:51-56`）。方案：列定义加 `sortKey` 指向原始数值字段；DataTable 排序读 `sortKey ?? key`。验收："10.0%" 排在 "9.0%" 前；"1,234" 排在 "999" 前；新增 DataTable 排序测试。 |
| AN-04 | **周期语义对齐**【误导】现状：UI 把 daily→"本周"、weekly→"本月"、monthly→"全年"（`Analytics.vue:261,265`），后端实为 24h/7d/30d；指标卡 subtitle 写死"本周"（`:39-42`）。方案：标签改"24 小时/近 7 天/近 30 天"；subtitle 随周期动态。验收：三档标签与后端语义一致；切 monthly 后无"本周"字样。 |

### 8.2 P1 核心问题回答能力

| 编号 | 事项 |
| --- | --- |
| AN-05 | **首屏涨粉指标** 现状：5 张指标卡无粉丝/涨粉，fans 埋在 CreatorStatsPanel 内部。方案：指标卡区加入"粉丝数/周期涨粉"卡（数据源 creator-stats 已有字段，`api/analytics.ts:87`）；AI 费用卡移出首屏指标区（并入成本卡）。验收：首屏可见粉丝与涨粉。 |
| AN-06 | **结论先行重排** 现状：增长洞察排在成本之后（`:341-535`）。方案：页面顺序 → 指标卡 / 增长洞察 / 趋势+构成图 / TOP 笔记表 / 成本卡（折叠为次级）。验收：首屏第二屏内可见洞察。 |
| AN-07 | **环比 delta** 现状：指标卡只有绝对值。方案：前端按 `published_at` 把帖子分"本周期/上周期"两桶计算环比（浏览/互动/发布数），MetricCard 加 delta 展示（↑↓ 与百分比，样本不足显示 `—` 并注明）。验收：weekly 下显示"vs 前 7 天"。 |
| AN-08 | **单篇下钻**【断链】现状：表格行不可点，但 `getCreatorNote`/`getCreatorNoteQuality` 与 `CreatorNoteQualityPanel` 已存在。方案：DataTable 加行点击 emit；Analytics 打开抽屉/对话框展示单篇详情与质量面板（复用现有组件）；热门话题→`/start` 保持。验收：点击行可见单篇详情与质量雷达。 |
| AN-09 | **刷新失败不静默**【误导】现状：有缓存时 fetch 失败界面无提示（`Analytics.vue:33`、store:89）。方案：有数据时失败 → 内联提示条"数据更新失败，展示的是上次数据"+重试；同时刷新 `lastUpdatedAt` 语义（WS 推送也更新）。验收：断网刷新出现提示条，旧数据保留。 |
| AN-10 | **双周期选择器统一** 现状：页面级 daily/weekly/monthly 与 CreatorStatsPanel 自带 7d/30d 并存互不联动。方案：CreatorStatsPanel 的选择器收纳进面板内部（标明"创作者中心数据周期"），页面级选择器只控本页图表；两者视觉分组区分。验收：不存在看似联动实则独立的两个选择器并排。 |
| AN-11 | **表格完整性** 现状：`slice(0,10)` 后 10 篇不可达；最佳行高亮无解释；列头无排序态 aria。方案：默认 10 条+"查看全部 20 条"展开；最佳行加"最佳"徽标与图例；列头 `aria-sort`。验收：20 篇全部可达；高亮含义有文字说明。 |
| AN-12 | **局部刷新反馈** 现状：切周期只有刷新钮转圈；重进页不自动重试（`Analytics.vue:27`）。方案：切换周期时图表/表格区 busy 态（保留旧数据+遮罩）；进页若上次失败自动重试一次。 |

### 8.3 P2 打磨

| 编号 | 事项 |
| --- | --- |
| AN-13 | EngagementChart aria 描述 i18n（现硬编码英文，`EngagementChart.vue:52`）；图表空数据可视占位（非仅 aria 层）。 |
| AN-14 | 趋势图加数据点 symbol（移动端可读值）与可选 dataZoom；移除未配置的 LegendComponent 注册。 |
| AN-15 | MetricCard `aria-live` 收敛（刷新不朗读全部数字）；评估引入 AnimatedCounter 且必须经 reduced-motion JS 层（INF-05）。 |
| AN-16 | CSV 导出 TOP 笔记（前端生成，无需 ECharts toolbox）。 |
| AN-17 | 表格补 shares 列或与构成图口径对齐；DataTable 行类型替换 `Record<string, any>`。 |
| AN-18 | 视图级测试补齐：`tests/views/Analytics.spec.ts`（三态、周期切换、排序、下钻、环比）。 |

---

## 9. 质量评估页 Evaluation（/evaluation、/evaluation/:threadId）

> 核心问题："这篇笔记好不好、差在哪、接下来怎么办？" → 分数必须可解释，结论必须通向行动。证据详见 `research/evaluation-audit.md`。

### 9.1 P0 上下文与行动出口

| 编号 | 事项 |
| --- | --- |
| EV-01 | **详情页评估上下文**【断链】现状：详情 PageHeader 只有通用"评估详情"（`EvaluationView.vue:413-427`），深链进来不知道评的是哪篇。方案：详情头部显示笔记标题、账号、threadId（可复制）、评估时间、decision 徽章；`openDetail` 带上下文或详情接口数据补齐。验收：深链打开详情即可确认评估对象。 |
| EV-02 | **趋势失败与无数据区分**【误导】现状：`loadTrend` catch 吞错一律显示"暂无历史评估数据"（`:182-191,335`）。方案：趋势卡三态（加载/失败含重试/真无数据），遵守空态红线。验收：断网下趋势卡显示失败+重试，而非"暂无数据"。 |
| EV-03 | **行动出口**【断链】现状：needs_revision/rejected 只有纯文本 hints，无改稿入口（全文件无 `/review` 引用）。方案：详情页按 decision 渲染主 CTA——needs_revision/rejected → "去审核页改稿"（`/review/:threadId`，改稿后自动重评估为既有能力）；approved → "查看工作流/再次创作"。验收：任一 needs_revision 评估 1 次点击到达改稿界面。 |

### 9.2 P1 分数语义与可解释性

| 编号 | 事项 |
| --- | --- |
| EV-04 | **阈值单一来源**【误导】现状：`scoreTier` 硬编码 70/50（`:143-147,486`），后端可按账号覆盖（`evaluator_config.py:64-65`）。方案：按 D6 建 `constants/evaluation.ts`；维度行内联判断一并收敛。验收：全仓仅一处阈值定义。 |
| EV-05 | **无分不渲染 0 分**【误导】现状：列表/详情 `overall_score ?? 0` 显示红色 `0.0`（`:391-393,230,452`）。方案：null/undefined → `—`（中性色+说明"暂无评分"）。验收：无分记录不再显示 0.0。 |
| EV-06 | **bias_check 独立展示**【误导】现状：与加权维度同尺度入雷达（`EvaluationRadar.vue:38-45`），`bias_severity` 前端未使用。方案：按 D7 雷达剔除 bias_check；偏倚告警卡展示 severity 等级与说明。验收：雷达只含加权维度；severity 高时告警卡醒目。 |
| EV-07 | **维度数与文案真实**【误导】现状："9 维"标题写死（8 维旧数据不符）、en 还是 "6-Dimension"（`en.json:691` vs `zh-CN.json:691`）。方案：标题动态 `{count} 维`；双语同步修复。验收：8/9/10 维数据下标题均正确。 |
| EV-08 | **维度解释与权重可见** 现状：维度只有名称，无"评什么"解释；加权关系不可见。方案：维度行加 TooltipHelper 解释（10 维说明文案双语）；总分卡注明"加权总分"并可在维度列表查看权重（来自 D6 常量模块）。验收：每维可见含义说明；权重可查证。 |
| EV-09 | **历史浏览增强** 现状：搜索仅已加载页内前端过滤；无筛选；趋势点不可点；账号过滤未接。方案：decision 筛选 chips + 分数段筛选（前端对已加载数据，标注范围）；趋势图点点击跳 `/evaluation/:threadId`；列表接入既有 `account_id` 参数（跟随当前账号+"全部账号"切换）。验收：可按 decision 过滤；点趋势点打开对应详情。 |
| EV-10 | **维度映射单一来源** 现状：`DIMENSION_LABEL_KEYS` 4 处重复维护且 Review 缺 `altruism`（`Review.vue:332-342`）。方案：移入 `constants/evaluation.ts`（或 types/evaluation.ts 导出），4 处引用统一。验收：grep 仅一处定义；Review 不再显示原始 key。 |
| EV-11 | **骨架屏替换文本加载** 现状：列表/详情加载为纯文本（`:357-359,430`）。方案：接入 skeletons 体系（新增 EvaluationSkeleton）。验收：加载态为结构化骨架。 |

### 9.3 P2 打磨

| 编号 | 事项 |
| --- | --- |
| EV-12 | **dark mode 统一** 现状：EvaluationView scoped 硬编码 hex 无 dark 变体，与同页 creator tab 割裂（`:510-663`）。方案：按 D8 迁移 Tailwind + dark: 变体。 |
| EV-13 | 搜索空态文案区分"无匹配/真无数据"（`:361-368`）；趋势日期本地化（替换 `slice(5,16)`，用 INF-04）；列表 aria-label 含分数与 decision。 |
| EV-14 | 雷达维度顺序前端固定；tooltip 显示该维 rationale 摘要；320px 雷达在窄屏降高。 |
| EV-15 | 手动 RQGM 评估：运行中加"预计 10-30 秒/产生 LLM 费用"提示；结果在切换笔记前保留（会话内）。 |
| EV-16 | 清理遗留 i18n key（`zh-CN.json:2053,2065-2068`）；`VersionCompare.vue:237` 误用 avgEngagementRate 作分数 label 一并修正。 |
| EV-17 | 视图级测试补齐：`tests/views/EvaluationView.spec.ts`（列表/详情两态、decision CTA、无分显示、趋势三态）。 |

---

## 10. 跨页面基础设施

> 一次收敛，五页受益。证据详见 `research/shared-infra-audit.md`。

| 编号 | 优先级 | 事项 |
| --- | --- | --- |
| INF-01 | P0 | **统一错误态组件** 现状：五页三套手写错误卡（ErrorState/ErrorCard 仅 Dashboard 用）。方案：泛化 `ErrorState`（props：类型/标题/描述/重试/次行动，不绑定 workflowStore；Dashboard 的 store 绑定经适配层保留），Showcase/Replay/Analytics/Evaluation 手写错误卡全部替换。验收：五页错误态同组件渲染；保留各页现有恢复语义（Replay 四类错误、Analytics 缓存提示条等）。 |
| INF-02 | P1 | **骨架屏统一** 现状：Showcase/Replay/Evaluation 未用 skeletons 体系。方案：三页接入；新增 EvaluationSkeleton。 |
| INF-03 | P1 | **图表主题机制** 即 D9：`composables/useChartTheme.ts` 输出 ECharts 主题化 option 片段（文字/轴/分割线/tooltip/色板），watch `isDark`；TrendChart/EngagementChart/EvaluationRadar 接入；图表色板从硬编码 hex 收敛到主题常量。 |
| INF-04 | P1 | **格式化 util** 新建 `utils/format.ts`：数字（千分位/紧凑）、百分比、日期（相对/绝对、locale 感知）；替换五页自写 `toLocaleString` 与 `slice` 切日期。 |
| INF-05 | P1 | **reduced-motion JS 层** 新建 `composables/useReducedMotion.ts`（matchMedia + 响应式）；AnimatedCounter/useAnimation/庆祝 confetti/计数动画接入；保留 `main.css` 全局 CSS 降级。 |
| INF-06 | P1 | **焦点管理** 新建轻量 focus-trap util + skip-link（App.vue main 已有 tabindex）；modal 三处自实现逻辑收敛；Replay 选步后焦点策略（RP-06）复用。 |
| INF-07 | P2 | **z-index 分层 token** 在 tailwind.config 定义 `zIndex: { base, sticky, overlay, modal, toast }` 语义层，替换 `z-[80]`/`z-[100]` 魔法值（渐进，先新代码）。 |
| INF-08 | P1 | **登录页域埋点** 复用 `interactionTelemetry`：Dashboard（cta_click、replay_enter、tab_switch）、Analytics（period_change、note_drilldown、topic_click）、Evaluation（decision_cta、drilldown、filter_change）；前后端白名单同步。 |
| INF-09 | P1 | **测试补齐与门槛** 三页视图 spec（DB-15/AN-18/EV-17）；建立 vitest 内 axe 检查（`axe-core` 对公开页关键态 0 critical，比 Playwright 门槛低——Playwright e2e 列入 P2 可选）；CI 加 i18n 双语 key 一致性脚本（现有人工核对脚本固化）。 |
| INF-10 | P2 | **性能预算** echarts 进 manualChunks 独立 chunk（Analytics/Evaluation 去重）；路由 chunk 预算延续 500KB warning；可选 rollup-plugin-visualizer 本地分析（dev 依赖，不进 CI 硬门槛）。 |
| INF-11 | P2 | **TooltipHelper 启用** 用于 EV-08 维度解释与 RP-05 阶段 tooltip（变死代码为正式能力，顺带修复其定位边界）。 |

---

## 11. 通用要求（全部条目适用）

- **样式**：新代码只用 Tailwind + `dark:` 变体；禁止新增 scoped 硬编码 hex；禁止新增全局 dark wildcard 覆盖（`main.css` 覆盖层只减不增）。
- **i18n**：所有文案进 `en.json`/`zh-CN.json` 双语；禁止硬编码兜底（参照 `ContentCards.vue:606` 反例）。
- **触控与响应式**：可交互元素 ≥44px；所有布局变更须在 390×844、768×1024、1440×900 三档手工验证。
- **动效**：持续动画每页 ≤2 组、只动 transform/opacity；全部经 `prefers-reduced-motion` 降级（CSS + INF-05 JS 层）。
- **无障碍**：新交互可纯键盘完成；状态变化有 aria-live 或焦点管理；对比度 ≥ AA（axe 验证）。
- **状态红线**（docs/frontend-ux-optimization.md，不得违反）：Dashboard 状态唯一来源 `effectiveState`；连接状态唯一来源 `realtimeStore.connectionStatus`；API 重试只刷新当前 threadId；空态区分"无数据/加载失败"并给下一步；公开页不引入业务 store；异步请求带 AbortController + stale guard。
- **埋点红线**：新事件名与属性 key 同步进 `interactionTelemetry.ts` 与 `backend/api/routes/public_telemetry.py` 白名单；不采集内容文本。

## 12. 埋点方案汇总

公开页（补全 V2 事件表）：`showcase_case_impression`、`showcase_featured_open`、`showcase_filter_change`、`showcase_cta_click`、`showcase_detail_retry`、`replay_step_navigate`（method）、`replay_result_expand`、`replay_result_copy`、`replay_share`、`replay_cta_click`（auth_state）、`replay_first_result_visible`（改 IntersectionObserver 语义）。

登录页域（新增，INF-08）：`dashboard_cta_click`、`dashboard_replay_enter`、`dashboard_tab_switch`、`analytics_period_change`、`analytics_note_drilldown`、`analytics_topic_click`、`evaluation_decision_cta`、`evaluation_drilldown`、`evaluation_filter_change`。

属性白名单仅允许：页面名、位置、method、auth_state、mode、decision、period、计数类数值。**禁止**上报标题/正文/账号名等内容。

## 13. 性能预算

- 路由懒加载现状保持；echarts 独立 chunk（INF-10）；入口 chunk 体积不较基线增长 >10%。
- Showcase 列表分页（SH-09）；Replay 预取受既有 24 容量缓存约束（RP-09）；Dashboard 高频事件节流（DB-14）。
- `npm run build` 的 chunkSizeWarning（500KB）不得新增告警；AgentTUI 既有大 chunk 提示除外（既有说明）。

## 14. 测试与质量门槛

- 新增视图 spec：`tests/views/Dashboard.spec.ts`、`tests/views/Analytics.spec.ts`、`tests/views/EvaluationView.spec.ts`（覆盖各自 P0/P1 行为）；DataTable 排序与 ErrorState 泛化补组件 spec。
- 既有测试不得破坏（特别注意 `theme1-loading.spec.ts` 断言 AnalyticsSkeleton 结构、Showcase/WorkflowReplay spec 的 mock 约定）。
- 公开页关键态 axe 检查（vitest + axe-core）0 critical；Playwright e2e 为 P2 可选增强。
- 每个 PR 完成命令：`cd frontend && npm run type-check && npm run test:run && npm run build` 全绿。

## 15. 里程碑（PR 划分与依赖）

| PR | 内容 | 包含条目 | 估算 |
| --- | --- | --- | --- |
| PR-1 | 公开页转化路径修正 | SH-01/02/03、RP-01/02/04、INF-01（错误态先行为后续 PR 铺路） | 4–5 人日 |
| PR-2 | 公开页体验增强与清理 | SH-04~08、RP-03/05/06/07/08、INF-11 | 4–5 人日 |
| PR-3 | Dashboard 正确性与路径 | DB-01~06、DB-08、DB-09、DB-15 | 4–6 人日 |
| PR-4 | Analytics 正确性（误导清零） | AN-01~04、INF-03、INF-04 | 3–4 人日 |
| PR-5 | Analytics 深度与下钻 | AN-05~12、AN-18 | 4–5 人日 |
| PR-6 | Evaluation 上下文/行动/分数语义 | EV-01~07、EV-10、EV-17 | 3–4 人日 |
| PR-7 | Evaluation 可解释性与主题统一 | EV-08/09/11~16、INF-02 | 2–3 人日 |
| PR-8 | 基建收尾与 P2 打磨 | INF-05/06/07/08/09/10、SH-09~11、RP-09/10、DB-10~14、AN-13~17 | 3–4 人日 |

依赖关系：INF-01（统一错误态）先行，PR-1 携带；INF-03/INF-04 是 AN-01/AN-02 与 EV-13 的前置，放 PR-4；DB-15/AN-18/EV-17 随各页 PR 同步交付，不留尾巴。每个 PR 独立可合、独立可回滚。

## 16. 风险与依赖

- **在途改动**：`feat/analytics-visual-polish` 上 Analytics 三文件未提交改动（cellClass、多彩柱、互动率配色）需先提交/合入，PR-4 在其之上进行，AN-03 排序修复注意与 cellClass 钩子兼容。
- **可选后端配合（不阻塞）**：① `/evaluation/result` 返回 thresholds/weights（D6 P2，无此前端用常量模块）；② Analytics 时间序列聚合端点（D5 已决策前端分桶，数据量不足时再议）。
- **ECharts 主题切换**：watch isDark 整 option 重建可能引起闪动——采用 `setOption(option, {notMerge:false})` 增量更新并接受一次性过渡。
- **测试影响面**：INF-01 替换五页错误卡、SH-10 删除死代码、EvaluationView 样式迁移均触及现有测试断言（骨架结构、i18n key 存在性），随 PR 同步更新。
- **后端维度集合可变**：评估维度/权重由 `evaluator_config.py` 与训练脚本驱动，前端一切维度展示必须数据驱动（D6/D7），禁止写死维度列表——EV-10 的常量模块只是 label/解释文案的映射，不是维度全集声明。

## 17. 验收标准（发布前总闸）

1. G1–G6 全部达成（§2 表逐项核查）。
2. 五页在 390×844 / 768×1024 / 1440×900 三档、明暗双主题下人工走查无阻断问题。
3. `type-check`、`test:run`、`build` 全绿；新增 spec 覆盖各页 P0 行为；公开页 axe 0 critical。
4. 公开页漏斗事件在真实环境验证上报齐全且带归因。
5. 无任何 P0【误导】/【断链】条目遗留；P1 遗留项须明示并排期。
6. `docs/frontend-ux-optimization.md` 同步更新（信息架构/状态约定/新增共享组件与 util 的约定）。

## 18. 实施审计（2026-07-19）

### 本轮已完成并有代码/测试证据的条目

- Showcase：SH-01~08 已在 PR-1/PR-2 基线完成；SH-09 列表分页、SH-10 无引用 replay 死代码清理、SH-11 路由级 SEO 元信息已完成。
- Replay：RP-01~08 已在 PR-1/PR-2 基线完成；RP-09 下一步空闲预取、RP-10 reduced-motion 精细降级已完成。
- Dashboard：DB-01~06、DB-08、DB-09、DB-15 已有实现/视图 spec；DB-07 已增加运行中 agent 时长、样本不足时隐藏 ETA；DB-14 已实现按 job 的 200ms trailing throttle。
- Analytics：AN-01~12 已有实现/视图 spec；AN-13 图表摘要与可见空态、AN-14 趋势点与无用 Legend 注册清理、AN-16 CSV 导出、AN-17 shares 列与 DataTable `unknown` 行类型已完成。
- Evaluation：EV-01~07、EV-10~11 已有实现/视图 spec；EV-13 无匹配空态、EV-14 雷达固定顺序/rationale tooltip/窄屏高度已完成。
- 基建：INF-03~06、INF-08、INF-10 已有代码证据；i18n 双语检查脚本通过；新增公开页 meta util、Dashboard 计时和图表文案均已双语同步。

### 仍需发布前处理的条目/证据

- INF-01/INF-02：Showcase、Replay、Analytics、Evaluation 的错误态和公开页 skeleton 尚未全部收敛到同一泛化组件；当前各页的局部恢复语义仍需保留后再统一。
- INF-09：当前已有 Dashboard/Analytics/Evaluation view spec，但公开页 axe 0-critical 检查尚未接入 Vitest/CI；需要在发布环境补跑无障碍扫描。
- INF-11/EV-08：Evaluation 维度说明目前以可聚焦 title/aria 入口呈现，TooltipHelper 尚未正式接入；若要求统一浮层组件，需补一次组件 API 适配。
- DB-10~13、AN-15、EV-12、EV-15~16 仍为 P2 打磨项；不阻塞 P0/P1 代码合并，但必须在发布说明中明确延期。

### 验证结果

- `cd frontend && npm run type-check`：通过。
- `cd frontend && npm run i18n:check`：通过（1861 keys，双语一致）。
- `cd frontend && npm run test:run`：通过，47 个文件 / 573 个测试。
- `cd frontend && npm run build`：通过；存在既有 AgentTUI、ECharts 大 chunk warning，无新增构建失败。
- 未完成：390/768/1440 三档明暗主题人工走查、公开页 axe 扫描、部署后真实埋点与健康检查证据。因此本任务保持 `in_progress`，不能把 G1~G6 全部标记为发布完成。

## 19. 收尾复核（2026-08-09）

本次复核补齐了此前审计记录中的实现缺口，并以当前代码和门槛结果为准：

- INF-01：五页均使用 `components/ErrorState.vue`；Dashboard 的 workflow/error store 仍通过
  适配分支接入，公开页不绑定工作流 store。
- INF-02：Showcase、WorkflowReplay、Analytics、Evaluation 均接入对应 skeleton；Dashboard
  内容卡在长阶段加载时补充当前阶段说明。
- DB-13：ContentCards 的草稿/版本表面改为主题 token，状态枚举兜底走 i18n；新增组件测试。
- AN-18：Analytics view spec 覆盖加载、错误重试、周期切换、服务端 delta、原始数值排序、
  行点击下钻和 stale 数据提示。
- INF-09/INF-10：Vitest axe 关键态检查已进入前端测试；ECharts 手动分包改为实际注册模块，
  当前 build 不再出现 500KB chunk 警告。
- i18n：错误建议数组改用 `tm`，并兼容旧 `zh` locale；`i18n:check` 通过（2129 keys）。

当前仍不能虚构为完成的发布证据：

1. 真实部署的 390×844 / 768×1024 / 1440×900 明暗主题人工走查记录。
2. 默认严格模式的 live 空态验收（现部署有 1 条已批准 public 案例）；该环境只能用
   `--allow-existing-public` 运行矩阵，报告会明确标记 `live_empty_state_verified=false`。
3. 真实环境漏斗埋点的 owner/运营验收，以及由发布方提供的 Lighthouse/截图归档。

自动化与只读线上快照（2026-08-09）：`/tmp/public-ux-audit-current.json` 覆盖 96 个组合，
serious/critical axe 记录为 0，缓存步骤切换 p75 为 13.82ms，暖导航 p75 为 383.45ms，
`performance_budget_failure_count=0`，报告 `passed=true`。本次运行使用已批准的 1 条公开案例，
所以 `live_empty_state_verified=false`，不能替代严格空态验收。生产数据库近 30 天已有 1101 条、
30 种 `public_ux_events` 记录，可用于后续漏斗验收；该快照没有 owner/运营签字，也不能替代发布方
的 Lighthouse、截图和人工走查证据。

因此 G1~G6 的代码与自动化部分已复核，但发布总闸仍需上述外部证据后才能将任务改为
`completed`。

## 20. 收尾复核（2026-08-10）

本次复核修正了一个实际影响移动端首屏的 Replay 问题：`#replay-results` 是一个高度超过视口
的主证据网格，不能套用 15% IntersectionObserver 阈值的整块懒显，否则 390×844 首屏只露出
小部分时整块保持透明。现在该容器立即可见；步骤详情错误态也改为共享 `ErrorState`，并补齐
中英文文案与回归测试。

当前门槛结果：前端 66 个 spec 文件 / 690 个测试通过，`type-check`、`i18n:check`、`build`
通过；修复后真实公开案例代理探针已在 390×844 首屏看到步骤结果标题。完整本地公开矩阵有
95 个页面记录、axe serious/critical=0；本地 warm p75 受 Vite 开发服务器影响而超过生产预算，
不能替代部署性能数据。生产只读报告仍显示 96 个组合、axe=0、warm p75=383.45ms，且无预算
失败；另有一组修复后本地人工截图覆盖 Showcase/Replay × 390/768/1440 × light/dark，12
张截图的 Replay 结果标题均可读。生产已有 1 条批准案例，所以严格 live empty-state 仍未验证。

仍需发布方补齐的证据没有改变：真实部署 390/768/1440 明暗主题人工走查归档、严格 live 空态、
真实漏斗埋点 owner/运营验收，以及 Lighthouse/截图归档。因此任务继续保持 `in_progress`，
不能仅凭本地矩阵把 G1~G6 标成发布完成。

## 21. P2 代码收尾复核（2026-08-10）

本次补齐了此前记录为延期的 P2 代码项，并为每一项保留自动化证据：

- Dashboard DB-10/11/12：庆祝弹窗改为真实文案/图片计数，提供帖子链接与“再来一篇”入口，
  replay 模式禁止实时工作流 CTA；时间线不再重复渲染总进度填充；标签重命名增加触控入口、
  44px 目标和键盘/溢出菜单路径。CelebrationModal、WorkflowTabBar、Dashboard 和
  WorkflowTimeline 组件/视图测试覆盖这些分支。
- Analytics AN-15、Evaluation EV-08/12/15/16、INF-05/11：MetricCard 保持非 live 数值，避免刷新时
  朗读整组指标；AnimatedCounter/动画计数经 reduced-motion JS 层降级。评估结果显示有效维度权重并明确排除 bias，
  `/evaluation/result` 返回账号解析后的 thresholds/weights；EvaluationView 的 scoped 颜色迁移
  到 Tailwind dark 变体；RQGM 手动结果在面板会话内按账号+笔记保留；RQGM/动画均尊重
  reduced-motion，TooltipHelper 用于维度与 Replay 阶段解释。旧 VersionCompare 分数标签和
  双语文案已保持一致。
- 回归门槛：66 个 spec 文件 / 690 个测试通过，`type-check`、`i18n:check`（2137 keys）、
  `ruff format --check backend tests`、`ruff check backend tests`、`mypy backend`、后端 27 个
  相关测试和 `build` 全部通过；`git diff --check` 通过，构建仅保留既有动态/静态导入提示。
- 曾尝试运行完整后端 `pytest -q`，输出 54 个测试进度后长时间无新增结果，为避免把挂起误报为
  通过而中断；因此本记录不宣称完整后端套件通过，相关范围测试仍是 27/27 通过。
- 2026-08-10 只读核对运行中的 `xhs-growth`：前端 `index-DMueUbgE.js`、
  `Dashboard-CXy8coBo.js`、`EvaluationView-CV6bM7A3.js` 与本地最终构建逐字节同哈希，并含本轮
  UX 标记；部署后重新创建的运行容器已包含当前提交的 `_score_config`/维度权重解析实现，
  并通过容器内 `/api/system/health` 复核 `database=postgres`、`memory_store=postgres`、
  `ripple_cas=ok`。因此当前提交的前后端代码已实际载入运行容器；仍不能仅凭此替代发布总闸的外部证据。
- `scripts/acceptance/public_ux_audit.py` 增加了移动抽屉点击的状态确认重试，并将动画稳定等待
  限定为非阻断的展示准备步骤。修正后在宿主网络/X server 上重跑全量公开页矩阵：96 个页面组合、
  axe serious/critical=0、功能失败=0、性能预算失败=0，报告 `passed=true`；warm p75 为
  428.95ms、缓存步骤切换 p75 为 22.45ms。该运行仍使用 `--allow-existing-public`，所以
  `live_empty_state_verified=false`，不能替代严格空态验收。

上述是代码与本地自动化收尾，不改变发布总闸：真实部署三档明暗主题人工走查、严格 live
empty-state、真实漏斗埋点 owner/运营验收以及发布方 Lighthouse/截图归档仍需外部执行。因此
Trellis 任务继续保持 `in_progress`，不得把外部证据缺口写成已完成。

## 22. 部署后复核（2026-08-10）

本次获得部署授权后，完成 PostgreSQL 备份、镜像构建、镜像导入和服务重建。部署后容器复核结果：

- `./scripts/deploy.sh start` 成功启动 `postgres-xhs`、`ripple-service`、`xhs-growth`。
- 容器内 `/api/system/health`：`database=postgres`、`memory_store=postgres`、`ripple_cas=ok`。
- 容器内确认 `backend/api/routes/evaluation.py` 含 `_score_config`，前端 dist 使用当前构建产物。
  运行使用 `--allow-existing-public`，所以 `live_empty_state_verified=false`。
 复跑报告为 `/tmp/public-ux-audit-live-20260810-postdeploy-rerun.json`，warm navigation p75=495.95ms、
 缓存步骤切换 p75=22.8ms；首次采样的 578.15ms 预算失败报告亦保留，未被覆盖。

部署已完成，但真实三档明暗主题人工走查、严格 live 空态、漏斗埋点 owner/运营验收及 Lighthouse/截图归档仍需发布方补齐。

## 23. 最终浏览器脚本复核（2026-08-10）

修正验收脚本等待 Showcase 数据的方式后，使用宿主 X server 重跑部署矩阵：报告
`/tmp/public-ux-audit-final.json` 的 `passed=true`，覆盖 8 个矩阵页面，axe
serious/critical=0，性能预算失败=0。该次明确允许当前部署已有的 1 条批准 public case，故
`live_empty_state_verified=false`；严格 private-by-default 仍需无批准案例的目标环境。

真实轻模型路由采样与 token/时延汇总已记录在
`docs/acceptance/llm-route-benchmark-2026-08-10.json`，不启动工作流，并由固定合成提示完成。
这补齐了 provider 实调证据，但不替代内容 owner 对 POLISH、MOCK_GEN、VIRAL_MATCHING
样本的人工质量复核。发布总闸仍只剩真实部署三档明暗主题人工归档、严格空态、漏斗埋点
owner/运营验收及 Lighthouse/截图归档，任务保持 `in_progress`。
