# test: 加固 B3 执行段切换的 force/unknown/timeout 语义（票 5bu）

> B3（票 5bs）把"有 durable intent 的发布"切到 `CreatorAdvisor.execute_action`。
> 切换后三条最容易悄悄回归的语义没有直接用例：force 重试、unknown 结果、异常超时。
> 本票只加回归测试，不改实现。

## 1. 已核实的事实

| 事实 | 证据 |
|---|---|
| force 在主链是"一次性"，靠 `publish_options.force_publish` 消费 | `_run_publish_attempt` F3 |
| executor 收到 force 会新开 attempt（receipt attempt 级） | 票 5bq / `execute_action` |
| 执行器把 domain `unknown` 记为 FAILED receipt + `result["status"]="unknown"` | 票 5bn / `_publish_receipt_result` |
| 主链把 `unknown` 重新贴成 `publish_result_unknown` + `result_known=False` | `_submit_outcome_is_unknown` |
| 执行器 dispatcher 抛异常时不写 receipt（异常向上传播） | `_publish_with_effect_ledger` |

## 2. 测试（新增 3 个）

1. `test_a_forced_retry_re_executes_through_the_executor`
   - 第一次成功（receipt attempt=1）；`force_publish=True` 再跑一次；
   - 断言：Gateway 调 2 次、receipt 的 attempt 为 [1, 2]、都是 SUCCEEDED、
     `publish_options.force_publish` 被清成 False（一次性）。
2. `test_an_unknown_executor_outcome_keeps_the_mainline_semantics`
   - Gateway 返回 domain `status=unknown`；
   - 断言：`publish_result.status=unknown`、`error_type=publish_result_unknown`、
     `result_known=False`；receipt 为 FAILED 且 `result["status"]="unknown"`；
     主链账本 record 为 UNKNOWN（护栏保持 armed）。
3. `test_a_timeout_from_the_executor_is_unknown_and_writes_no_receipt`
   - Gateway 抛 `TimeoutError`；
   - 断言：`publish_result.status=unknown`、`result_known=False`、无 receipt、
     主链账本 record 为 UNKNOWN。

## 3. 结果（2026-11-01）

- [x] 三个用例单跑通过（45.98s）
- [x] 全量结果见 notes

## 4. 不做什么

- 不改实现（B3 已收口）；不改 claim 表；不动已有 63 个 run_publish 用例。
