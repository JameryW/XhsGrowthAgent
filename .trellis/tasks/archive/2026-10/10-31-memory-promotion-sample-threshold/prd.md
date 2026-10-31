# Memory Promotion machine-promote 阈值（票 5ab / PRD §9 Q4）

## Goal

锁定机晋升的样本阈值与冷却策略，关闭 PRD §9 Q4。今天 `PromotionPolicy.min_samples=5` 是 dataclass 默认字面量，与 `CreativeMemory.MIN_SAMPLES` 的对齐只在注释里；冷却窗口未成文。

## What I already know

* `decide_promotion`：`sample_count < min_samples` 或 `measured_rate is None` → `REFUSE(insufficient_samples)`
* `CreativeMemory.MIN_SAMPLES = 5`；`promotion.py` 注释要求与 proposals Laplacian「多少实测算数」同向
* 票 5aa：改 `min_samples` 语义必须 bump `DEFAULT_PROMOTION_POLICY_VERSION`
* 父 PRD Q4：`sample_count >= 5` 是否够？要不要「最近 N 天」冷却？

## Decisions (locked)

| Topic | Choice |
|-------|--------|
| 样本阈值 | **保持 5** — 与 `CreativeMemory.MIN_SAMPLES` 对齐；抽出 `DEFAULT_PROMOTION_MIN_SAMPLES`，`PromotionPolicy` / `default_promotion_policy()` 使用它 |
| 冷却窗口 | **MVP 不做**（无 `cooldown_days`、不扫 ledger 时间）— 去重/supersede 已处理同键更新；冷却另开票并需 `ExistingEntry` 带 promote 时钟 |
| 对齐护栏 | 单测断言 `DEFAULT_PROMOTION_MIN_SAMPLES == CreativeMemory.MIN_SAMPLES`（漂移即失败） |

## Requirements

1. `DEFAULT_PROMOTION_MIN_SAMPLES = 5`；policy 默认与工厂经此常量
2. 测试：默认机判决仍在 sample_count=4 拒、=5 可过（既有覆盖可保留）；新增对齐断言
3. Docs：关闭 Q4；写明冷却 out of scope
4. Spec 一笔 convention（可并入 error-handling 5aa 节或 directory）

## Acceptance Criteria

* [ ] Q4 成文：阈值=5、无冷却
* [ ] 常量单一出口 + 与 CreativeMemory 对齐测试
* [ ] docs / agent-os 开放问题去掉 Q4
* [ ] 相关单测绿

## Out of Scope

* 语义近邻（Q3）
* 实现 cooldown / 改 `min_samples` 数值
* proposals `_DRAFT_MIN_SAMPLES=3`（草稿门槛，非晋升闸门）

## Technical Notes

* 父 PRD §9 Q4；`backend/memory/promotion.py`、`creative.py` `MIN_SAMPLES`
