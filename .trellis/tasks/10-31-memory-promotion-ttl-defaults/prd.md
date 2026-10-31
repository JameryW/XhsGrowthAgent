# Memory Promotion TTL 默认值（票 5z / PRD §9 Q2）

## Goal

锁定 Memory Promotion 各目标命名空间的 TTL 默认策略，并让观测/晋升路径经单一解析点写入 `ttl_seconds` / 计算 `ttl_expired`——今天候选一律 `ttl_seconds=None`，过期分支只在单测里可及，产品默认未成文。

## What I already know

* 父 PRD 已定：每条 promotion 可带 `ttl_seconds`；过期只标 stale，不自动删除、不自动重晋升
* 协议层 `decide_promotion` **不算时钟**：`SourceCheck.ttl_expired` 由调用方传入（保持纯函数）
* `candidate_from_observation` / hy 候选当前不设 `ttl_seconds`；写入 `strategy_notes` 时透传 `None`
* Context retrieval 已透传非负整数 `ttl_seconds`；负值视为无
* 机晋升目标目前只有 `strategy_notes`（plays/materials 未裁决）

## Decisions (locked)

| Topic | Choice |
|-------|--------|
| 默认 TTL | **全部 `null`（永不过期，只靠 supersede）** — 与现状行为一致；不为 strategy_notes / audience / insights 发明未校准的天数 |
| 解析入口 | 单一 `resolve_promotion_ttl(namespace) -> int \| None`（常量表）；观测与 hy 建候选时调用，禁止散落魔法数字 |
| 过期判定 | 调用方助手 `ttl_expired_for(candidate, *, now, observed_at)`：仅当 `ttl_seconds` 非空时用真实时钟；默认 null ⇒ 永远不标 expired |
| 非目标 ns | plays/materials 仍不进表；解析未知 ns → `None`（不抛），与「未裁决命名空间」一致 |

## Assumptions

* MVP = 成文契约 + 解析/判定助手 + 接到现有 candidate 构造；不引入 cron 扫 stale、不自动删
* 将来若要给某 ns 设天数，只改常量表 + 测试，不改协议

## Open Questions

* （无阻塞）产品日后若要非 null 默认，另开票改常量并刷新 docs

## Requirements

1. 文档：`docs/memory-promotion.md` 锁定 Q2；§10/§11 更新开放问题列表
2. 代码：`backend/memory/promotion_ttl.py`（或挂在 `promotion.py` 旁）提供 `resolve_promotion_ttl` + `ttl_expired_for`
3. `candidate_from_observation` / hy candidate 构造经 `resolve_promotion_ttl` 填 `ttl_seconds`
4. `source_check_from_observation`（及 hy 等价处）在有 ttl 时用助手填 `ttl_expired`
5. 单测：null 默认；若常量改为正数则过期/未过期分支；未知 ns → None
6. 不改 `decide_promotion` 纯函数契约

## Acceptance Criteria

* [ ] Q2 成文：全 ns 默认 null + supersede-only
* [ ] 候选构造路径经单一解析点（测试可 monkeypatch 常量验证接线）
* [ ] `ttl_seconds is None` ⇒ `ttl_expired_for` 恒 False
* [ ] docs / agent-os 开放问题列表去掉或划掉 Q2
* [ ] 相关单测绿

## Definition of Done

* 实现 + 测试 + lint；docs 更新；Trellis archive

## Out of Scope

* 自动扫 stale / 删除 / 重晋升
* plays/materials 目标 ns 裁决
* 语义近邻（Q3）、sample 冷却（Q4）、policy_version 来源（Q6）
* trust 进 rerank

## Technical Notes

* 父 PRD：`.trellis/tasks/archive/2026-10/10-21-memory-promotion-pipeline/prd.md` §3 过期行、§9 Q2
* `docs/memory-promotion.md` §10「不算 TTL」→ 改为「协议不算；调用方经 promotion_ttl 助手算」
