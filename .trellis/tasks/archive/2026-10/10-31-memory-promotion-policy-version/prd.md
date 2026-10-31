# Memory Promotion policy_version 来源（票 5aa / PRD §9 Q6）

## Goal

锁定 `decided_by="machine"` 时 `policy_version` 的权威来源，使审计能从账本行定位到可复算的策略快照。今天 `PromotionPolicy.policy_version` 默认字面量 `"v1"` 散落在 dataclass 字段上，没有单一出口、也没有「改阈值必须 bump」的成文契约。

## What I already know

* `PromotionPolicy.policy_version: str = "v1"`；`decide_promotion` 把该值写入 `PromotionDecision` → ledger / target provenance
* 人审行复用原 REVIEW 的 `policy_version`（不重新发明）
* TTL（票 5z）已有「单一常量表 + resolve」先例；Q6 应对齐同一形状
* 父 PRD §9 Q6：审计要能定位策略版本；来源需定（常量？配置文件？）

## Decisions (locked)

| Topic | Choice |
|-------|--------|
| 权威来源 | **Git 模块常量** `DEFAULT_PROMOTION_POLICY_VERSION`（与 `default_promotion_policy()`）— 不引入 env/远端配置；同二进制同版本，审计跟 commit |
| 出口 | 所有默认 `PromotionPolicy()` / `decide_promotion(..., policy=None)` 路径经工厂或常量，禁止另写 `"v1"` 魔法串 |
| Bump 规则 | 改变会影响机判决的字段（`min_samples` / `machine_promotable_classes` / `allowed_namespaces` 语义）时**必须** bump 常量；仅文档/注释改动不 bump |
| 人审 | 仍复用 REVIEW 行上的 `policy_version`（票 5y 不变） |

## Requirements

1. 抽出 `DEFAULT_PROMOTION_POLICY_VERSION` + `default_promotion_policy() -> PromotionPolicy`
2. `decide_promotion` 在 `policy is None` 时用工厂；dataclass 默认与常量一致
3. 单测：默认决策带出常量；monkeypatch/常量变更可观测；禁止散落字面量（可选 grep 测）
4. `docs/memory-promotion.md` 关闭 Q6；说明 bump 规则
5. Spec：directory / error-handling 或 quality 记一条 convention

## Acceptance Criteria

* [x] Q6 成文：Git 常量是 machine `policy_version` 唯一权威来源
* [x] 默认机判决的 `policy_version` 等于 `DEFAULT_PROMOTION_POLICY_VERSION`
* [x] docs / agent-os 开放问题列表去掉 Q6
* [x] 相关单测绿

## Out of Scope

* 语义近邻（Q3）、sample 冷却窗口（Q4）
* 远程/动态下发 policy、多租户不同版本
* 改 `min_samples` 数值本身（除非为接线所必需；本票默认保持 5）

## Technical Notes

* 父 PRD §9 Q6；对照 `promotion_ttl.py` 单一出口模式
* `backend/memory/promotion.py` `PromotionPolicy`
