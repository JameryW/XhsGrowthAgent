# feat(ops): 本地部署功能冒烟脚本 + 3 个 #756/无 PG 漂移修复（票 5cq）

> 用户要求"本地部署后做全面的功能测试"。实际把 API 与 CLI 跑起来后，发现 5 个真问题
> （3 个阻断/误导级 + 2 个文案漂移），并沉淀了一个可复用的部署冒烟脚本。

## 1. 实测发现（按严重度）

| # | 问题 | 证据 |
|---|---|---|
| 1 | **Windows GBK 控制台 CLI 直接崩溃** | `xhs-growth run` 打印面板时 `UnicodeEncodeError: 'gbk' codec can't encode '\U0001f680'`，exit 1；version/config 同样受影响 |
| 2 | **无 POSTGRES_URI 时登录 500** | 服务正常启动（SQLite checkpointer），但 app DB 池从未初始化：`POST /api/auth/login` → `RuntimeError: DB connection pool not initialized` → 500 |
| 3 | **health 谎报 LLM 未配置** | magpie 可用且 LLM 实测能出网，`llm_providers` 却只列直连 provider → "未配置任何 LLM Provider" |
| 4 | health 把 database 报成 `ok` | SQLite checkpointer ≠ 应用 DB 层就绪；登录/账号接口实际不可用 |
| 5 | CLI `config` 与 `search_api` 文案停留在 DeepSeek 直连时代 | config 不列 MAGPIE；health 要求 `DEEPSEEK_API_KEY`（#756 已禁用直连） |
| 6 | **CLI `run` 无 `--niche`** | 真实运行在 trend_scout 因 D2' 缺 niche 报错，CLI 没有参数可给，本地跑不通工作流 |

## 2. 修复

| 位置 | 变化 |
|---|---|
| `backend/cli/main.py` | 启动时把 stdout/stderr `reconfigure(encoding="utf-8", errors="replace")`（GBK 控制台不再崩）；`config` 列 MAGPIE 并注明直连已非默认；`run` 新增 `--niche`，缺 niche 时给出可操作提示并 exit 2（D2' 不放默认值） |
| `backend/db/pool.py` | 新增 `DatabaseUnavailableError`，`get_pool()` 抛它而不是裸 `RuntimeError` |
| `backend/api/middleware.py` | 映射为 **503 `ERROR_DB_UNAVAILABLE`**，消息说明缺 `POSTGRES_URI`，不再 500 |
| `backend/api/errors.py` | 新增错误码 `DB_UNAVAILABLE` |
| `backend/api/routes/system.py` | `llm_providers` 增加 magpie；`database` 增加 `app_db` 字段并在缺失时降级为 `warning`；overall 需 LLM+app_db 双就绪才 `ok` |
| `backend/services/web_search/router.py` | 文案改为 Tavily-only，说明 DeepSeek 直连已禁用 |
| `scripts/functional_smoke.py`（新） | 对运行中实例做 HTTP 冒烟：health 语义、公开接口/404、静态壳、鉴权边界；带凭据时登录 + 鉴权读 + 可选工作流生命周期；无 DB → `BLOCKED` 而非失败；仅 FAIL 时退出 1 |
| `docs/deployment.md` | 健康检查字段读法 + 部署后功能冒烟用法/判定语义 |
| `CLAUDE.md` | 命令与 Health Check 说明同步 |

## 3. 实测结果（本地 Windows，无 podman/Postgres）

- API：`/health` 200；`/api/system/health` → `llm=ok（magpie）`、`database=warning/app_db=unavailable`、overall `degraded`；静态壳 `/` 200 HTML；公开接口 200/404 正确；受保护接口未带 token 401；登录 **503 `ERROR_DB_UNAVAILABLE`**（修复后）。
- CLI：`version` / `config` / `run --dry-run` 全部 exit 0（GBK 修复后）；`run --niche 家居` 真实跑通：magpie LLM 调用（含一次连接中断重试）、XHS 工具因无 cookie 干净跳过、Ripple 禁用降级，最终 `planning`/content_strategist，exit 0。
- `scripts/functional_smoke.py`：无凭据 8 pass / 0 fail / 1 skip；带凭据 8 pass / 0 fail / 1 blocked（无 Postgres，符合预期）。
- **无法在本机验证**：完整控制台（登录+工作流生命周期）需要 Postgres；容器部署需要 podman——两者本机都没有，脚本会在有 PG 的部署上自动覆盖这些段。

## 4. 测试

- `tests/unit/scripts/test_functional_smoke.py`（新，8）：magpie 缺失=FAIL、graph-only=PASS、静态壳缺失=FAIL、503=BLOCKED、500=FAIL、退出码语义、生命周期启动失败即止。
- `tests/unit/api/test_middleware.py` +1：DB 不可用 → 503 且带 `ERROR_DB_UNAVAILABLE`。
- `tests/unit/api/test_system_health.py` +3：magpie 识别、缺 app_db 降级、双就绪才 ok。
- `tests/unit/cli/test_main.py` +4：GBK reconfigure、UTF-8 不动、dry-run 不要求 niche、缺 niche exit 2 + 提示。
- `tests/unit/services/web_search/test_router.py` +2：文案不再要求 DEEPSEEK key。

## 5. 不做什么

- 不引入 SQLite 版 app DB（登录/账号/工作流表依赖 Postgres 语义；graph-only 模式保持"能跑图、不能登录"的诚实边界）。
- 不改 langgraph msgpack strict 警告（`WorkflowPhase` 未注册）——记为已知观察，未来 langgraph 升级会阻断。
