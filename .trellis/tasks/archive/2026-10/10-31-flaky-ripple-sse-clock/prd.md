# 稳定 ripple SSE 时间回退测试的时钟依赖（票 5aq）

> 来源：全量 pytest 的一次真实失败（本会话门禁 Run A）。`test_stale_sse_zero_progress_falls_back_to_time_estimate`
> 在机器快速/负载情况下 3 次 emit 的 `elapsed` 全为 0.0，`progress >= 0.01` 断言不成立；
> 单跑通过。这是“用真实时钟推断程序行为”的典型 flake，也正是
> `.trellis/spec/backend/quality-guidelines.md` §10.2.5 明确禁止的模式。

## 1. 目标

让该测试**不依赖真实时间推进**：注入确定性步进时钟，使 `elapsed` 与 `progress` 由测试控制，
从而在任意机器速度下都稳定通过（并保留它真正要断言的语义：SSE 过期后走时间回退）。

## 2. 已核实的事实

| 事实 | 证据 |
|---|---|
| 失败形态：`non_final` 里没有 `progress >= 0.01`，3 次 emit 的 elapsed 全为 0.0 | 本会话全量 pytest 输出 |
| 原因：`wait_for_completion` 用 `_time.monotonic()` 计算 `elapsed`；`poll_interval=0.01` 而 machine 在 3 次 mock 轮询里推进 <10ms | `backend/services/ripple_service.py` 的 `start_time/elapsed` 与 `time-based estimate` 分支 |
| `_time` 在模块内**只**被用于 `monotonic()`（4 处） | grep `_time.` 结果 |
| 仓库规范禁止用时钟样本推断行为 | `.trellis/spec/backend/quality-guidelines.md` §10.2.5 |

## 3. 决定（locked）

- 测试内注入 `_SteppingClock`（每次 `monotonic()` 推进固定步长，测试同时可读 `now`），
  用 `patch.object(ripple_service, "_time", clock)` 替换模块的时间源。
- `sse_stale_zero` 里的 `last_update_at` 用 `clock.now - SSE_STALE_THRESHOLD - 10`，保持“过期”
  语义与实现无关。
- 断言改为确定性：非终态 emit 恰好 3 条（mock 给 3 个 running + 1 个 completed）、
  时间回退分支成立（至少一条 `progress >= 0.01`）、且 progress 单调不减。
- 生产代码只做一个**等价重构**：仓库把 `import time as _time` 写在两个函数内部（非模块级），
  所以 `_time` 不是可替换的模块 seam。把两处函数内导入提升到模块顶部（`backend/services/ripple_service.py`），
  语义与导入时机不变，模块级别名从此可被测试替换。

## 4. 要求

1. `backend/services/ripple_service.py`：`import time as _time` 提升到模块级，删除两处函数内导入（等价重构）。
2. `tests/unit/services/test_ripple_service.py`：只改该测试（加 `_SteppingClock`、patch 模块 `_time`、
   断言确定性化）。
3. 连跑 ≥20 次全绿；相邻 ripple 用例不受影响。
4. `ruff check` / `ruff format --check` 绿。

## 5. 验收

- [x] 该用例 20/20 通过，且断言不再依赖 wall clock
- [x] 相邻 ripple 测试全绿（`tests/unit/services` 933 passed；98 个 `tmp_path` ERROR 为沙箱环境性，零 failed）
- [x] 生产代码仅做等价提升（`time` 别名到模块级），行为不变；ruff / format 绿
- [x] 突变自检：让 `monotonic()` 恒返回同一值（elapsed 恒 0）→ 时间回退断言变红；恢复后绿

## 6. 不做什么

- 不改 `wait_for_completion` 的行为或 `poll_interval` 默认值。
- 不引入 `freezegun` 等新依赖（用最小 shim）。
- 不动其它 `import time`（`get_health` 里的局部 `time.time()` 与本测试无关）。
