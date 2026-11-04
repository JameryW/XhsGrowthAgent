# fix(runtime): dev SQLite checkpointer 未关闭导致进程退出挂起 + serve 单测真实起服务器（票 5cv）

> 目标完成后继续处理最后一个"本地环境观察项"：pytest 打印 summary 后进程不退出。

## 1. 反馈回路（先可判红）

`python .eval-tmp/pytest_exit_loop.py tests/unit/cli/test_main.py 3`：跑子集 → 看到 summary 后
15s 内进程是否退出；未退出即 HANG，并用 py-spy dump（失败后改进程内 wrapper）抓线程栈。

- 修复前：**0/3 clean exit**（22 passed 后必挂）
- 修复后：**3/3 clean exit**（23 passed 后正常退出）

进程内 wrapper 在 `pytest.main` 返回后枚举线程：

```
ALIVE_THREADS=1
THREAD name='Thread-13 (_connection_worker_thread)' daemon=False
  aiosqlite/core.py:59 _connection_worker_thread -> future, function = tx.get()
```

二分定位到 `TestCliServe`：`serve` 单测只 patch 了 `uvicorn.run`，但新实现走
`_serve_uvicorn`（Windows SelectorEventLoop），所以每个 serve 测试都**真的启动了服务器**；
应用 lifespan 在 SQLite 回退模式用 `compile_graph_dev()` 编译 dev graph，而 **shutdown 清理只
关闭 Prod 的 store/checkpoint pool，从不关闭 dev graph 的 aiosqlite 连接**。aiosqlite 的
`_connection_worker_thread` 是非守护线程 → 解释器退出时无限等待它。

## 2. 修复

| 位置 | 变化 |
|---|---|
| `backend/api/app.py` | 新增 `_close_dev_sqlite_checkpointer(graph)`：调用 `backend.graph.builder.close_dev_graph`（该 helper 已存在，之前名字记错导致第一次修复被 `contextlib.suppress` 静默吞掉）；lifespan 清理阶段在关闭 prod pool 前调用它 |
| `tests/unit/cli/test_main.py` | serve 单测改为 patch `backend.cli.main._serve_uvicorn`（不再真实起服务器），并新增 `--reload` 走 `uvicorn.run(reload=True)` 的测试 |
| `tests/unit/api/test_app_dev_sqlite_cleanup.py` | 新增 3 个单测：关闭连接并置 `_sqlite_conn=None`、`None` graph 为 no-op、close 抛错被吞 |
| `CLAUDE.md` | Testing 段补充：本地 SQLite dev graph 必须经 `dev_graph()`/关闭 helper；再出现 summary 后挂起先查未关闭的 aiosqlite 连接 |

## 3. 验证

- 反馈回路：CLI 子集 0/3 → 3/3 clean exit
- 全量 pytest（无 PG）：4963 passed / 11 skipped / 0 failed，且**进程正常退出**（此前每次都要 kill）
- 新增 cleanup 单测 3 passed；serve 测试由 10.5s/个 降至秒级（不再起真实服务器）

## 4. 说明

- 生产（Postgres）路径本就关闭 store/checkpoint pool，不受影响；此修复针对本地/开发 SQLite
  回退与短生命周期进程（pytest、`serve` 重启、CLI 脚本）。
- 第一次修复尝试里我引用了不存在的 `close_sqlite_checkpointer`，被 `contextlib.suppress(Exception)`
  静默吞掉；新单测用真实 `close_dev_graph` 行为把这个错误钉住（close 必须被 await、属性置 None）。
