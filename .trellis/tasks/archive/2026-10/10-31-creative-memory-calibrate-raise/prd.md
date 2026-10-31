# CreativeMemory calibrate 失败即抛（票 5af）

## Goal

与票 5ae 对齐：`calibrate` / `_calibrate_*` 对 **durable 读写失败** 不再 `except Exception: warn + return 0`，避免把写失败统计成「未更新」。父 PRD §10 在 5ae 后仍登记「召回 / calibrate 另开票」。

## What I already know

* `_calibrate_style` / `_calibrate_play` / `_calibrate_materials` 整段 try/except 吞掉异常后返回 0
* `_persist_*` 在 5ae 后 durable 失败已上抛；当前仍被 calibrate 外层吞掉
* 「找不到 ID」返回 0 是合法无操作，不是失败
* `calibrate` 用 gather 并行三命名空间；一命名空间 durable 失败 → 整次 calibrate 失败（诚实）

## Decisions (locked)

| Topic | Choice |
|-------|--------|
| Durable 失败 | **上抛**（去掉吞异常后伪 0） |
| 未找到记录 | 仍返回 0（非异常） |
| Store 次级 lookup / dual-write | dual-write 仍 best-effort（经 `_persist_*`）；lookup 仅在 durable miss 时尝试，lookup 抛错可上抛或视为 miss——**durable get 抛错上抛**；store aget 抛错 → warn + 当 miss（可选索引） |
| 召回 swallow | 仍 out of scope |

## Requirements

1. `_calibrate_style` / `_calibrate_play` / `_update_one`：去掉吞 durable 失败的 except
2. 单测：mock durable persist/get 失败 → calibrate raises；missing id → 0
3. 更新 docstring（不再写 swallow + log）
4. 更新 §10 / docs 划掉 calibrate 项

## Acceptance Criteria

* [x] durable calibrate 写/读失败上抛，不返回假 0
* [x] 缺失 ID 仍 0
* [x] dual-write best-effort 不变
* [x] 测试绿；§10 calibrate 邻近风险关闭

## Out of Scope

* `recall_*` 吞异常
* MemoryManager uuid4 keys

## Technical Notes

* `backend/memory/creative.py` calibrate helpers；`tests/unit/memory/test_creative_memory.py`
