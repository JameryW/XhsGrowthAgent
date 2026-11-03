# docs(eval): 更正 judge 用例数为 13 并补计数器边界说明（票 5co）

> 机械核对文档声明：把评测方案里每个"X passed"与实际用例数逐一对照，发现 §6.9 写的是
> 12，实际是 13（5cm 加的 `used`/`max_calls` 边界用例没有计入，也没写进覆盖列表）。

## 1. 改动

| 位置 | 变化 |
|---|---|
| `docs/adaptive-harness-eval-plan.md` §6.9 | `12 passed` → `13 passed`；覆盖列表补上"`used` 负值/越界被拒绝且 `max_calls` 构造后不可改" |

其余计数核对结果（本轮实测，全部一致）：fixtures 21、gate 29、judge 13、plan_l3 15、
policy 9；`tests/unit/scripts` 总数 188 passed。

## 2. 同轮端到端验证（非文档）

`python scripts/ci_local.py` 完整跑通：`local CI parity: OK`
- PASS：lint、format（696 tracked .py）、mypy（264 files）、gates、tests（pytest 全量）
- SKIP（如实）：eval-gate（无 `.eval-fixtures/` 本地语料）、frontend（无 node_modules）

## 3. 不做什么

- 只修事实性计数，不新增评测行为、不改代码。
