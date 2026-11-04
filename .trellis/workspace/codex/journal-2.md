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
