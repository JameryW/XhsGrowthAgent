# Context trust_class 进入 rerank（票 5ad / P1-A 后续）

## Goal

让 Context Compiler 的确定性 rerank 消费 `ContextItem.trust_class`（P1-A 已落字段、诚实边界「尚未参与排序」）。Memory Promotion 已能产出 `internal_fact` / provenance，排序融合再不接上则字段只进可选标注、不进取舍。

## What I already know

* `rerank_items`：`priority` desc → `confidence * source_weights[source]` desc → recency desc；稳定排序
* `TrustClass`：`internal_fact` / `memory` / `external_document` / `model_generated` / `unspecified`
* Promotion 写入可带 `trust_class`；retrieval 透传；未知拼写回落命名空间默认
* info.md D6'：无 LLM rerank；P1b 基线钉渲染字节——改排序可能要刷新基线快照
* agent-os 行 6：✅ 已满足，排序融合留 P1 后续

## Decisions (locked)

| Topic | Choice |
|-------|--------|
| 融合方式 | 在有效置信度上再乘 **trust multiplier**（仍纯函数、确定性）：`effective = confidence * source_weight * trust_weight` |
| 乘数表 | 封闭常量 `TRUST_RERANK_WEIGHTS`：`internal_fact=1.0`，`memory=0.85`，`model_generated=0.7`，`external_document=0.55`，`unspecified=0.5`（相对序固定；数值可测） |
| `verified` | **本票不进排序**（生产者仍少）；仅 trust_class |
| 默认行为 | 始终应用乘数（无开关）；缺字段走 `UNSPECIFIED` 权重 |
| 基线 | 若 P1b / harness 快照因排序变字节 → **同 PR 刷新**并在描述写明 |

## Requirements

1. `rerank_items`（及 docs）接入 trust 乘数；导出权重常量
2. 单测：同 priority/confidence/source 时 `internal_fact` 排在 `external_document` 前；与 source_weights 可叠加
3. 跑 context baseline / 相关门禁；必要刷新快照
4. 更新 `docs/agent-os-upgrade-2026q4.md` §5.2 诚实边界；context 文档若有

## Acceptance Criteria

* [x] trust_class 影响 rerank 有效置信度（有单测）
* [x] 仍确定性、无 LLM
* [x] 基线门禁绿（含必要快照更新）
* [x] agent-os §5.2「trust 尚未进入 rerank」划掉

## Out of Scope

* `verified` / TTL 进排序
* LLM rerank、可学习权重
* 改 Memory Promotion 生产者

## Technical Notes

* `backend/context/compiler.py` `rerank_items`；`models.TrustClass`；`tests/unit/context/test_compiler.py`；baseline
