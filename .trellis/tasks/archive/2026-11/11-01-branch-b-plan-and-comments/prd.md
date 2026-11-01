# docs: P4 分支 B 可选迁移方案 + 清理旧符号注释（票 5bl）

> 目标：把 P4 里"分支 B 未采用"的一句话，升级为**可执行的最小迁移方案**（前提已由
> 票 5bi 解除），并清理 backend 注释里对已删除符号 `run_publish` 的残留引用。
> 纯文档/注释，无行为变化。

## 1. 已核实的事实

| 事实 | 证据 |
|---|---|
| P4 采用分支 A（实现体在入口背后），分支 B 未采用 | `docs/publish-action-protocol.md` P4 段 |
| 分支 B 的前提"控制面 receipt 路径不承载六态账本"已被解除 | 票 5bi：`_publish_with_effect_ledger` |
| 主链幂等键与 intent 幂等键不同源（publish_id vs caller key） | `compute_publish_id` / `ActionIntent.idempotency_key` |
| backend 注释仍称 `run_publish`（符号已删除） | `_wf_actions.py:438/483/499`、`services/omp_bridge.py:1902` |

## 2. 交付

1. `docs/publish-action-protocol.md` 增补「P4 分支 B（未采用，可选后续）」：
   - 前提已解除的说明；
   - 5 步最小迁移方案（先落 CONFIRMED intent → 用 `execute_action` 替换执行段 →
     幂等键同源 → 先写测试 → 回滚开关）；
   - 未做原因（改变执行语义 + 牵动 `test_run_publish` 约 500 行假设，需拍板后立项）。
2. 清理注释：
   - `backend/api/routes/_wf_actions.py` 3 处 "run_publish" → 发布入口/attempt；
   - `backend/services/omp_bridge.py` 1 处 → publish attempt。
3. 顺带修正 P4 段里一处不精确表述（"除定义模块与入口模块外零调用" → "backend 中除
   入口模块外零调用"，与实际 AST 不变量一致）。

## 3. 验证

- `tests/unit/scripts` 98 passed（含 claim/锚点/citations）
- `ruff check` 绿
- 全量 pytest 结果见 notes（纯注释/文档改动，仍跑全量确认无意外）

## 4. 结果（2026-11-01）

- [x] 分支 B 方案写入文档（可被后来者直接执行为独立票）
- [x] 旧符号注释清零（`grep run_publish backend` 仅剩测试文件名/docstring 的历史表述）
- [x] 文档门禁 98 passed；全量见 notes

## 5. 不做什么

- 不实施分支 B（需产品/架构拍板）；不改任何运行时代码。
