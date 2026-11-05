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
| 默认模型终态复验（提交 `01280d1b`） | 默认路由 `opencode-go/deepseek-v4.1-flash`（无 alt 覆盖）重跑生产冒烟 + 全 gate 链路；额外覆盖 `paused/evaluator_fail_closed → POST /resume approve → completed` | **通过**：冒烟 **28/28 PASS**；`GATE_CHAIN_OK=True`（timeline 含 evaluator/publisher，`mock_published`，225.5s，9 次状态迁移） |
| 前端本地门禁（按 CI 命令） | `npm run type-check`、`npm run test:run`（75 文件）、`npm run i18n:check` | **通过**：type-check 0；**788/788 tests exit 0**；i18n 2372 keys consistent（修复 Node≥22 真实 WebSocket 后，见票 5dh） |
| omp 运行时 + xhsagent 扩展桥接 | 本地 bun 1.4.4 跑 vendored `omp` 18.14.2；`models.yml` 自定义 magpie provider；`-e xhsagent-ext/src/index.ts` 加载扩展；扩展工具经 API 真实调用 | **通过**：omp 非交互 JSON 真实 LLM 回复 "ok"；扩展暴露 **34 个 xhs 工具**；`xhs_system_health` 返回 `status=ok`（7 项检查明细）、`xhs_workflow_list` 返回 0 条，与 API 一致 |
| 实时面 | WS `subscribe`/`ping`/`get_missed`、暂停/取消的实时事件、`GET /events/missed` 补传（seq 有序、since 末尾返回 0）、SSE `/api/workflow/stream/{id}` 事件流 | 通过 |
| 语义记忆（本地 embedding，无需 API key） | `XHS_EMBED_MODEL=local:BAAI/bge-small-zh-v1.5`（512 维，HF_HOME 指向工作区）；health `memory_store.semantic_index=true`；Postgres store 写入 3 条内容后语义召回 top-1 为相关条目（相似度 0.79 vs 无关 0.27） | **通过**；关键词过滤仅匹配字符串字段（hashtag 列表不参与） |
| 并发与调度 | 50 并发 `/status`、20 并发 `/health`、creator-stats 调度器短周期实跑 | 通过（见指标）；调度器 `last_status=completed`、`interval_hours` 生效 |
| 部署面 | 静态资产 4 个、117 条 OpenAPI path、404 信封 `ERROR_ROUTE_NOT_FOUND`、405、gzip、CORS | 通过 |
| 生产优雅退出 | `serve` 关闭时 checkpoint pool 关闭、无残留 aiosqlite 线程、exit 0 | 通过 |
| 评测链 | 抽取 → 门禁 → variant → 篡改拒绝（前序 P3 票） | 通过 |
| 测试套件 | 全量 pytest（含 `XHS_PG_PARITY_URI` Postgres 对等用例） | **4981 passed / 11 skipped / 0 failed** |

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
| 5de | Redis 不可达时 `_ensure_backend` 每次鉴权都重试连接：所有认证接口恒定 ~1.03s（`/api/accounts` 1.0s、`/status` 1.03s、50 并发 status 全部 >45s 超时） | 后端探测改为进程内一次（`_backend_resolved`）；实测 `/accounts` 15–31ms、`/status` 47–125ms、50 并发 0.73s |
| 5df | Windows 下 `xhs-growth login` 打开 app DB 时未切 SelectorEventLoop：配置了 `POSTGRES_URI` 反而 30s `PoolTimeout` | login 入口调用 `_use_psycopg_compatible_loop_on_windows()`；负路径恢复为"账号不存在"exit 1 |
| 5dg | `POST /api/auth/logout` 返回 200 但不吊销 token：同一 Authorization 头仍可访问 `/api/auth/me`（200） | logout 从 Authorization 头取 token 并 `revoke_token`；新增真实 token 撤销与 service token 两条测试 |
| 5dh | Node ≥22 自带真实 `WebSocket`：前端组件测试挂载时真连 `ws://localhost:3000`，teardown 后留下未处理 `ECONNREFUSED`，`npm run test:run` 788 用例全过但 exit 1（CI Node 20 未暴露） | `frontend/tests/setup.ts` 默认 stub inert WebSocket；需要 WS 行为的 spec 仍用 `vi.stubGlobal` 覆盖；复跑 exit 0 |
| 5di | `publish-retry` 失败后 `/status` 误报 `stale/orphan`（图状态 phase=publishing 且 as_node 写入留下 next 节点）；带 `Content-Type: application/json` 的空 body 使 5 处处理器 `request.json()` 抛 `JSONDecodeError` → 500 | 重试写回 terminal phase（COMPLETED/ERROR）+ error；新增 `backend/api/body.py:json_object_body()` 统一空/非法 body → `{}`；补 5 例 helper 测试与 2 个回归测试 |

## 4. 关键指标（修复前 → 修复后）

| 指标 | 前 | 后 |
|---|---|---|
| `/status`（start 后） | 12.4 / 12.4 / 23.8 / 35.2s（另测 58s） | 47–125ms（票 5de 后；5db 时 ~1.03–2.31s） |
| 认证接口（如 `/api/accounts`） | ~1.0s（Redis 探测重试） | 15–31ms |
| 50 并发 `/status` | 50/50 超时（>45s） | **50/50 200，0.73s** |
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
- **omp 运行时**：本机用 vendored `node_modules/.bin/omp` + 本地 bun 1.4.4 验证了非交互 JSON 运行时、自定义 provider 与 xhsagent 扩展的 34 个工具桥接（见 §8）；**交互式 TUI 界面**未验证。omp 的 Python eval kernel 在本机沙箱写 `%TEMP%\omp-python-runner` 时 EPERM（JS/Bun kernel 正常，工具调用成功）——属 Windows 沙箱 ACL 环境限制，非仓库缺陷。
- **真实 LLM 限额**：gate 链路首次复跑期间 magpie 默认上游（`opencode-go/deepseek-v4.1-flash`）当日 Go 配额耗尽（429），当时用 `remote-magpie/auto/gpt-6.1-terra` 临时覆盖完成验证（仅测试启动器，不改仓库路由）；配额恢复后已用**默认路由**重跑冒烟与全 gate 链路（见 §7）。
- **Embedding**：默认 `openai:text-embedding-3-small` 无 API key；本次用本地 `BAAI/bge-small-zh-v1.5`（512 维，首次需联网下载 ~96MB）验证语义索引与召回，OpenAI embedding 路径未验证。
- **omp 交互式 TUI**：仅验证非交互 JSON 运行时与扩展桥接；TUI 界面（`rpc-ui`）未验证。
- **本地 Windows 环境噪声**：嵌入式 PG 的磁盘性能与 CI Linux 不同；CI 为准。
- `psycopg` 偶发 "another command is already in progress" 仅出现在测试竞态（删除账号与 runner 收尾并发），响应仍正确。

## 7. 终态复验（最终提交 `01280d1b`）

| 项 | 结果 |
|---|---|
| CI（GitHub Actions） | run [41865404568](https://github.com/JameryW/XhsGrowthAgent/actions/runs/41865404568) **success**（10/10 job）；此前 `7a5049fa` run 41859697819、`e2df95bc` run 41863073532 均 success |
| 生产路径冒烟（默认模型 + 干净 PG） | **28 checks: 28 pass / 0 fail / 0 blocked / 0 skip** |
| 全 gate 链路（默认模型） | `GATE_CHAIN_OK=True`：9 次状态迁移，timeline 含 `evaluator`/`publisher`，`publish_result.status=mock_published`，225.5s |
| 额外覆盖 | `paused / evaluator_fail_closed` → `POST /api/workflow/resume {"human_decision":"approve"}` → `completed`（人工恢复路径） |
## 8. 补充验证（2026-11-05 晚）

| 项 | 结果 |
|---|---|
| omp CLI 运行时 | 本地 bun **1.4.4** 驱动 `omp/18.14.2`；`models.yml` 自定义 magpie provider（`openai-completions`，两个模型）；`-p --mode json --no-session` 真实 LLM 回复 "ok"（usage 8400 tokens） |
| xhsagent 扩展加载 | `-e backend/omp/extensions/xhsagent-ext/src/index.ts` 成功加载，工具面 **34 个** `xhs_*` 工具 |
| 扩展 → API 桥接 | `XHS_AGENT_API_BASE=http://127.0.0.1:8889` + `XHS_SERVICE_TOKEN`：`xhs_system_health` 返回 `status=ok`/7 项检查；`xhs_workflow_list` 返回 “No workflows found.”（0 条）；API 日志对应 `GET /api/system/health`、`GET /api/workflow/list` 200 |
| 前端本地门禁 | `npm run type-check` 0；`npm run test:run` **75 文件 / 788 tests passed, exit 0**；`npm run i18n:check` **2372 keys consistent** |
| 环境说明 | omp Python eval kernel 因本机沙箱 ACL 无法写 `%TEMP%\omp-python-runner`（EPERM），自动改用 JS/Bun kernel 后工具调用成功；`omp models` 同时发现本机 ollama 模型（19 个），未参与验证 |
| 发布确认 gate 安全语义（`dry_run=false`） | review 批准（非 dry-run）→ evaluator 未放行 → `paused/evaluator_fail_closed`；`POST /workflow/resume {"human_decision":"approve"}` → `awaiting_publish`；**空 body `/resume` 返回 `awaiting_publish` + 指导文案、不执行发布**；`{"resume_value":{"decision":"confirmed"}}` → publisher → `completed`（`XHS_USE_BROWSER=false` 下按设计 `mock_published`） |
| shooting_planner 结构化输出失败处理 | 模型连续两次返回空结构（`body_copy`/`title_candidates` 为空）时工作流进入 `error`，错误信息明确、无挂起；重跑后通过（模型侧偶发，非代码缺陷） |
| 语义记忆（本地 embedding） | `XHS_EMBED_MODEL=local:BAAI/bge-small-zh-v1.5`（512 维，HF_HOME=工作区 `.eval-tmp/hf-cache`，模型 95.8MB）：直接相似度 0.7878/0.4904/0.2658（相关 vs 无关）；Postgres store 写入 3 条后 `recall_similar_content` 语义 top-1 命中相关条目；`GET /api/system/health` → overall `ok`、`memory_store.semantic_index=true`、`embed_dims=512`；关键词过滤命中正文词（"暖光"），hashtag 列表不参与关键词过滤 |
| 发布重试端点（publish-retry） | 对 `mock_published` 线程 `POST /api/workflow/publish-retry` → 200 `retrying`，用现有内容重跑真实发布（不重走创作链路）；无凭据下 publisher 返回结构化失败 `account_inactive`（含 recovery 指引） | 修复后（票 5di）：空 JSON body 重试 200（原 500）；失败重试终态 `status=error / phase=error / orphan=false`（原 stale/orphan）；`publish_result.status=failed` 保留错误详情 |
