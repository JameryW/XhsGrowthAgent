# CreativeMemory find_similar 失败即抛（票 5ah）

## Goal

与票 5ae–5ag 对齐：`_find_similar_style` 对 **durable** `find_style_by_tone_visual` 失败不再 `except` 吞掉后当「无相似」——否则 `deposit_style` 会在存储故障时错误地新建 uuid 风格行，破坏合并语义。父 PRD §10 / 5ag 仍登记 `find_similar` swallow 另开票。

## What I already know

* `_find_similar_style`：durable miss 后可选 store `asearch`；durable 失败目前 `logger.debug` + 继续 / 当 miss
* 唯一调用方：`deposit_style`（同 conn 事务路径）；`existing is None` → 新 `style_id`
* Durable 失败被当成 miss = 静默重复写入（比假空召回更糟）
* Store 检索已是 best-effort warn + `return None`（注释写明不得阻断 durable deposit）——与 5af/5ag 次级索引一致，保持

## Decisions (locked)

| Topic | Choice |
|-------|--------|
| Durable `find_style_by_tone_visual` 失败 | **上抛**（去掉 swallow；由 `deposit_style` 传播） |
| 真实无命中 | 仍返回 `None`（合法 miss，可新建） |
| Store `asearch` 失败 | **保持** warn + `None`（可选索引；不阻断已成功的 durable 路径意图） |
| 公开 API | 无新公开方法；仅修私有 helper |

## Requirements

1. `_find_similar_style`：去掉 durable 的 swallow；异常上抛
2. Store 分支不变（warn + None）
3. 单测：durable find 失败 → `deposit_style` raises；miss → 仍新建；store 失败 → 仍可走 durable miss/hit
4. Docstring / §10 / docs / error-handling scenario 划掉 find_similar 项

## Acceptance Criteria

* [x] durable find 失败上抛，不伪 miss
* [x] 真实 miss 仍 `None`；store 失败仍 best-effort
* [x] `deposit_style` 在 durable find 故障时不再静默新建
* [x] 测试绿；§10 find_similar 邻近风险关闭

## Out of Scope

* MemoryManager uuid4 keys
* Effect 对账增强（agent-os 行 5 P1）
* 改变 merge / tone+visual 相等判定

## Technical Notes

* `backend/memory/creative.py` `_find_similar_style`；`tests/unit/memory/test_creative_memory.py`
* Spec: `.trellis/spec/backend/error-handling.md`（接 5ag scenario）
