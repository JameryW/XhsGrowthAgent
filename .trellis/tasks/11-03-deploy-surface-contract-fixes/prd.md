# fix(api/cli): /api 404 信封、缺失静态资产 404、CLI 未知线程退出与连接泄漏（票 5cr）

> 继续"本地部署后全面功能测试"的部署面：静态资源、OpenAPI、错误语义、CLI 负路径。
> 又发现 4 个真问题（其中 1 个会让 CLI 进程挂死），全部修复并固化为冒烟检查。

## 1. 发现与修复

| # | 问题（实测） | 修复 |
|---|---|---|
| 1 | `GET /api/does-not-exist` → **404 空 body、无 Content-Type**。前端 `client.ts` 会把空 body 归为 `NETWORK_ERROR`，路由/代理配错被误报成网络故障 | 注册 `StarletteHTTPException` 处理器：`/api/*` 的 404 返回 ApiResponse 信封（新错误码 `ERROR_ROUTE_NOT_FOUND`）；非 API 保持默认 `{"detail": …}`；405 仍是 405 |
| 2 | SPA 兜底对缺失的 `/assets/*` **回退 index.html（200 HTML）**，浏览器把 HTML 当 JS 执行，报错无从定位 | `assets/*` 文件不存在时抛 404，不回退 |
| 3 | CLI `status` / `logs` / `resume` 对未知线程显示 `✅ completed` / 空日志，**exit 0**——拼错 thread_id 或连错 checkpointer 看起来像正常完成 | 新增 `_require_existing_thread`：空快照 → 明确"线程不存在"面板 + **exit 1** |
| 4 | `logs` / `resume` 用 `compile_graph_dev()` 后不关闭，aiosqlite worker 线程让进程在解释器退出时**挂死**（faulthandler 证实卡在 `threading._shutdown`）；`status` 用 `dev_graph()` 上下文所以正常 | 两个命令改为 `async with dev_graph() as graph:`，退出即关闭连接 |

## 2. 冒烟脚本扩展（`scripts/functional_smoke.py`）

新增 `check_deployment_surface`：
- `/openapi.json` 有效（117 paths）、`/docs` 200；
- `index.html` 引用的 `**/assets/*` 全部 200（此前 HTML 被截断到 400 字符导致误报，已改为保留完整 body）；
- 未知 `/api/*` 路由必须是 404 错误信封；
- 错误方法 405、`gzip` 生效、CORS preflight 带 `allow-origin`。

实测（本机 8099）：**16 checks，15 pass / 0 fail / 1 skip**（鉴权段无凭据跳过）。

## 3. 测试

- 新增 `tests/unit/api/test_api_route_404_envelope.py`（3）：信封、405、非 API 默认形状。
- `tests/unit/scripts/test_functional_smoke.py` +3：部署面全 PASS、缺失资产 FAIL、非信封 404 FAIL。
- `tests/unit/cli/test_main.py` +3：status/logs/resume 未知线程 exit 1 + "线程不存在"。
- 既有 `test_frontend_static.py`、CLI/文档门禁全绿。

## 4. 文档

`docs/deployment.md` 冒烟章节补充部署面契约（404 信封、资产 404 不回退、405/gzip/CORS）。

## 5. 不做什么

- 不改 `/api/*` 既有业务 404 的 typed code（仍由 `APIError` 处理，信封不变）；
- 不把 405 也改成信封（保持框架语义，前端可区分）。
