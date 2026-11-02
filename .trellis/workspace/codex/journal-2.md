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
