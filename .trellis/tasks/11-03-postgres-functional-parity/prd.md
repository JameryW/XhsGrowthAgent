# fix(deploy): Windows psycopg 事件循环 + serve reload 默认 + 调度器健康语义 + 冒烟账号预置（票 5cs）

> 目标是把"本地部署后全面功能测试"里唯一没覆盖的生产路径（Postgres）补上。
> 用 `pgserver`（嵌入式 PostgreSQL 16.2，自带 pgvector 0.6.2）起真实 PG，跑通了
> `xhs-growth serve` + 登录 + 工作流生命周期，过程中发现 3 个真问题。

## 1. 实测发现

| # | 问题 | 证据 |
|---|---|---|
| 1 | **Windows 上 PG 路径完全不可用**：uvicorn 在 win32 无 reload 时硬编码 `ProactorEventLoop`，psycopg async 拒绝运行；应用陷入连接重试，随后静默回退 SQLite | `uvicorn/loops/asyncio.py`: `if sys.platform == "win32" and not use_subprocess: return asyncio.ProactorEventLoop`。日志刷 `Psycopg cannot use the 'ProactorEventLoop'…`，health 最终显示 sqlite |
| 2 | `serve` 默认 `reload=True`：生产不安全；且在受限环境里第一次代码变更后 reloader 重启即退出（exit 1），把"启动服务"变成一次性进程 | 日志末尾 `StatReload detected changes … Reloading…` 后进程退出 1 |
| 3 | 新部署 `overall=degraded` 持续数小时：scheduler 首轮未运行被记为 `warning`，而 overall 对 scheduler warning 软降级 | health 实测 `llm=ok/db=ok/ready` 但 `overall=degraded`，scheduler=`warning "定时同步尚无完成记录"`，首轮排期在 4 小时后 |

另有两处冒烟脚本缺口（不是产品 bug）：
- 全新控制台没有账号：`GET /api/workflow/list` 合法返回 400 "create an account first"，
  `POST /api/workflow/start` 返回 404 `ERROR_ACCOUNT_NOT_FOUND`。脚本必须先创建/复用一个
  所属账号，再跑生命周期。
- 生命周期调用取 15s 超时不够：start 后 runner 写 checkpoint 期间 status 实测 **~12.5s**
  （pause/resume ~1s，cancel 12.5s）。这是性能观察（嵌入式 PG 本地磁盘），不是端点失败。

## 2. 修复

| 位置 | 变化 |
|---|---|
| `backend/cli/main.py` | `serve` 新增 `--reload`（默认 **False**，生产安全）；非 reload 路径调用 `_serve_uvicorn()`：Windows 上显式创建 `SelectorEventLoop` 驱动 `uvicorn.Server`（Linux/macOS 仍走 `uvicorn.run`）；`sync-stats` 同样先切 selector（其 psycopg 异步路径同样受影响） |
| `backend/api/routes/system.py` | scheduler 首轮未完成且**已排期或按策略跳过** → `ok` + `first_run_pending=true`；只有"未排期且无记录"才 `warning`。overall 不再因正常首轮等待而降级 |
| `scripts/functional_smoke.py` | 新增 `_ensure_account`（复用或创建所属账号）、`_delete_account` 清理；`check_login` 在鉴权读之前预置账号；生命周期改用 `_call_with_retry`（60s 超时 + 1 次重试）；网络错误 status=0 一律 FAIL（此前 `<500` 会误判 PASS），404/409 视为端点已应答 |
| `tests/unit/cli/test_main.py` | serve 测试改 patch `_serve_uvicorn`（避免真的起服务器）；新增 `--reload` 帮助断言 |
| `tests/unit/api/test_system_health.py` | 更新 skip-before-first-run 断言；新增"首轮已排期=ok"与"未排期=warning"两例 |
| `tests/unit/scripts/test_functional_smoke.py` | 新增账号复用/创建/失败、生命周期使用预置账号 4 例 |
| `docs/deployment.md` | Windows 部署说明（`xhs-growth serve` 自带 selector loop；`--reload` 仅开发）；本地 Postgres 功能验证配方（pgserver）；scheduler 首轮语义；status 延迟观察 |
| `CLAUDE.md` | serve 命令与 Health Check overall 语义同步 |

## 3. 实测结果

- 嵌入式 PG：PostgreSQL 16.2，`CREATE EXTENSION vector` 成功（0.6.2）
- `xhs-growth serve`（Postgres）启动：`database=postgres/ready`、`memory_store=postgres`、`overall=ok`
- 默认管理员 bootstrap 生效：`admin/admin123` 登录 200
- 冒烟（带凭据 + `--start-workflow`）：**28 checks / 28 PASS / 0 FAIL / 0 BLOCKED**
  （health、公开接口、静态壳与资产、OpenAPI、404 信封、405、gzip、CORS、登录、账号、
  鉴权读、工作流 start/status/pause/resume/cancel/delete、账号清理）
- 全量测试开启 `XHS_PG_PARITY_URI`：见 journal

## 4. 已知观察（未在票内修）

- 嵌入式 PG 下 start 后 status/cancel 偶发 ~12.5s（runner 写 checkpoint 期间的读延迟）；
  生产需实测确认，不阻塞功能正确性。
- langgraph 警告 `Deserializing unregistered type WorkflowPhase/WorkflowMode`（未来 strict
  msgpack 会阻断）。
- `astream_events(version="v1")` 已弃用。
- 冒烟在 workflow 刚结束就删账号时偶见 psycopg `another command is already in progress`
  警告（runner 收尾与账号删除竞争），不影响响应。

## 5. 不做什么

- 不把嵌入式 PG 引入仓库依赖/CI（它是本地验证工具，不是生产组件）；
- 不改 LangGraph 的 checkpoint 序列化注册（独立事项）。
