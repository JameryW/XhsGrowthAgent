# CreativeMemory deposit 失败即抛（票 5ae）

## Goal

消除 `CreativeMemory.deposit_*` 对 **durable 写失败** 的 `except Exception: logger.warning` 吞异常——与仓内「失败不是数据」冲突；调用方把空返回当成功，晋升/观测会建立在假写入上。Memory Promotion 父 PRD §10 已登记为邻近风险、另开票。

## What I already know

* `deposit_style` / `deposit_play` / `deposit_material` / `deposit_benchmark` 外层整段 try/except 吞掉一切异常
* `_sync_*_store` / dual-write 已有「durable ok → store warn」模式（正确）
* 测试 `test_deposit_*_silent_on_exception` 钉住了错误契约
* 召回路径的 swallow 本票**不动**（读降级另议）

## Decisions (locked)

| Topic | Choice |
|-------|--------|
| Durable 失败 | **上抛**（去掉外层吞异常）；调用方必须处理 |
| Store dual-write | **保持 best-effort warn**（语义索引可选；durable 已成功） |
| 召回 swallow | **Out of scope** |
| calibrate swallow | **Out of scope**（可另票） |

## Requirements

1. 四个 `deposit_*`：durable 路径失败传播；仅 dual-write 保留 warn
2. 更新/删除 `*_silent_on_exception` 测试 → 断言 raise
3. 扫调用方（creator_stats gather 等）：失败应可见（允许 gather return_exceptions 或上抛——选与现有 resilience 契约一致的最小改动）
4. Docs：父 PRD §10 / memory 相关诚实边界更新

## Acceptance Criteria

* [x] durable deposit 失败不再被静默吞掉
* [x] dual-write 失败仍不回滚 durable（warn）
* [x] 单测更新；相关调用方测试绿
* [x] §10 邻近风险该项划掉或指向本票

## Out of Scope

* recall_* / calibrate 吞异常
* 改 MemoryManager uuid4 key 策略

## Technical Notes

* `backend/memory/creative.py`；`tests/unit/memory/test_creative_memory.py`；creator_stats resilience
