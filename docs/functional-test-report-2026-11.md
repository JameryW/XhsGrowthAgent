# 本地部署功能测试与缺陷修复报告（2026-11）

> 范围：在开发者本机（Windows）对 XhsGrowthAgent 做"拉取最新代码 → 本地部署 → 全面功能测试 →
> 修复所有发现问题"的完整闭环。本文只记录**已实际执行并有输出证据**的结果，便于复核与交接。
> 提交均在 `origin/main`；本文件本身通过 PR 合并。

## 1. 测试环境

| 项 | 值 |
|---|---|
| 宿主 | Windows，PowerShell；Python 3.12.9（`.venv`），pytest 9.1.1，ruff 0.16.1 |
| LLM | 本机 magpie 网关（`MAGPIE_BASE_URL=http://127.0.0.1:3425/v1`），真实调用 |
| 数据库 | 嵌入式 PostgreSQL 16.2（`pgserver` wheel，自带 pgvector 0.6.2）；无 podman/docker |
| 浏览器 | `XHS_USE_BROWSER=false`（无真实小红书凭据，平台侧交互不在本次范围） |
| 启动方式 | `xhs-growth serve`（Windows 自动 SelectorEventLoop）/ CLI `xhs-growth run` |

## 2. 测试矩阵与结果

| 层面 | 覆盖内容 | 结果 |
|---|---|---|
| CLI | `version` / `config` / `run --dry-run` / 真实 `run --niche` / `status` / `logs` / `resume` / 未知线程与缺 niche 负路径 | 通过；真实工作流到 planning，exit 0 |
| API（graph-only，无 PG） | health、公开接口、静态壳与资产、OpenAPI、404 信封、405、gzip、CORS、鉴权 401、登录 503 BLOCKED | 冒烟 15 pass / 0 fail / 1 blocked |
| API（生产 Postgres） | health `database=postgres/app_db=ready`、`memory_store=postgres`、admin 登录、账号 CRUD、工作流 start/status/pause/resume/cancel/delete、清理 | 冒烟 **28/28 PASS** |
| 真实工作流 | magpie 真实 LLM、检查点写入与 resume（`status`/`logs` 读回）、无 `Blocked`/`unregistered` 告警 | 通过 |
| 人工在环 gate 链路（生产 PG + 真实 LLM） | start → ripple → draft → blogger → draft → choice → review → evaluator → dry-run publish；逐 gate 由 API 驱动，记录状态迁移 | **通过**：timeline `evaluator`/`publisher` 均执行，`publish_result.status=mock_published`，`/api/evaluation/result` 返回 `overall_score=77.1`、`decision=approved`、6 维评分 |
| 部署面 | 静态资产 4 个、117 条 OpenAPI path、404 信封 `ERROR_ROUTE_NOT_FOUND`、405、gzip、CORS | 通过 |
| 生产优雅退出 | `serve` 关闭时 checkpoint pool 关闭、无残留 aiosqlite 线程、exit 0 | 通过 |
| 评测链 | 抽取 → 门禁 → variant → 篡改拒绝（前序 P3 票） | 通过 |
| 测试套件 | 全量 pytest（含 `XHS_PG_PARITY_URI` Postgres 对等用例） | **4973 passed / 14 skipped / 0 failed** |

## 3. 发现并修复的缺陷

按票号归档在 `.trellis/tasks/archive/2026-11/`；每张票含 PRD、验收与回归测试。

| 票 | 问题（摘要） | 修复要点 |
|---|---|---|
| 5cm–5cp | P3 评测/上下文预算相关缺陷 | 见对应归档 PRD |
| 5cq | CLI GBK 控制台崩溃；无 PG 时登录 500；health 漏报 magpie / app_db；CLI 缺 niche | UTF-8 重配置；`DatabaseUnavailableError`→503；health 语义 |
| 5cr | `/api/*` 404 空 body；缺失资产回退 index.html；CLI 未知线程 exit 0；`logs/resume` 退出挂起 | 404 信封；资产 404；线程存在性校验；`async with dev_graph()` |
| 5cs | Windows ProactorEventLoop 与 psycopg 不兼容；`serve` 默认 reload；调度器首轮导致 degraded；冒烟账号/超时 | SelectorEventLoop；`--reload` 可选；`first_run_pending`；冒烟预置账号 |
| 5ct | 检查点枚举 msgpack 未注册；`astream_events` v1 弃用；冒烟删除竞态 | 显式 allowlist；v2；删除重试 |
| 5cu | 事件循环被同步代码阻塞（CDP DNS ~12s、首次 provider 导入）→ `/status` 12–58s | provider 预加载 + DNS 移出循环 + 60s TTL |
| 5cv | dev SQLite 连接未关闭 → pytest/serve 退出挂起 | lifespan 清理调用 `close_dev_graph`；serve 单测不再真起服务 |
| 5cw/5cx | CDP 探测失败结果被永久缓存；TTL 从探测开始计时 | 60s TTL；从完成时刻计时 |
| 5cy | serde strict 模式静默屏蔽 `ContentStatus` 等枚举；启动失败泄漏线程；两个 off-loop 测试恒真；accounts 负缓存永久 | 全枚举 allowlist；启动失败 try/except 清理；测试在返回时采样；host TTL |
| 5cz | allowlist 测试硬编码，新增枚举不会失败 | 动态发现 `backend.state.enums` 全部枚举 |
| 5db | provider 预加载阻塞启动（lifespan 42s） | 守护线程后台预加载 + 按路由选择，lifespan 1.38s |
| 5dc | start 后约 1s 内 `/status` 误报 `completed/100%`（`derive_status` Priority 11 忽略活跃 runner），客户端会停止轮询并跳过全部 gate | Priority 11 增加 `has_active_task`：活跃 → `running`；补 2 个单测，5 处旧断言显式 `False` |
| 5dd | review/ripple 提交先 `aupdate_state(as_node=pending gate)` 会消费动态 `interrupt()`：gate 节点不执行，review 后 `publish_result={}`、无 evaluator/publisher | side updates 随 `Command(resume=..., update=...)` 提交；回归测试断言 `Command.update` 携带 `publish_decision` |

## 4. 关键指标（修复前 → 修复后）

| 指标 | 前 | 后 |
|---|---|---|
| `/status`（start 后） | 12.4 / 12.4 / 23.8 / 35.2s（另测 58s） | ~1.03–2.31s |
| 事件循环看门狗 `LOOP STALLED` | 每轮 2–3 次（3–11s） | 0 次 |
| lifespan 启动 | 42.4s | 1.38s |
| `serve` 就绪 | >20–25s | graph-only 5.2s / Postgres 9.3s |
| 单次 checkpoint `aput` 最长 | 11–22s | ≤1.06s |
| 本地 pytest 退出 | summary 后永久挂起，需手动 kill | 正常退出 |

## 5. 复现命令

```powershell
# 全量测试（Postgres 对等用例需要 PG，未设置则自动跳过）
$env:XHS_PG_PARITY_URI='postgresql://postgres:@127.0.0.1:<port>/postgres'
.venv\Scripts\python.exe -m pytest -q

# 静态门禁（lint / format / mypy / gates / omp；--skip-tests 可选）
.venv\Scripts\python.exe scripts/ci_local.py --skip-tests

# 部署后功能冒烟（需要运行中的实例）
.venv\Scripts\python.exe scripts/functional_smoke.py `
  --base-url http://127.0.0.1:8099 --username admin --password <password> --start-workflow
```

## 6. 已知边界（未在本次验证）

- **真实小红书平台交互**：发布/互动需要测试账号凭据与平台窗口；本次以 `XHS_USE_BROWSER=false` 验证到工作流编排层。
- **本地 Windows 环境噪声**：嵌入式 PG 的磁盘性能与 CI Linux 不同；CI 为准。
- `psycopg` 偶发 "another command is already in progress" 仅出现在测试竞态（删除账号与 runner 收尾并发），响应仍正确。
