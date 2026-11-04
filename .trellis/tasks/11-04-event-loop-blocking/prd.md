# fix(runtime): 事件循环阻塞——provider 首次导入与同步 DNS 导致 /status 12–58s（票 5cu）

> 目标完成后继续追查唯一的性能观察项：生产路径（Postgres）上 start 后 `/status` 偶发
> 12–58s。结论：**不是 Postgres/checkpoint 的问题**，是工作流节点在 async 路径里执行了
> 同步阻塞调用，把事件循环整个卡住，所有请求（含 `/status`、checkpoint 读写）被迫排队。

## 1. 诊断证据（逐步排除）

| 证据 | 结论 |
|---|---|
| `XHS_LATENCY_LOG=1` 结构化采样：`total_ms=34303`，其中 `aget_state_ms=34279`、`db_ms=7` | 慢在 `aget_state`，但 DB 侧不慢 |
| 直连 psycopg 查询同一线程的最新 checkpoint：0–16ms | Postgres 本身快；非 DB 锁/IO |
| checkpoint 行/blob 体积极小（3–4KB/线程） | 不是大对象写入 |
| 给 `AsyncPostgresSaver._cursor`/`aput`/`aget_tuple` 打点：`aput` 自身 11–22s，`cursor acquired after 11s` | 读者在等同一 saver 的读写互斥锁；锁被谁长时间占用才是根因 |
| 心跳看门狗（独立线程每 0.5s 检查）捕获 `LOOP STALLED 3.3s` + 全线程 traceback | **事件循环被同步代码阻塞** |
| traceback：`trend_scout → granted_scopes → load_credential → _bound_profile → get_account_cdp_endpoint → _resolve_cdp_host → socket.gethostbyname("host.containers.internal")`；另有 `_create_model → import langchain_anthropic` | Windows 上该主机名不存在时 DNS 走满超时（~12s）；首次 model 创建还会在循环内做重 import（数秒） |

## 2. 修复

| 位置 | 变化 |
|---|---|
| `backend/models/router.py` | 新增 `preload_model_providers()`：显式导入 langchain_openai/langchain_anthropic（幂等） |
| `backend/api/app.py` lifespan | 启动时 `await asyncio.to_thread(preload_model_providers)` |
| `backend/cli/main.py` `run` | 同样在 `asyncio.to_thread` 预加载后再进图 |
| `backend/db/accounts.py` | `_resolve_cdp_host` 加 `lru_cache`；`get_account_cdp_endpoint` 用 `await asyncio.to_thread(...)` 执行阻塞 DNS |
| `backend/agents/publisher.py` | 容器 CDP 探测抽成带缓存的 `_probe_container_cdp_endpoint()`；新增 `_resolve_cdp_endpoint_async()`（to_thread），发布路径改用它 |
| `backend/api/routes/free.py` | free 模式 CDP 解析改用异步包装 |
| 测试 | `tests/unit/db/test_accounts_cdp_offloop.py`（阻塞 sleep 在 thread 时 ticker 仍推进 + 缓存命中）、`tests/unit/models/test_preload_providers.py`（两个 SDK 已导入、幂等）、`tests/unit/agents/test_run_publish.py`（async 包装不阻塞循环） |

## 3. 实测对比（同一台机器、嵌入式 Postgres、真实 magpie 工作流）

| 指标 | 修复前 | 修复后 |
|---|---|---|
| `/status` 延迟（start 后连续 4 次） | 12.4s / 12.4s / 23.8s / 35.2s（另测到 58s） | **1.08s / 1.08s / 1.09s / 3.5s** |
| 看门狗 `LOOP STALLED` 次数 | 每次运行 2–3 次（每次 3–11s） | **0** |
| 单次 `aput` 最长 | 11–22s | **≤1.06s** |

## 4. 验证

- 三组聚焦回归测试；真实工作流 + Postgres 冒烟 28/28；全量（含 `XHS_PG_PARITY_URI`）见 journal；CI 见推送后 run。

## 5. 不做什么

- 不改 LangGraph 上游 saver 的全局 `asyncio.Lock` 设计（单 checkpointer 实例读写天然串行）；
- CDP 探测结果按进程缓存（负结果同样缓存）：Chrome 后启动需重启进程，与容器主机探测语义一致，已在 docstring 说明。
