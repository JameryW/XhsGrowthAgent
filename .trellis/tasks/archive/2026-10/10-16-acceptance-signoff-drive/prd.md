# 推动 G1–G5 仓外签字收口（豁免追踪强化）

## Goal

在**维持 2026-09-22 风险豁免**的前提下，强化 G1–G8 追踪：看板状态标明 `waived_risk_accepted`、补齐复审日期与催办清单，Settings Acceptance 只读页跟随 JSON——**不改判任何门槛为「通过」**。

## Decision (ADR-lite)

| Topic | Decision |
|-------|----------|
| 签字结论 | **维持豁免**；不收集新签字、不写「通过」 |
| 产物 | 增强 `signoff-board.json` + `docs/acceptance/signoff-chase-checklist.md` |
| 状态语义 | gate `status` → `waived_risk_accepted`（或等价）；保留 waiver 块 |
| UI | Settings Acceptance 渲染新字段（next_review_at / 豁免语义） |

## Requirements

1. **`signoff-board.json`**
   - 每个 gate：`status=waived_risk_accepted`（或明确 waived）、`next_review_at`、`chase_action`（一句话待办）、证据路径保留。
   - 顶层 `waiver` 保留；可加 `next_global_review_at`。
   - `disclaimer` 重申：豁免 ≠ 通过；CI 绿不得冒充签字。
   - 同步更新 `signoff-request-2026-09-22.md` 签字表状态列（与 JSON 一致）。

2. **`signoff-chase-checklist.md`（新）**
   - 按角色（发布方 / 运营 / 产品 / release owner）分组的可复制催办文案。
   - 每门槛：看什么、现有证据、待确认问题、建议复审日。

3. **Settings Acceptance 面板**
   - 展示豁免状态与 `next_review_at`；不提供「一键通过」。

4. **测试**
   - `acceptance_signoff` loader / API 兼容新字段；禁止把 waived 显示成 passed。

## Acceptance Criteria

* [x] 看板 JSON 中 G1–G8 为豁免语义，非 passed；含 next_review_at
* [x] 催办清单文档存在且按角色可复制
* [x] 签字单 markdown 表与 JSON 状态一致
* [x] Settings 只读页反映豁免 + 复审日
* [x] 单测：waived ≠ passed；loader 不崩

## Defaults

* `next_review_at`：自今日起 **90 天**（可在 JSON 统一或按 gate 微调）
* 日期基准：实现日（2026-10-16 上下文）→ 约 `2027-01-14`

## Out of Scope

* 真收集签字 / 改判通过
* 自动化代替人工走查
* 法务意见书

## Open Questions

* （无阻塞项）

## Technical Notes

* `backend/services/acceptance_signoff.py`, Settings `AcceptanceSignoffPanel.vue`
* Spec: `.trellis/spec/backend/compliance-p2.md`（signoff board 一节可补一句豁免语义）
