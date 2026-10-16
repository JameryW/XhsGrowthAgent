# Acceptance 签字催办清单（豁免追踪）

> **目的**：在维持 2026-09-22 **风险豁免**的前提下，按角色催办复审。  
> **不是**今日收集「通过」签字；`waived_risk_accepted` ≠ passed。  
> 机器可读状态：[`signoff-board.json`](./signoff-board.json)。签字单：[`signoff-request-2026-09-22.md`](./signoff-request-2026-09-22.md)。  
> 全局建议复审日：`2027-01-14`（自 2026-10-16 起约 90 天）。

---

## 发布方（含 G2 / G4；G1 可与 release owner 协同）

### G2 — 严格 live 空态

| 项 | 内容 |
|---|---|
| 看什么 | 无批准 public case 环境上 `live_empty_state_verified=true` |
| 现有证据 | 无严格空态证据；现状 `live_empty_state_verified=false`（含 1 条已批准 case） |
| 待确认 | 提供目标环境并跑严格空态，**或**书面接受「1 条已批准 case」为正式状态 |
| 建议复审 | 2027-01-14 |
| 状态 | `waived_risk_accepted`（非通过） |

**可复制催办：**

```
【催办 G2 严格 live 空态 · 豁免复审】
当前状态：waived_risk_accepted（2026-09-22 风险接受，不是通过）。
请确认：① 提供无批准 case 环境并验收严格空态；或 ② 书面接受现有「1 条已批准 case」状态。
证据缺口：live_empty_state_verified=false。建议复审日：2027-01-14。
说明：本次催办是豁免追踪复审，不是要求今日改判「通过」。
```

### G4 — Lighthouse / 截图归档

| 项 | 内容 |
|---|---|
| 看什么 | 隔离环境 Lighthouse + 截图归档是否可作为发布基线 |
| 现有证据 | `docs/acceptance/lighthouse-2026-08-10.json`；`docs/acceptance/public-ux-screenshot-archive-2026-08-10.json` |
| 待确认 | 接受为发布基线，或指定公网 URL 重跑 |
| 建议复审 | 2027-01-14 |
| 状态 | `waived_risk_accepted`（非通过） |

**可复制催办：**

```
【催办 G4 Lighthouse/截图 · 豁免复审】
当前状态：waived_risk_accepted（风险接受 ≠ 通过）。
请确认：① 接受 2026-08-10 隔离 Lighthouse/截图为基线；或 ② 给出公网 URL 要求重跑。
证据：docs/acceptance/lighthouse-2026-08-10.json、public-ux-screenshot-archive-2026-08-10.json。
建议复审日：2027-01-14。本次不收集「通过」签字，仅复审豁免是否续期。
```

---

## 运营（埋点 owner）

### G3 / G7 — 真实漏斗埋点验收

| 项 | 内容 |
|---|---|
| 看什么 | 线上 `public_ux_events` 漏斗口径（事件名、字段、采样率）与运营报表是否一致 |
| 现有证据 | 仅有事件量记录（有数据 ≠ 口径正确） |
| 待确认 | 口径接受，或给出修正清单 |
| 建议复审 | 2027-01-14 |
| 状态 | `waived_risk_accepted`（非通过） |

**可复制催办：**

```
【催办 G3/G7 漏斗埋点 · 豁免复审】
当前状态：waived_risk_accepted（风险接受 ≠ 通过）。
请确认 public_ux_events 漏斗口径与运营报表一致，或给出修正清单。
注意：历史上有事件量不代表口径已验收。建议复审日：2027-01-14。
本次催办维持风险接受追踪，不要求今日改判通过。
```

---

## 产品（含内容 owner）

### G5 — 方向 1 before/after 产品复核

| 项 | 内容 |
|---|---|
| 看什么 | 重建生产容器对照：旧版轮询写库 vs 新版 0 次 UPDATE |
| 现有证据 | `docs/acceptance/status-polling-before-after-2026-08-10.json` |
| 待确认 | 接受「可复现重建容器」对照，或要求补采历史线上日志 |
| 建议复审 | 2027-01-14 |
| 状态 | `waived_risk_accepted`（非通过） |

**可复制催办：**

```
【催办 G5 方向1 before/after · 豁免复审】
当前状态：waived_risk_accepted（风险接受 ≠ 通过）。
请确认：重建容器对照（status-polling-before-after-2026-08-10.json）是否可接受；
若流程要求历史线上日志，请提出补采方案。建议复审日：2027-01-14。
```

### G6 — 轻模型路由样本质量评审

| 项 | 内容 |
|---|---|
| 看什么 | POLISH / MOCK_GEN / VIRAL_MATCHING 真实采样质量；POLISH 成本是否可接受 |
| 现有证据 | `docs/acceptance/llm-route-benchmark-2026-08-10.json`（quality_proxy=JSON 有效，非人工评审） |
| 待确认 | ① 样本质量可接受；② POLISH 是否收紧输出预算；③ 不接受则回滚路由 |
| 建议复审 | 2027-01-14 |
| 状态 | `waived_risk_accepted`（非通过） |

**可复制催办：**

```
【催办 G6 路由样本质量 · 豁免复审】
当前状态：waived_risk_accepted（风险接受 ≠ 通过）。
请产品/内容 owner：① 评审三路由样本质量；② 决定 POLISH 是否收紧输出预算；③ 不接受则指定回滚。
证据：docs/acceptance/llm-route-benchmark-2026-08-10.json（quality_proxy 不是人工内容评审）。
建议复审日：2027-01-14。本次不改判「通过」。
```

---

## release owner

### G1 — 三档明暗主题人工走查

| 项 | 内容 |
|---|---|
| 看什么 | 已部署公开页 390×844 / 768×1024 / 1440×900 × 明暗主题人工走查 |
| 现有证据 | `docs/acceptance/public-ux-screenshot-archive-2026-08-10.json`（只读归档，非代替走查） |
| 待确认 | 走查通过并签字，或列出返工项，或书面续豁免 |
| 建议复审 | 2027-01-14 |
| 状态 | `waived_risk_accepted`（非通过） |

**可复制催办：**

```
【催办 G1 三档双主题走查 · 豁免复审】
当前状态：waived_risk_accepted（风险接受 ≠ 通过）。
请 release owner / 发布方：完成三档×双主题人工走查并签字，或列出返工项，或确认续豁免至下一复审日。
只读证据：public-ux-screenshot-archive-2026-08-10.json（不能代替走查）。建议复审日：2027-01-14。
```

### G8 — 单窗口 runtime baseline 的 SLO 效力

| 项 | 内容 |
|---|---|
| 看什么 | 单窗口 status/list/账号汇总/健康 baseline 是否升格为正式 SLO |
| 现有证据 | `docs/acceptance/production-runtime-baseline-2026-08-10.json`（声明非长期 SLO） |
| 待确认 | 接受为正式 SLO，或指定延长期限/指标后重采 |
| 建议复审 | 2027-01-14 |
| 状态 | `waived_risk_accepted`（非通过） |

**可复制催办：**

```
【催办 G8 runtime baseline SLO · 豁免复审】
当前状态：waived_risk_accepted（风险接受 ≠ 通过）。
请 release owner：接受 production-runtime-baseline-2026-08-10.json 为正式 SLO，
或指定延长期限/指标后重采。建议复审日：2027-01-14。本次催办不冒充签字通过。
```

---

## 不接受的关闭方式（重申）

- 用本地测试、健康检查或 CI 全绿把 `waived_risk_accepted` 改成 `passed` / 「通过」。
- 在 Settings Acceptance 提供「一键通过」。
- 无批准案例环境的严格空态结论，除非真在无批准案例环境跑过。
