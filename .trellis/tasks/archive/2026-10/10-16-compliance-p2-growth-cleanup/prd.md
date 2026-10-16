# P2：增长体验与合规收尾

## Goal

交付原评估全部 P2：发布后学习回流、垂类合规分级、G1–G5 签字文档看板、依赖/死代码清理。

## Decision (ADR-lite)

| Topic | Decision |
|-------|----------|
| 范围 | P2-1～P2-4 全部 |
| 交付 | 单 PR，内部 slice |
| G1–G5 | **Acceptance 文档看板**（刷新/结构化 `docs/acceptance/` 签字状态表；可选只读展示）；不代替真人签字 |
| 学习回流 | 默认最近 **N=5** 篇 analytics/弱标签表现 → Start 推荐；附 Evidence/outcome-learning 追溯链接 |

## Requirements

### Slice A — P2-1 学习回流
- 从账号最近 N=5 篇有表现的内容生成选题推荐（复用 outcome-learning / analytics / Evidence Graph 已有能力）。
- Start 创作页展示「基于最近 N 篇表现的推荐选题」，可点开追溯证据。
- 无足够样本时展示明确空态（不编造）。

### Slice B — P2-2 垂类合规分级
- 高风险垂类（医疗/金融/医美等）：叠更严 lexicon + 必需资质提示。
- Start/设置切换到高风险垂类时 UI 提示阈值已提升；与 P0 `HIGH_RISK_NICHES` / niche YAML 对齐并可扩展。

### Slice C — P2-3 G1–G5 文档看板
- 结构化签字状态表（基于 `docs/acceptance/signoff-request-2026-09-22.md`）：G1–G5（及文档中的 G6+ 若需一并列出）状态、负责人角色、结论占位。
- 可选：轻量只读 API 或 Settings「Acceptance」区块渲染同一 markdown/JSON 状态（非强制写库）。
- 明确：不能代替仓外签字。

### Slice D — P2-4 清理
- 扫残余无用依赖、死代码、过时注释路径；CI 全绿。
- 不回滚 P0/P1 安全默认。

## Acceptance Criteria

* [ ] Start 页展示基于最近 N=5 的推荐（或明确空态），可追溯证据
* [ ] 高风险垂类切换后阈值/资质提示可见；有单测
* [ ] `docs/acceptance` 签字看板状态表可用；可选只读 UI
* [ ] 清理后依赖减少或死代码标注移除；CI 全绿

## Definition of Done

* 测试 + lint/CI green
* Spec 更新：`compliance-p2` 或扩展现有 compliance specs
* 不引入假数据学习推荐

## Out of Scope

* 仓外真人签字完成本身
* 法务意见书
* 完整重做 outcome-learning 引擎（只接现有闭环到 Start UI）

## Open Questions

* （无阻塞项）

## Technical Notes

* `docs/outcome-learning.md` + `test_outcome_learning_claims.py`
* `docs/acceptance/signoff-request-2026-09-22.md`
* Start 创作路由 / frontend Start Creating view
* P0 niche lexicon + `HIGH_RISK_NICHES` / `compliance_policy`
