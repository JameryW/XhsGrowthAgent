# Journal - codex (Part 2)

> Continuation from `journal-1.md` (archived at ~2000 lines)
> Started: 2026-11-02

---



## Session 60: E4 质量裁判与 199 调用预算护栏（票 5ch）

**Date**: 2026-11-02
**Task**: E4 质量裁判与 199 调用预算护栏（票 5ch）
**Branch**: `main`

### Summary

按 2026-11-02 拍板落地 E4 裁判：scripts/eval/judge.py 提供五维 JudgeScores、确定性提示词、容错解析（围栏/散文/缺维度/超范围）、JudgeBudget（默认 199，先扣费后调用，超限拒绝）与 judge_content（一次判定一次调用，坏输出仍计费）；与生产 evaluator 分离，不影响发布决策。11 个假模型用例覆盖提示词确定性、解析容错、预算语义（耗尽时模型零调用）与坏输出计费。文档记录三项拍板、§6.9 与仍 external-only 的 live 执行边界；agent-os 路线图 10 补 5ch。验证 docs 门禁 146 passed、全量 4873 passed / 14 skipped / 0 failed / 0 errors。票 5ch 已归档。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `2f6f79bf` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 61: L3 live 授权门闸与部署 runbook + 脱敏加固（票 5ci）

**Date**: 2026-11-02
**Task**: L3 live 授权门闸与部署 runbook + 脱敏加固（票 5ci）
**Branch**: `main`

### Summary

新增 scripts/eval/plan_l3.py（live 运行授权门闸：samples 1..50、judge_calls<=max_calls<=199、测试账号必填、judge!=none、XHS_EVAL_LIVE=1；--armed 不满足 exit 1、--json 输出无凭据计划）与 docs/adaptive-harness-runbook.md（部署侧 live 步骤与停止条件），评测方案补 §6.10。同时修复 E1 两个脱敏缺口：密钥形状键的容器值现在整段置空（此前 {'api_key': {'value': ...}} 会泄漏）、非字符串标识符不再被走进容器（字符串列表→假名列表，其他置空）。验证 plan_l3 11 passed、fixtures 12 passed、unit/scripts 159 passed、ci_local 静态作业 PASS、全量 4886 passed / 14 skipped / 0 failed / 0 errors。票 5ci 已归档。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `60c31cef` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 62: 独立审查修复：E1 脱敏与 E3/E4 门禁加固（票 5cj）

**Date**: 2026-11-02
**Task**: 独立审查修复：E1 脱敏与 E3/E4 门禁加固（票 5cj）
**Branch**: `main`

### Summary

按独立审查修复全部高危/中危：E1 脱敏覆盖真实 schema 身份字段（workflow_thread_id/reviewer/nickname/author/post_id…）、URL 清空、绝对路径护栏、messages 永远丢弃并移除坏开关；JudgeBudget 拒绝 >199 且 budget 必填；门禁空语料/旧脱敏版本/未列出文件/非 PASS benchmark/未知状态/决策相同 variant 全部转红，policy 类型校验，mode 由 --fail-on-red 决定；sqlite 只读打开且跳过 subgraph ns、phase 过滤收紧；plan_l3 按总量校验预算（calls_per_sample 必填）；文档与 runbook 同步真实范围。验证 fixtures 14/gate 23/judge 12/plan 13、unit scripts 172、全量 4899 passed / 14 skipped / 0 failed / 0 errors。票 5cj 已归档。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `dba338dc` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 63: 语料指纹与加盐假名（票 5ck）

**Date**: 2026-11-02
**Task**: 语料指纹与加盐假名（票 5ck）
**Branch**: `main`

### Summary

收口独立审查两条低危：抽取器写 manifest.sha256，gate 校验并支持 --expect-manifest-sha256 做 out-of-band 核对（文档如实说明成对重写需外部值）；pseudonym 支持 HMAC 密钥（XHS_EVAL_REDACTION_KEY，不写入语料），manifest 记录 pseudonym_mode，无密钥时警告短 id 可被字典攻击。新增 5 个用例（加盐稳定/不同密钥、加盐与无盐抽取模式、指纹不匹配、out-of-band 期望值）。验证 fixtures 17、gate 25、unit scripts 177、全量 4904 passed / 14 skipped / 0 failed / 0 errors；ruff 与 ci_local 静态作业绿。票 5ck 已归档。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `b5498859` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 64: 验证轮小硬化：预算单一来源、未列出 JSON、无盐提示（票 5cl）

**Date**: 2026-11-02
**Task**: 验证轮小硬化：预算单一来源、未列出 JSON、无盐提示（票 5cl）
**Branch**: `main`

### Summary

三处小硬化 + 文档同步：plan_l3 改为从 judge 导入 APPROVED_MAX_CALLS（预算上限单一来源）；gate 未列出文件检查扩到所有 *.json（下划线变体也红）；无盐语料 detail 始终标注 pseudonyms unsalted (sha256)（可见不阻断）；agent-os 路线图 10 与结论补齐 5cd–5ck 与 E4 状态。验证 gate 25、plan_l3 13、unit scripts 177、全量 4904 passed / 14 skipped / 0 failed / 0 errors。票 5cl 已归档。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `52046e04` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 65: 复核高危修复：artifact 内容解析与第二批脱敏（票 5cm）

**Date**: 2026-11-02
**Task**: 复核高危修复：artifact 内容解析与第二批脱敏（票 5cm）
**Branch**: `main`

### Summary

按第二轮独立复核修复两处高危：1) 抽取器新增 --store-uri，用 resolve_state 解析 artifact ref 化内容；无 store/解析失败跳过并计 unresolved_artifacts，绝不写无内容 fixture；2) 第二批真实 schema 身份字段（platform_post_id/run_id/target_id/ids/confirmer/confirmed_by/user_viral_links/复数 URL/UNC/file://）补齐脱敏并回归。残留中危：指纹必需、extractor_version 校验、逐 phase 预算快照与校验、JudgeBudget used 边界与 max_calls 只读、任何 live 运行需 XHS_EVAL_LIVE、估算非上限、phase 过滤不丢线程、驱动错误干净退出。验证 fixtures 21/gate 29/judge 14/plan 15/policy 9、unit scripts+harness 197、ruff+mypy 绿、全量 4916 passed / 14 skipped / 0 failed / 0 errors。票 5cm 已归档。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `22ccb163` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 66: #756 后变体示例改为逐 phase 预算（票 5cn）

**Date**: 2026-11-02
**Task**: #756 后变体示例改为逐 phase 预算（票 5cn）
**Branch**: `main`

### Summary

远端 #756（LLM 统一走 magpie、禁用直连 DeepSeek）使原 route_lighter 变体失去意义；改为 phase_budget 变体（publishing 预算 4000），gate diff 仅 context_budgets，测试与 §6.8 同步；删除旧变体。分支已 rebase 到 #756，全量 4916 passed / 14 skipped / 0 failed / 0 errors。票 5cn 已归档。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `4e565dfe` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 67: 文档计数更正与本地 CI 全量验证（票 5co）

**Date**: 2026-11-03
**Task**: 文档计数更正与本地 CI 全量验证（票 5co）
**Branch**: `main`

### Summary

核对评测方案全部 X passed 声明：judge 12→13 并补 used/max_calls 边界覆盖；其余计数一致（fixtures 21/gate 29/plan 15/policy 9/unit scripts 188）。同轮跑完整 ci_local：lint/format/mypy/gates/tests/omp PASS，eval-gate 与 frontend 如实 SKIP，local CI parity: OK。票 5co 已归档。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `e798c3e2` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 68: artifact 写缝回归与扫描上限（票 5cp）

**Date**: 2026-11-03
**Task**: artifact 写缝回归与扫描上限（票 5cp）
**Branch**: `main`

### Summary

三处部署相关护栏：用 refify_updates 真实写缝回归解析内容（此前只用 put_artifact 直写）；断言 Postgres saver/store 的 from_conn_string 入口存在（--postgres-uri/--store-uri 依赖）；新增 --scan-limit 限制 alist 读取量，命中记 scan_capped 并警告语料可能不完整。文档 §6.5 与 runbook 同步（fixtures 24 用例）。验证 unit scripts+harness 200、ci_local 静态作业 PASS、全量 4919 passed / 14 skipped / 0 failed / 0 errors。票 5cp 已归档。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `2d082dcd` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 69: 本地部署功能测试：6 发现 5 修复 + 冒烟脚本（票 5cq）

**Date**: 2026-11-03
**Task**: 本地部署功能测试：6 发现 5 修复 + 冒烟脚本（票 5cq）
**Branch**: `main`

### Summary

本地无 podman/Postgres，原生起 API（8099/sqlite/magpie 可用）做功能测试。发现并修复：Windows GBK 控制台 CLI 崩溃（UTF-8 reconfigure）；无 PG 时登录 500（DatabaseUnavailableError→503 ERROR_DB_UNAVAILABLE）；health 漏报 magpie；health 把 SQLite checkpoint 报成 app DB ok（新增 app_db 字段与 overall 降级）；CLI config/search 文案仍在 DeepSeek 直连时代；CLI run 缺 --niche 导致 D2' 无法起跑。新增 scripts/functional_smoke.py（health/公开接口/静态壳/鉴权边界/登录+可选工作流生命周期，无 DB 记 BLOCKED，仅 FAIL 退出 1）与 8 个测试；docs/deployment.md、CLAUDE.md、execution-plane.md 锚点同步。实测冒烟 8 pass/0 fail（带凭据 +1 blocked）；CLI run --niche 家居 真实跑通 exit 0。全量 4936 passed / 14 skipped / 0 failed / 0 errors。票 5cq 已归档。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `c5dff332` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 70: 部署面契约修复：404 信封/资产 404/CLI 线程与连接泄漏（票 5cr）

**Date**: 2026-11-03
**Task**: 部署面契约修复：404 信封/资产 404/CLI 线程与连接泄漏（票 5cr）
**Branch**: `main`

### Summary

本地部署功能测试部署面发现 4 个问题并修复：未匹配 /api/* 返回空 404（改 ApiResponse 信封 ERROR_ROUTE_NOT_FOUND）；缺失 /assets/* 回退 index.html（改 404）；CLI status/logs/resume 未知线程报 completed 且 exit 0（加 _require_existing_thread，exit 1）；logs/resume 不关闭 dev graph 导致 aiosqlite 线程使进程挂死（改 async with dev_graph）。functional_smoke 增加部署面检查（openapi/docs/静态资产/404 信封/405/gzip/CORS，修 HTML 截断误报），实测 16 checks 15 pass/0 fail/1 skip。新增测试 9；docs execution-plane 锚点与 deployment 契约同步。全量 4945 passed / 14 skipped / 0 failed / 0 errors。票 5cr 已归档。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `41337768` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 71: 检查点枚举 allowlist + astream v2 + 冒烟删除重试（票 5ct）

**Date**: 2026-11-04
**Task**: 检查点枚举 allowlist + astream v2 + 冒烟删除重试（票 5ct）
**Branch**: `main`

### Summary

修复真实运行遗留：WorkflowPhase/WorkflowMode 在 langgraph msgpack 中未注册（未来 strict 版本会拒绝加载旧线程）——新增 checkpoint_serde 显式 allowlist 并注入 dev/memory/prod 三种 checkpointer；CLI astream_events v1→v2 消除弃用告警；冒烟 cancel 后 delete 400 时重试，避免孤儿历史。真实 CLI run 与 Postgres API 冒烟均验证无 unregistered/弃用告警。含 PG 对等全量 4958 passed / 11 skipped / 0 failed。票 5ct 已归档。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `bbac6f4e` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 72: 事件循环阻塞修复：provider 预加载与 CDP DNS 移出循环（票 5cu）

**Date**: 2026-11-04
**Task**: 事件循环阻塞修复：provider 预加载与 CDP DNS 移出循环（票 5cu）
**Branch**: `main`

### Summary

定位 /status 12-58s 真因：async 节点同步阻塞（Windows DNS 解析 host.containers.internal 走满超时 ~12s；首次 provider SDK import 在循环内）。修复：启动时 to_thread 预加载 provider SDK；CDP host 解析 lru_cache + to_thread；publisher/free 使用 async 包装。实测 /status ~1.1s、看门狗卡顿 0 次、aput ≤1.06s；生产冒烟 28/28；全量含 PG 对等 4963 passed / 11 skipped / 0 failed。新增 off-loop 回归测试 3 组；文档与 execution-plane 锚点同步。票 5cu 已归档。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `991c8099` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 73: dev SQLite checkpointer 未关闭导致退出挂起（票 5cv）

**Date**: 2026-11-04
**Task**: dev SQLite checkpointer 未关闭导致退出挂起（票 5cv）
**Branch**: `main`

### Summary

定位本地 pytest summary 后不退出：进程内 wrapper 显示残留 aiosqlite 非守护 worker 线程，二分到 serve 单测实际启动服务器、应用 lifespan 的 SQLite 回退 dev graph 关闭时未关闭连接。修复：app 清理阶段调用 close_dev_graph（新增 _close_dev_sqlite_checkpointer）；serve 单测改 patch _serve_uvicorn 并覆盖 --reload 路径；新增 3 个 cleanup 单测；CLAUDE.md 记录。CLI 子集 0/3→3/3 clean exit；全量 4964 passed / 14 skipped / 0 failed 且正常退出；lint/format/gates/mypy 通过。票 5cv 已归档。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `e01a3ea5` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 74: CDP 探测缓存改 60s TTL（票 5cw）

**Date**: 2026-11-04
**Task**: CDP 探测缓存改 60s TTL（票 5cw）
**Branch**: `main`

### Summary

修复 5cu 引入的回归：容器 CDP 探测此前用进程级 lru_cache，失败结果永久缓存，Chrome 后启动需重启进程才能恢复。改为 60s TTL 缓存并抽出 uncached 探测 + clear helper；新增 3 个单测覆盖 TTL 内复用、过期重探、正结果缓存、清缓存恢复。全量 4967 passed / 14 skipped / 0 failed 且正常退出；lint/format/gates/mypy 通过。另用最小脚本验证 serve 正常 shutdown 后 aiosqlite 线程为 0、进程自行退出。票 5cw 已归档。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `a6da3bf8` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 75: 生产路径（Postgres）在 5cu/5cv/5cw 后回归：28/28 冒烟、status ~1s、优雅退出池关闭

**Date**: 2026-11-04
**Task**: 生产路径（Postgres）在 5cu/5cv/5cw 后回归：28/28 冒烟、status ~1s、优雅退出池关闭
**Branch**: `main`

### Summary

重建嵌入 PG 16.2 后回归生产路径：health overall=ok / database=ok(app_db=ready) / memory_store=postgres；scripts/functional_smoke.py --start-workflow 28/28 PASS；start 后连续 3 次 status 延迟 2.31s/1.03s/1.03s（修复前 12-58s）；用 SelectorEventLoop 驱动真实 uvicorn Server 优雅退出：CHECKPOINTER_POOL_CLOSED=True、AIOSQLITE_THREADS=0、8.4s 内 exit 0（SQLite 模式同样 0 残留线程）。注意 Windows 下 in-process 驱动必须显式 SelectorEventLoop，否则 psycopg 在 Proactor 上 PoolTimeout 回退 SQLite（脚本层面，不是产品问题）。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `ffb105ca` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 76: CDP TTL 从探测完成计时（票 5cx）

**Date**: 2026-11-04
**Task**: CDP TTL 从探测完成计时（票 5cx）
**Branch**: `main`

### Summary

自审 5cw 发现缓存时间戳在阻塞探测前采样，慢 DNS 会把 60s TTL 缩成 ~48s；改为探测完成后计时。2 行修正，TTL 3 测试通过，全量 4967 passed / 14 skipped / 0 failed 且进程正常退出；本地 CI parity（lint/format/mypy/gates/omp，--skip-tests）通过。票 5cx 已归档。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `3a6a14ba` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 77: 独立审查修复：serde 全枚举 allowlist、启动失败清理、测试判红（票 5cy）

**Date**: 2026-11-04
**Task**: 独立审查修复：serde 全枚举 allowlist、启动失败清理、测试判红（票 5cy）
**Branch**: `main`

### Summary

独立 adversarial review 发现 serde allowlist 严格模式会静默屏蔽 ContentStatus 等 4 个真实检查点枚举（决策字段降级为 str + Blocked 告警），已补齐 6 个枚举并加逐成员/嵌套 round-trip 测试；lifespan 启动失败路径原会泄漏 aiosqlite 线程导致进程挂起，现 try/except 关闭 store/pool/dev graph 再抛；两个 off-loop 测试改为 endpoint 返回时采样（去掉 vacuous 断言）；accounts CDP host 负结果从永久 lru_cache 改 60s TTL；close 失败改 logging.warning。聚焦 82 passed；全量 4971 passed / 14 skipped / 0 failed 且正常退出；lint/format/gates/mypy 通过。票 5cy 已归档。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `3b426d57` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 78: 收尾：5cs 归档（遗留观察项已被后续票修复）+ 真实工作流 resume 验证

**Date**: 2026-11-04
**Task**: 收尾：5cs 归档（遗留观察项已被后续票修复）+ 真实工作流 resume 验证
**Branch**: `main`

### Summary

归档唯一遗留的进行中票 5cs（Postgres 功能对等）：其 notes 里列的 12.5s status 延迟、unregistered msgpack 告警、astream v1 均已由 5ct/5cu 修复，meta.followups 记录映射。另用真实 CLI 工作流验证 serde 修复：run --niche 家居 走 magpie 到 planning（exit 0），随后 status/logs 加载同一检查点，无任何 Blocked/unregistered 告警。产物 .xhs/checkpoints.sqlite 中新增线程 xhs_default_b127e8a3。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `7fa6ab89` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 79: serde allowlist 动态枚举防线（票 5cz）

**Date**: 2026-11-04
**Task**: serde allowlist 动态枚举防线（票 5cz）
**Branch**: `main`

### Summary

把 5cy 的硬编码 6 枚举断言改为动态发现 backend.state.enums 全部 StrEnum：allowlist 必须完全一致，新增枚举会让测试失败强制同步（否则 strict msgpack 会静默降级）。聚焦 4 passed；全量 4971 passed / 14 skipped / 0 failed 且正常退出。另：用真实 Postgres 验证重构后的 lifespan——health ok/ok/ready、优雅退出 CHECKPOINTER_POOL_CLOSED=True、0 残留线程、exit 0；第二次独立外审进程异常退出（无产出），已由自查+动态防线替代。票 5cz 已归档。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `8a064973` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 80: 启动回归修复：provider 预加载后台化，42s→1.4s（票 5db）

**Date**: 2026-11-04
**Task**: 启动回归修复：provider 预加载后台化，42s→1.4s（票 5db）
**Branch**: `main`

### Summary

定位 5cu 启动回归：await 的 provider 预加载在 Windows 冷启动拉起 transformers/torch（import hook 证实），lifespan 42.4s、就绪 >20s。改为按路由选择 provider + 守护线程后台预加载，API/CLI 非阻塞；实测 lifespan 1.38s、serve 就绪 5.2s、真实 CLI 工作流正常（exit 0）。新增 daemon/失败吞掉/按路由导入测试；全量 4973 passed / 14 skipped / 0 failed 且正常退出；lint/format/gates/mypy 通过。票 5db 已归档。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `51a54153` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 81: 启动指标补齐：Postgres 模式 serve 就绪 9.3s（5db 后）

**Date**: 2026-11-04
**Task**: 启动指标补齐：Postgres 模式 serve 就绪 9.3s（5db 后）
**Branch**: `main`

### Summary

5db 之后补测生产模式启动：POSTGRES_URI + xhs-growth serve 从进程启动到 /api/system/health 200 = 9.3s（修复前 >20-25s），health ok / database ok(app_db=ready) / memory_store=postgres；graph-only 模式此前实测 5.2s。deployment.md 补充两个就绪数字。嵌入 PG 已停止。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `65e042db` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 82: gate 全链路与实时/并发/调度补测（票 5dc-5df）

**Date**: 2026-11-05
**Task**: gate 全链路与实时/并发/调度补测（票 5dc-5df）
**Branch**: `main`

### Summary

gate 链路打通；auth Redis 探测与 CLI login loop 修复；4979 passed

### Main Changes

## 2026-11-04 深夜：人工在环 gate 全链路 + 实时/并发/调度补测

### 修复（main）
- 7a5049fa fix(gates)：`derive_status` Priority 11 增加 `has_active_task`（start 后 ~1s 误报 completed 会让客户端停止轮询跳过 gate）；review/ripple 的 side updates 改随 `Command(resume=..., update=...)` 提交（原 `aupdate_state(as_node=pending gate)` 会消费动态 interrupt，review 后 `publish_result={}`、无 evaluator/publisher）。CI 41859697819 success。
- e2df95bc perf(auth)+fix(cli)：Redis 不可达时 `_ensure_backend` 每次鉴权重试连接，所有认证接口恒定 ~1s（50 并发 /status 全超时）；改为进程内只探测一次（`_backend_resolved`）。Windows `xhs-growth login` 打开 app DB 前未切 SelectorEventLoop，配置 POSTGRES_URI 时 30s PoolTimeout。CI 41863073532。

### 证据
- 全量 pytest（PG parity）：**4979 passed / 11 skipped / 0 failed**。
- 人工在环 gate 链路（生产 PG + 真实 LLM）：start → ripple → draft → blogger → draft → choice → review → evaluator → dry-run publish；timeline 含 evaluator/publisher，`publish_result.status=mock_published`，`/api/evaluation/result` overall_score=77.1/approved。
- 实时面：WS subscribe/ping/get_missed、暂停/取消实时事件、`GET /events/missed`（27 事件 seq 有序，since 末尾=0）、SSE `/api/workflow/stream` 首帧。
- 调度器：`CREATOR_STATS_SYNC_INTERVAL_HOURS=0.0006` 实跑 `run=1 status=completed`，health 回填 last_finished_at。
- 并发：50 并发 /status 50/50 200，0.73s（修复前 50/50 >45s 超时）；/accounts 1.0s→15–31ms，/status 1.03s→47–125ms。
- 只读 API：workflow/list、workflow/history（19 checkpoints）、analytics/costs（$0.11）、evaluation/list、creator-stats、evaluation/run（76.4）。
- CLI：version、sync-stats --dry-run（6 suggestions）、login 负路径（PG 下立即「账号不存在」exit 1）。
- LLM 配额：magpie 默认上游当日 Go 配额耗尽（429），gate 链路用 `remote-magpie/auto/gpt-6.1-terra` 临时覆盖（测试启动器，未改仓库路由）。

### 未验证（外部阻塞）
真实小红书发布/互动、omp TUI 运行时（本机无 omp/pnpm）、前端浏览器 E2E（CI frontend 已过）、语义检索（无 embedding key）、真实 Ripple/Tavily（无凭据）、真实发布（仅 dry-run）。


### Git Commits

| Hash | Message |
|------|---------|
| `7a5049fa` | (see git log) |
| `e2df95bc` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 83: 架构升级完成度审计与 4 处缺陷修复（2026-11-14）

**Date**: 2026-11-14
**Task**: 架构升级完成度审计与 4 处缺陷修复（2026-11-14）
**Branch**: `main`

### Summary

审计 9 个执行面切片 + P3 工具链；修复 verification 遥测/协程泄漏/eval serde/文档漂移；全量 4990 passed / 14 skipped / 0 failed

### Main Changes

## 2026-11-14：架构升级完成度审计 + 4 处缺陷修复

### 审计（只读，3 路并行）
- 对照 `docs/agent-os-upgrade-2026q4.md` / `docs/adaptive-harness-eval-plan.md` 逐条核对：9 个执行面切片（P0-A/P0-B/Attempt/Run/P1-A/P1-B/P2-部分/证据采集器/ADR-0007）全部 PRESENT 且有生产调用点；P3-前置 F 矩阵 F1/F2/F4 PASS、F5/F7/F8 仍 SKIP；E1–E4 工具链在但 E2/E3 未接线、L1/L2 回放未实现、live external-only。
- 本地全量：4990 passed / 14 skipped / 0 failed；`ci_local.py --skip-tests` lint/format/mypy/gates/omp 全 PASS；E3 corpus PASS 路径用临时语料实跑通过。
- 发现的缺陷：verification 事件无测试守护且控制面发布不发射；`test_publish_retry` 泄漏未 await 的租约心跳协程；文档 8 处漂移（锚点/计数/词表/路线图票号/本地库说明/用例数）；E1 抽取器未用项目 checkpoint serde（真实 checkpoint 打印 unregistered type 警告）。

### 修复（4 个提交）
- `de5ad5cc` fix(telemetry)：控制面 creator-origin 发布补 `kind:"verification"`（mainline-origin 不重复）；新增 3 条守护测试。
- `43a88329` test(publish-retry)：统一 5 处 fake_create_task，关闭未调度协程；warnings 5→1。
- `ae06d01e` fix(eval)：抽取器 sqlite/Postgres 两条入口改用 `checkpoint_serde()`；新增 2 条入口契约测试（24→26 passed）。
- `c83ac772` docs：同步 §2/§5/§9 锚点与计数（4990/14）、§5.10 保留词、§9.2 票号到 5cp、新增 §9.3 复核记录；eval-plan 本地库 0→27 checkpoints 等；`.gitignore` 忽略 `.workbuddy/`、`data-gym-cache/`。

### 验证
- 全量 pytest 4990 passed / 14 skipped / 0 failed（5004 collected，222s，1 条环境级 Starlette 弃用警告）。
- `scripts/ci_local.py --skip-tests`：PASS lint / format / mypy / gates / omp → `local CI parity: OK`。
- 文档门禁 `tests/unit/scripts` 207 passed；E3 临时语料 `[PASS] corpus 5 fixtures` + `benchmarks F1/F2/F4`，`mode=block red=False`。
- 已 rebase 到 origin/main `96bf61f1` 并推送（`de5ad5cc`/`43a88329`/`ae06d01e`/`c83ac772`/`c49ce79b`）；CI run **43592668170** 的 10 个作业全部 success。
- 补齐本地 `frontend/node_modules`（npm install，270 packages）后：`vue-tsc --noEmit` 通过、`vitest run` **788 passed / 75 files**、i18n 2372 keys 通过、OMP `tsc --noEmit` 通过——§9.1/§9.2 的环境限制项在本地已可复核（node_modules 不入库，CI 仍权威）。

### 未做（裁定/外部）
- 路线图 8（多 Agent 并行）保持「先不建」；E4 live 端到端 external-only。~~E2 接线需产品拍板；E3 的 L2 回放/阈值仍缺；本地 `.eval-fixtures/` 未生成~~ —— 这三项已在 2026-11-14 后续轮补齐，见下节。

### 2026-11-14 后续轮：E2 接线 + E3 L2/阈值 + 本地语料（完成剩余全部）

- **E2 接线**：新增 `backend/harness/runtime.py`（`XHS_HARNESS_POLICY=module:factory` 惰性解析、`configure_policy`/`reset_policy`/`policy_generation`/`is_default_policy`、坏 spec 抛 `HarnessPolicyLoadError` 不静默回退）；`ModelRouter._candidate_model_ids`（overrides → policy.route_model → MODEL_FALLBACKS → escalation，`with_fallback` 惰性嵌套，cache key 含代际）、`compile_prompt`（仅 budget None 时问 phase 预算）、`ToolGateway._effective_limits`（默认策略不查目录；非默认用 ToolLimits，未知能力回退 spec，非法 limits 抛 ValueError）。默认行为等价；`test_runtime.py` 36 + `test_policy.py` 9 + 770 passed，mypy 267 files 0 issues。
- **E3 L2**：`scripts/eval/tool_replay.py`（manifest/逐 case sha256、真实 `ToolGateway` + 脚本化工具、ToolResult 分类 + 唯一 invoke 回执 + `EffectLedger` 终态/blocks_retry、两次回放确定性）+ `scripts/eval/record_tool_results.py`（`--seed` 5 边界 case；`--sqlite-path` 抽取，无记录写空 manifest 如实报告）；缺/空语料 SKIP，坏 manifest/sha/分类/回执/账本/非确定判红；`test_eval_l2.py` 23 passed。
- **阈值**：`scripts/eval/thresholds.py`（cost 漂移 ≤5%、p50/p95 ≤10%、quality ≥0.8；baseline 0 与缺 judge 数据显式 SKIP，坏 metrics 红）；`test_eval_thresholds.py` 40 passed。
- **门禁**：`run_gate.py` 现为 corpus/policy/l1/l2/thresholds/variant/benchmarks 七项检查，新增 `--tools-corpus`/`--metrics`/`--skip-l2`/`--skip-thresholds`；`test_eval_gate.py` 37 passed（+8 集成）。
- **本地语料**：`extract_fixtures.py` 生成 `.eval-fixtures/`（5 fixtures，digest `17e331e3…`；未设 `XHS_EVAL_REDACTION_KEY` → 未加盐；10 个 artifact refs 跳过）；`record_tool_results.py --seed` 生成 `.eval-tool-corpus/`（5 cases）；二者 gitignored，`.gitignore` 增 `.eval-tool-corpus/`。
- **验证**：`pytest -q` → **5113 passed / 14 skipped / 0 failed**（5127 collected，166s）；`ci_local --skip-tests` 全绿（本地有语料时 eval-gate 真实运行 corpus/policy/l1/l2/benchmarks PASS，thresholds 无 metrics 显式 SKIP）。
- 文档：eval-plan §3/§4/§5/§6.6/§6.7 与 agent-os §9.1/§9.2/§9.3/新增 §9.4 同步。

### 2026-11-14 追加：E3 L1 决策回放（用户选定方向）
- `scripts/eval/decision_replay.py`：逐 fixture 回放四个决策（model 路由 / 该 phase 的 context budget / escalation / tool limits）；**强制不变量**（路由非空、预算 None 或非负 int、escalation 目标非空且不重复、tool limits 形状、JSON 可序列化）+ **确定性**（两次回放必须一致）；与基线的差异按 fixture 逐字段写入 preference diff（不判红）；未传 `--variant` 却偏离基线判红；缺语料与 `--skip-l1` 均显式 SKIP（缺口不当通过）。
- `scripts/eval/run_gate.py`：新增 `l1` 检查与 `--skip-l1`；`GateReport.l1` / `l1_diff`；JSON 报告含 l1 summary；CLI 打印 `l1 preference diff`。
- 验证：`tests/unit/scripts/test_eval_l1.py` **16 passed**（基线干净、预算变体降级为 preference diff、无 variant 偏离必红、空路由/重复 escalation/非确定性必红、缺语料/空语料 SKIP、不可读语料红、gate 集成与 --skip-l1、边界预算与 bool 拒绝）；`tests/unit/scripts` 共 **223 passed**。
- 实跑：真实语料 5 fixtures → `[PASS] l1: decisions identical to the baseline`；demo 语料 + `phase_budget` 变体 → `l1 preference diff: {"fixture-pub": {"context_budget": {"baseline": null, "current": 4000}}}`，`mode=block red=False`。
- 文档：eval-plan §3/§4/§5/§6.7 与 agent-os §9.2/§9.3 同步 L1 状态。
- 提交：`3bc05c4c feat(eval): 实现 E3 L1 决策回放` 已推送；CI run 43596029485 的 10 个作业
  全部 success。
- 未做：L2 工具/网关回放需录制的 `ToolResult` 序列（尚未采集）；成本/时延/质量阈值判定属 E4 live 产出。


### Git Commits

| Hash | Message |
|------|---------|
| `de5ad5cc` | (see git log) |
| `43a88329` | (see git log) |
| `ae06d01e` | (see git log) |
| `c83ac772` | (see git log) |
| `3bc05c4c` | feat(eval): 实现 E3 L1 决策回放 |
| `4eddb652` | docs: 记录 L1 推送与 CI |
| `35a10a78` | feat(harness): 接线 HarnessPolicy（E2） |
| `7fb3dad8` | feat(eval): E3 L2 + 阈值 + gate 七项检查 |

### Testing

- [OK] 全量 `pytest -q`：5113 passed / 14 skipped / 0 failed（5127 collected，166s）
- [OK] `ci_local --skip-tests`：lint/format(711 files)/mypy(267 files)/gates/eval-gate/frontend/omp 全 PASS

### Status

[OK] **Completed**

### Next Steps

- 已无可本地执行的剩余项：E1–E3（含 L1/L2/阈值）、E2 接线、E4 裁判/预算/计划门闸全部落地并验证；仅 E4 live 端到端 external-only，路线图 8 继续裁定不建。
- 提交：`35a10a78` E2 接线、`7fb3dad8` L2+阈值+gate、`082b5602` 文档；已推送 origin/main。CI run **43601364293**（commit `082b5602`）10 个作业全部 success。

### 2026-11-14 补充：部署文档同步

[OK] **Completed**

- `.env.example` / `CLAUDE.md` Environment Setup 补 `XHS_HARNESS_POLICY`（留空=默认策略；`module:factory` 注入；坏 spec 抛 `HarnessPolicyLoadError`，不静默回退）。
- `docs/adaptive-harness-runbook.md` §2 由三项改成七项门禁：补 `record_tool_results.py --seed`、`--tools-corpus` / `--metrics` 用法、逐项期望与 SKIP 语义。
- 本地 `ci_local.py --skip-tests` 全 PASS（lint / format 720 files / mypy 267 / gates / eval-gate / frontend / omp）；`test_eval_gate` + `test_ci_local` 47 passed。
- docs-only CI run **43601887947**（commit `92a3972a`）10 个作业 success。
- 追加发现并修复：`scripts/deploy.sh` 用显式 `-e VAR` 列表传环境变量（不读 env-file），`XHS_HARNESS_POLICY` 漏传会导致 `.env` 设置永远进不了容器 → 已补 `-e XHS_HARNESS_POLICY="${XHS_HARNESS_POLICY:-}"`，`bash -n` 通过；CLAUDE.md 部署段同步说明「新 harness 开关须加进该列表」。
- `.env.example` 补齐 `XHS_EMBED_MODEL/DIMS/BASE_URL`（deploy.sh 一直传，模板缺失）；HYMEMORY_* 故意不进 deploy（镜像只装 `.[browser]`，SDK 未装，需显式 `.[memory-hy]` 才启用），已确认不是漏配。

### 2026-11-14 补充（二）：部署 env 三方对账

[OK] **Completed**

- 机制确认：镜像只 `COPY backend/` + entrypoint + `frontend/dist`，`.dockerignore` 排除 `.env`；容器 env 唯一来源是 `deploy.sh` 的 `-e` 白名单（不是 env-file）。据此对 `.env.example` ↔ `deploy.sh` ↔ backend `os.environ` 读取做全量对账。
- `deploy.sh` 后端容器补传（均有代码默认值兜底）：`XHS_COOKIE`/`XHS_USER_ID`（单账号回退凭据）、`XHS_BROWSER_ACTION_COOLDOWN_SECONDS`、`XHS_PUBLISH_COOLDOWN_SECONDS`、`XHS_ENGAGEMENT_ACCOUNT_COOLDOWN_SECONDS`、`XHS_QR_LOGIN_COOLDOWN_SECONDS`、`XHS_QR_RISK_BLOCK_SECONDS`、`XHS_CDP_{PUBLISH,ENGAGEMENT,LOGIN}_LOCK_TIMEOUT_S`、`XHS_ALLOW_OUTBOUND_DM`、`XHS_DM_DAILY_LIMIT`、`XHS_COMMENT_REPLY_DAILY_LIMIT`、`CREATOR_STATS_REUSE_TAB_CHANCE`/`MAX_OPEN_PAGES`/`HYGIENE_MAX_CLOSE`、`RIPPLE_LLM_MODEL`、`NOTIFICATION_WEBHOOK_URL`。
- `.env.example`：删除全仓库无读者的 `IMAGE_GEN_API_KEY`；新增 `XHS_ALLOW_OUTBOUND_DM`/`XHS_DM_DAILY_LIMIT`/`XHS_COMMENT_REPLY_DAILY_LIMIT` 模板行；`XHS_COOKIE`/`XHS_USER_ID` 标注为单账号回退；`HYMEMORY_*` 标注 host/dev-only（镜像不含 `.[memory-hy]` SDK，故意不传）。
- 新增守卫 `tests/unit/scripts/test_deploy_env.py`（3 tests）：模板 active 键必须在 `-e` 白名单；backend 读取的已文档化键也必须在白名单；host-only 豁免项必须仍在模板中（`HYMEMORY_` 前缀、`CREATOR_STATS_MAX_BODY_VISITS`）。CLAUDE.md 部署段把错误描述「passes all env vars」改成「只转发显式 `-e` 列表，新增键三处同步」，防止同类静默失效。
- 验证：`test_deploy_env.py` 3 passed、`tests/unit/scripts` 297 passed；`deploy.sh` 用 LF 副本 `bash -n` exit=0（Windows 检出自带 CRLF 是既有事实，非本次改动引入）。
- 全量回归 **5116 passed / 14 skipped / 0 failed**（5130 collected）；`ci_local.py --skip-tests` 全 PASS。提交 `42fa2af1` 已推送，CI run **43606998996** 10 个作业 success。

