# 优化前端交互体验（收尾 07-17 UX V3）

## Goal

收尾 `07-17-frontend-ux-optimization-v3` 的剩余项。用户 2026-08-03 确认：不新开一轮，接着做完。

## 现状核实（2026-08-03，代码证据）

### 已完成（不重做）

* SH-01~11、RP-01~10、DB-01~09、DB-15、AN-01~14/16/17、AN-18、EV-01~07、EV-10~11、EV-13~14、EV-17、INF-03~06、INF-08、INF-10（07-19 审计 + 后续核对）
* EvaluationSkeleton 已接入（EvaluationView.vue:29,833,917）
* DB-12 触控目标：tab 关闭钮已 min-w-[44px] min-h-11（WorkflowTabBar.vue:356）
* EV-16：VersionCompare avgEngagementRate 误用已无痕迹
* dark-explicit 迁移（08-02，~1400 处）

### 剩余缺口（本轮范围候选）

| # | 原编号 | 现状 | 证据 |
| --- | --- | --- | --- |
| 1 | INF-01 | 统一错误态未收敛：ErrorState 仅 Dashboard 用，Showcase/Replay/Analytics/Evaluation 各自手写 | grep importers 仅 Dashboard.vue |
| 2 | INF-02 | Showcase/WorkflowReplay 未接 skeletons 体系 | 两 view 无 Skeleton 引用 |
| 3 | INF-09 | CI 无前端质量门槛：ci.yml 前端 job 只有 `npm install + typecheck`，无 test:run / i18n:check；axe 0 critical 未接入 | ci.yml:81-83 |
| 4 | INF-11/EV-08 | TooltipHelper.vue 存在但 0 处引用；评估维度解释未用浮层 | grep 无 importer |
| 5 | DB-10 | CelebrationModal 已换真实产物计数，但 confetti 无 reduced-motion 守卫；仍有装饰 100% 格 | CelebrationModal.vue:100,139,183 |
| 6 | DB-13 | ContentCards 硬编码中文兜底 `t(...) \|\| '中文'` + blue-* 硬编码 | ContentCards.vue:622-627,422-427 |
| 7 | AN-15 | AnimatedCounter 无 reduced-motion 门；MetricCard aria-live 全量朗读 | AnimatedCounter.vue 无 reduced；MetricCard.vue:75 |
| 8 | EV-15 | 手动 RQGM 评估无"预计耗时/LLM 费用"提示 | grep 无 |
| 9 | EV-12 | EvaluationView 仍 scoped 硬编码 hex（但用 `html.dark .x` 成对写法，符合 docs 现行约定）→ 可降级为不改 | EvaluationView.vue:1069-1095 |
| 10 | DB-11 | CircularProgress/MiniProgress 仍在（VersionCompare:237 用 MiniProgress）；去重未做 | grep |

### 非代码项（发布前人工）

* 390/768/1440 三档明暗走查；部署后埋点上报验证（§17.2/17.4）

## Requirements（2026-08-03 用户确认：全选，10 项 + axe）

1. **INF-01** 泛化 ErrorState，Showcase/Replay/Analytics/Evaluation 四页替换手写错误卡，保留各页恢复语义（Replay 四类错误、Analytics 缓存提示条）
2. **INF-02** Showcase/WorkflowReplay 接 skeletons 体系
3. **INF-09** CI 前端门槛：`test:run` + `i18n:check` 进 ci.yml
4. **INF-11/EV-08** TooltipHelper 正式接入：Evaluation 维度解释 + Replay 阶段 tooltip
5. **DB-10** CelebrationModal confetti reduced-motion 守卫；去装饰 100% 格
6. **DB-11** 进度可视化去重（hero 总进度条 / CircularProgress 阶段指示 / MiniProgress 窄屏）
7. **DB-13** ContentCards 硬编码中文兜底、blue-* 硬编码清理
8. **AN-15** AnimatedCounter reduced-motion 门；MetricCard aria-live 收敛（刷新不朗读全部）
9. **EV-15** 手动 RQGM 评估加"预计 10-30 秒 / 产生 LLM 费用"提示
10. **EV-12** EvaluationView scoped hex → Tailwind + dark: 迁移
11. **axe** vitest + axe-core 公开页（Showcase/Replay）关键态 0 critical 接入 CI

## PR 划分

* PR1 公开页基建：INF-01 + INF-02
* PR2 页面打磨：DB-10/11/13、AN-15、EV-15、EV-12、INF-11/EV-08
* PR3 CI 质量门槛：test:run + i18n:check + axe-core

## Acceptance Criteria

* [ ] 上述 11 条全部落地
* [ ] `cd frontend && npm run type-check && npm run test:run && npm run build` 全绿
* [ ] i18n 双语同步（check-i18n.mjs）；新增事件不涉及内容文本
* [ ] axe 公开页 0 critical
* [ ] 遵守 docs/frontend-ux-optimization.md 红线（状态唯一来源、空态区分、不新增全局 dark 重映射）

## Definition of Done

* 每 PR 独立可合；新代码 Tailwind + dark: 变体；文案双语；触控 ≥44px

## Out of Scope (explicit)

* 07-17 已完成条目；后端 API 语义；视觉改版

## Decision (ADR-lite)

**Context**: 07-17 UX V3 完成约 90%，剩余 10 缺口 + CI/axe 门槛；后续 08-01/08-02 三轮已清掉大部分 P2。
**Decision**: 本任务收尾全部剩余项（用户全选），按 3 个 PR 交付；EV-12 虽已符合 docs 的 `html.dark` 成对写法约定，仍按原 PRD 迁 Tailwind dark: 以彻底消灭 scoped hex。
**Consequences**: axe 接入可能翻出既有对比度/语义问题，顺带修；超出本轮范围的记录延期。

## Technical Notes

* 07-17 PRD+审计：`.trellis/tasks/07-17-frontend-ux-optimization-v3/prd.md` §18
* CI：`.github/workflows/ci.yml` 前端 job 目前仅 typecheck
* 本机 build 需 swap（记忆 vite-build-swap-workaround）；vite build OOM 风险，本地以 type-check+test 为 gate
