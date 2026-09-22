# 发布总闸签字催办单 — 2026-09-22

覆盖 Trellis 任务 `07-17-frontend-ux-optimization-v3` 与 `08-05-next-optimization-target`
刻意保持 `in_progress` 的全部仓外门槛。代码与本地/只读证据已于 2026-08-10 前补齐
并于 2026-09-22 在当前主干复验全绿（前端 775/775、type-check、i18n 2317 keys、
后端 upsert 相关 54 通过）；以下事项只能由对应角色确认，任何本地测试都不能代替。

签字方式：在本文件末尾签字表留名 + 日期 + 结论（通过 / 有条件通过 + 条件 / 不通过 + 理由）。
集齐后由执行人归档两任务。

## 门槛清单

### G1 三档明暗主题人工走查（07-17）
- 看什么：已部署 `xhs-growth` 的公开 Showcase / Replay / Start Creating / Analytics，
  390×844、768×1024、1440×900 三档 × 明暗两主题，人工走查无错位、无遮挡、无不可读。
- 现有证据（只读，非代替）：`docs/acceptance/public-ux-screenshot-archive-2026-08-10.json`
 （18 条记录，三档×双主题× live 空态/fixture 两面，全过横向溢出检查）。
- 待确认人：release owner / 发布方。结论：走查通过，或列出需返工项。

### G2 严格 live 空态（07-17）
- 看什么：无批准 public case 的目标环境上，公开页严格 private-by-default
  （`live_empty_state_verified=true`）。
- 现状：2026-08-10 部署含 1 条已批准 case，所有复跑均为
  `--allow-existing-public`，`live_empty_state_verified=false`（诚实记录，非失败）。
- 待确认人：发布方（提供目标环境并执行严格空态验收，或书面接受当前“1 条已批准 case”
  为正式状态并关闭本门槛）。

### G3/G7 真实漏斗埋点验收（07-17 + 08-05 共用）
- 看什么：线上 `public_ux_events` 漏斗埋点口径（事件名、字段、采样率）与运营报表对得上。
- 现有证据：2026-08-09 数据库有近 30 天 1101 条 `public_ux_events`（仅证明有数据，
  不证明口径正确）。
- 待确认人：运营（埋点 owner）。结论：口径接受，或给出修正清单。

### G4 发布方 Lighthouse / 截图归档验收（07-17）
- 看什么：`docs/acceptance/lighthouse-2026-08-10.json`
 （mobile performance 0.86 / a11y 1.0 / best-practices 1.0；
  desktop 三项 1.0；隔离空态目标，非公网 URL）与 G1 的截图归档。
- 待确认人：发布方。结论：接受为发布基线，或指定公网 URL 重跑。

### G5 方向 1 before/after 产品复核（08-05）
- 看什么：`docs/acceptance/status-polling-before-after-2026-08-10.json`
 （重建生产容器对照：旧版 50 次轮询 50 次 DB UPDATE，新版 0 次；延迟 p50/p95
  基本无差，收益结论仅限“省掉 UPDATE/row lock”，未冒充延迟收益）。
- 待确认人：产品。若发布流程要求“历史线上日志”而非“可复现重建容器”，请书面确认
  本对照可接受，或提出补采方案。

### G6 轻模型路由样本质量评审（08-05）
- 看什么：`docs/acceptance/llm-route-benchmark-2026-08-10.json`
 （12 次真实 provider 调用：POLISH 快 38%、MOCK_GEN 快 60%、VIRAL_MATCHING 快 76%，
  结构化有效率未降；但 `quality_proxy` 明确只是“JSON 有效”，**不是人工内容评审**；
  且 POLISH 输出更长，按成本表估算该样本成本未降）。
- 待确认人：产品/内容 owner。需决策：① 三个路由样本质量可接受；
  ② POLISH 是否进一步收紧输出预算；③ 不接受则回滚对应路由。

### G8 单窗口 runtime baseline 的 SLO 效力（08-05）
- 看什么：`docs/acceptance/production-runtime-baseline-2026-08-10.json`
 （单窗口：status/list/账号汇总/健康各 50–100 次全 200，p95 2–7ms；
  含 1 次瞬态 Ripple 健康检查 ReadTimeout 已恢复；声明非长期 SLO）。
- 待确认人：release owner。结论：接受为正式 SLO 基线，或指定延长期限/指标后重采。

## 签字表

| 门槛 | 签字人 | 日期 | 结论 |
|---|---|---|---|
| G1 三档走查 | | | |
| G2 严格空态 | | | |
| G3/G7 漏斗埋点 | | | |
| G4 Lighthouse/截图 | | | |
| G5 方向1对照 | | | |
| G6 路由样本质量 | | | |
| G8 baseline 效力 | | | |

## 不接受的关闭方式（重申）

- 用本地测试、健康检查或复验全绿冒充以上任一签字。
- 把“子票 6/6 全绿”“复验全绿”改判为任务 completed。
- 无批准案例环境的严格空态结论，除非真在无批准案例环境跑过。

## 豁免关闭记录 — 2026-09-22

仓库 owner 明确指示"不用签字，直接继续"，即豁免 G1-G8 的签字要求，
接受残留风险关闭两任务。**这不是"门槛通过"，是风险接受**，签字表留空即为证据：

- G2 严格空态从未在无批准案例环境验证（live_empty_state_verified=false 仍为当前事实）。
- G6 路由样本质量未经人工内容评审；POLISH 输出预算未收紧（成本未降是已知事实）。
- G8 单窗口 baseline 未获 SLO 效力；长期可靠性无基线。
- G1/G4 未获发布方人工走查与公网 Lighthouse 确认。

后续若线上因此出问题，从本记录回溯，不得 reinterpret 为"当时已验收通过"。
