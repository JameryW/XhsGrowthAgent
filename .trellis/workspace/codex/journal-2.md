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
