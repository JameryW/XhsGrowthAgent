# P4 分支 B slice2：mainline intent 先于任何持久效果（票 5bo）

> 分支 B 方案第 1 步：「执行前先落 CONFIRMED `ActionIntent`（producer 已有，需从
> 账本 claim 之后提前到执行之前）」。本票只做顺序调整 + 顺序测试，不改 dispatch。

## 1. 已核实的事实

| 事实 | 证据 |
|---|---|
| 原顺序：material → PREPARED → ledger claim → intent | `backend/agents/publisher.py`（B1 前） |
| 方案要求 intent 先于执行/持久效果 | `docs/publish-action-protocol.md` 分支 B 第 1 步 |
| producer 按 `(account, publish_id)` 幂等 | `publish_intent.record_mainline_publish_intent` |
| 账本 claim 失败会在此之前返回 duplicate 结果 | `EffectLedger.begin` + `EffectBlockedError` 分支 |

## 2. 决定（locked）

1. `record_mainline_publish_intent` 移到 `publish_intent_material` 之后、`_write_publish_record`
   （PREPARED）与 `EffectLedger.begin` **之前**。
2. 语义不变：best-effort、幂等、拒绝/存储失败都不影响发布。
3. 顺序由测试钉住：让 `EffectLedger.begin` 抛 `RuntimeError`，intent 仍必须已存在
   （若 intent 仍在 claim 之后，该断言必然失败）。
4. 不改 mainline dispatch（B3 才切换）；不新增 HTTP 行为。

## 3. 要求

1. `backend/agents/publisher.py`：移动 producer 调用与注释，删除原"claim 后"重复块。
2. `tests/unit/agents/test_run_publish.py`：新增
   `test_the_mainline_intent_is_persisted_before_the_effect_claim`。
3. `docs/publish-action-protocol.md`：记录 B2 落地。
4. 验证：定向（含新测试）+ 全量 + ruff。

## 4. 结果（2026-11-01）

- [x] producer 前移，PREPARED/claim 之后不再重复写
- [x] 顺序测试通过（账本抛错仍读到 mainline intent）
- [x] 定向 313 passed（B1+B2 代码）、新测试单跑 passed、ruff 绿
- [x] 全量结果见 notes

## 5. 不做什么

- 不切换主链 dispatch（B3）；不改 ledger/producer 语义。
