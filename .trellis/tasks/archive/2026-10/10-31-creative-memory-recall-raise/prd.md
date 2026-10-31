# CreativeMemory recall 失败即抛（票 5ag）

## Goal

与票 5ae / 5af 对齐：`recall_style` / `recall_plays` / `recall_materials` / `recall_benchmark` 对 **durable 读失败** 不再 `except Exception: warn + 当空`，避免把存储故障答成「没有记忆 / 冷启动默认」。父 PRD §10 在 5af 后仍登记「召回 swallow 另开票」。

## What I already know

* 四个 `recall_*` 各自把 durable `list_*` / `get_benchmark` 包在 `except Exception: logger.warning` 里，失败后继续走 store / 空结果 / `_default_styles()`
* Store `asearch` 是可选语义补充（与 calibrate 的 store lookup 同级），不是权威源
* `recall_style` 在**真实空库**时返回 `_default_styles()` 是冷启动契约（ADR-0006）；必须与 durable 失败严格区分
* `MemoryManager.recall_*` 已在票 5m 清零 `MEMORY_FALLBACKS`（读失败上抛）；CreativeMemory 应对齐 durable 面

## Decisions (locked)

| Topic | Choice |
|-------|--------|
| Durable 读失败 | **上抛**（去掉吞异常后伪空 / 伪冷启动） |
| 真实空结果 | 仍返回 `[]` / `None`；`recall_style` 仍可走 `_default_styles()` **仅当 durable 成功且无真实 style** |
| Store 语义检索失败 | **warn + 仅用 durable 结果继续**（可选索引；与 5af store lookup 一致） |
| `find_similar` | out of scope（内部辅助，非公开 recall 面） |

## Requirements

1. 四个 `recall_*`：去掉 durable 读失败的 swallow；durable 异常上抛
2. Store `asearch` 失败仍 warn，不阻断已拿到的 durable 行
3. 单测：mock durable list/get 失败 → raises；空库 → 现有空/默认行为；store 失败 → 仍返回 durable
4. 更新 docstring；§10 / docs / error-handling scenario 划掉 recall 项

## Acceptance Criteria

* [x] durable recall 读失败上抛，不返回假空 / 假冷启动默认
* [x] 真实空库行为不变（含 `recall_style` 冷默认）
* [x] store 检索失败 best-effort warn，不掩盖 durable
* [x] 测试绿；§10 recall 邻近风险关闭；error-handling 增 scenario

## Out of Scope

* `find_similar` swallow
* MemoryManager uuid4 keys
* Effect 对账增强（agent-os 行 5 P1）

## Technical Notes

* `backend/memory/creative.py` recall_*；`tests/unit/memory/test_creative_memory.py`
* Spec: `.trellis/spec/backend/error-handling.md`（接 5ae/5af scenario）
