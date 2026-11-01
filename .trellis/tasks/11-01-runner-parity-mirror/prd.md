# chore(ci): 本地 runner 镜像 CI 的 PG parity 复查（票 5bx）

> 5bw 的 runner 跑全量 pytest，但 CI 还多做一步：单独重跑
> `tests/integration/test_creator_agent_backend_parity.py`，并要求输出里出现 `passed`——
> 理由是"静默 skip 与通过无法区分"。本地没有 Postgres 时这条能力无法执行，但 runner
> 至少不能让摘要暗示已覆盖，并且一旦提供 URI 就要真的复查。

## 1. 已核实的事实

| 事实 | 证据 |
|---|---|
| CI 的 test 作业在 pytest 之后重跑 parity 模块并要求 ` passed` | `.github/workflows/ci.yml` 的 *Verify backend parity actually ran* |
| 本地无 Postgres（无监听端口），parity 只能 CI 覆盖 | 5bv/5bw 的复核记录 |
| 需要 Postgres 时用 `XHS_PG_PARITY_URI`（CI 用 service 容器） | CI env + `tests/integration/test_creator_agent_backend_parity.py` |

## 2. 决定（locked）

1. `job_tests(skip=False)`：先跑全量 pytest；FAIL 直接 FAIL。
2. 环境有 `XHS_PG_PARITY_URI`：单独重跑 parity 模块；退出码非 0 **或**输出不含 ` passed`
   → FAIL（对应 CI 的那条断言）。
3. 没有 URI：PASS，但摘要明确写 `Postgres parity skipped: XHS_PG_PARITY_URI unset; CI sets it`。
4. `--skip-tests` 仍直接 SKIP（不误报）。

## 3. 测试

- 无 URI → PASS 且摘要含 `Postgres parity skipped`；
- 有 URI → 第二次 `_run` 调用的是 parity 模块，PASS 且摘要含 `parity executed`；
- 有 URI 但 parity 输出 `1 skipped`（exit 0）→ **FAIL** 且摘要含 `did not execute`。

## 4. 结果（2026-11-01）

- [x] tests 作业镜像 CI 的 parity 复查
- [x] 新增 3 个单测；`tests/unit/scripts/test_ci_local.py` 8 passed
- [x] 全量结果见 notes

## 5. 不做什么

- 不尝试在本地拉起 Postgres（无容器运行时/凭据）；不改变 CI 配置；
- 不把 parity 变成必跑（没有 URI 时如实标注跳过）。
