# test: 钉住「一次发布只有一个账本 claim」+ 不变量文档收口（票 5by）

> 分支 B 收口时做了一个**关键但只写在注释里**的决定：executor 以
> `artifact_store=None` 构造，让主链的 `publish_id` 账本成为一次发布唯一的 claim。
> 若未来有人"补上" executor 的账本，两份 claim 在崩溃后可能给出不同答案
> （主链 CONFIRMED、executor 仍是 IN_FLIGHT），重试读到哪份取决于调用顺序。
> 本票用测试 + 文档不变量把这个决定钉死。

## 1. 已核实的事实

| 事实 | 证据 |
|---|---|
| 主链在 dispatch 前用 `publish_id` claim 自己的账本 | `_run_publish_attempt` |
| executor 账本命名空间是 `("publish", "intent_effects")`，主链是 `("publish", "idempotency")` | `publish_effect_id` / `PUBLISH_IDEMPOTENCY_NS` |
| B3 以 `artifact_store=None` 构造 executor（不重复 claim） | 票 5bs |
| `EffectLedger(store, ns).get(key)` 可读单条；`store.asearch(ns)` 可列命名空间 | `backend/state/effects.py`、InMemoryStore API |

## 2. 测试

`test_an_approved_publish_touches_only_the_mainline_ledger`：
1. 用审批决策跑一次 approved publish（走执行器路径）；
2. 断言主链账本 record 存在且为 **CONFIRMED**；
3. 断言 `("publish", "intent_effects")` 命名空间**为空**（executor 没有写第二份 claim）。

## 3. 文档

`docs/publish-action-protocol.md` 的「不变量」：
- 第 2 条改为分支 B 收口后的终态：有 intent 时唯一执行入口是 `execute_action`；无 intent
  的回退直调是显式例外（claim `mainline_direct_publish_invocations = 1`）；一次发布只有一个
  账本 claim，测试同时钉住主链 CONFIRMED 与 `intent_effects` 为空。
- 「不做 / 触发条件」里的迁移期条目标注为历史（P1/P2 约束，已随分支 B 收口失效）。

## 4. 结果（2026-11-01）

- [x] 用例单跑通过（12.06s）
- [x] 文档不变量更新
- [x] 全量结果见 notes

## 5. 不做什么

- 不改实现（B3 的 `artifact_store=None` 就是被钉住的决定）；不改 claim 表。
