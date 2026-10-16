# P1：风控可观测、隐私与产品闭环

## Goal

在 P0 合规底线之上交付全部 P1：账号健康面板、抓取预算与脱敏、个保保留/删除导出、AI 内容标识、Auth Redis 持久化与文档对齐。

## Decision (ADR-lite)

| Topic | Decision |
|-------|----------|
| 范围 | P1-1～P1-5 全部；P2 排除 |
| 交付 | 单 PR，内部按 slice 提交 |
| Auth | Redis + TTL；不可用降级内存；日志标明 backend |
| 抓取超限 | 优先账号近期缓存；无缓存 → 明确错误 `scrape_budget_exhausted`（不造假数据） |

## Defaults (implement unless overridden)

| Item | Default |
|------|---------|
| Homefeed / search / comments 日上限（每账号） | 50 / 50 / 100（可 env/账号覆盖） |
| Audience / comments / DM / relationship 保留期 | 90 天 |
| AI 声明 | 发布确认默认勾选；回执字段 `ai_content_declared` |
| Token TTL | 与现有 session 过期策略对齐（或 24h 若无现成值） |

## Requirements

### Slice A — P1-1 账号健康面板
- Settings 完整展示：effective `get_cooldown_policy`、最近风险命中时间/原因、剩余封禁、SAFE_MODE、engagement pause。
- API 与 `db/risk_gates` 一致；接口/组件测试。

### Slice B — P1-2 抓取预算与脱敏
- 账号日预算计数（homefeed/search/comments）；超限 → 读缓存，否则 `scrape_budget_exhausted`。
- 他人昵称/ID 默认脱敏存储。

### Slice C — P1-3 个保保留与删除
- 可配置保留期 + 到期清理任务（评论/私信/Relationship Memory）。
- Audience Member 删除 + 导出 API；`docs/security.md` 数据清单。

### Slice D — P1-4 AI 生成内容标识
- 发布确认「含 AI 生成内容」默认勾选 → 回执。
- `de_ai_taste` 说明不暗示规避标识。

### Slice E — P1-5 Auth + 文档 + 冷却共享测试
- Token store：Redis 优先 / 内存降级；多实例 Redis 路径。
- 更新 `docs/security.md`（认证、CORS、token 后端）。
- 多实例冷却共享集成/单元测试（DB KV）。

## Acceptance Criteria

* [ ] 健康面板字段齐全且与 risk-gates API 一致（有测试）
* [ ] 抓取预算可配；超限缓存或 `scrape_budget_exhausted`；昵称/ID 脱敏
* [ ] 保留期 + 清理；Audience 删除/导出；security.md 数据清单
* [ ] AI 声明默认开并进回执；de_ai_taste 文案合规
* [ ] Redis token + 内存降级；security.md 对齐；冷却共享测试绿

## Definition of Done

* 相关单测/前端测通过；lint / CI green
* 默认偏安全；危险能力需显式配置
* Spec：必要时更新 `.trellis/spec/backend/compliance-baseline.md` 或新小节

## Out of Scope

* P2 全部；法务意见书；官方开放 API

## Open Questions

* （无阻塞项）

## Technical Notes

* Extend: `xhs_risk_gate` / `db/risk_gates` / `system.py` risk-gates / `XhsAccountsPanel`
* Auth: `backend/api/auth.py` + `REDIS_URI` from settings
* Publish receipt already has confirmer/source/time — add AI declaration field alongside
* Spec: `compliance-baseline.md`, `browser-automation-safety.md`, `docs/security.md`
