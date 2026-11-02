# fix(eval): 独立审查修复——真实 schema 脱敏、预算不可绕过、空语料必红（票 5cj）

> 独立审查（subagent，只读）发现 2 个高危 + 多个中危，全部是**真问题**：
> E1 的脱敏是 8 个键的精确 denylist，真实 schema 里 `workflow_thread_id`、blogger
> nickname、reviewer 邮箱、profile 链接都会原样进 fixture；E4 的 199 调用护栏是**可选
> 参数**，循环 300 次也不会触发；E3 空语料能拿到 `[PASS]` 并在 `--fail-on-red` 下 exit 0。
> 本票逐条修复并补回归测试。

## 1. 高危修复

| 问题 | 修复 |
|---|---|
| 真实 schema 身份字段泄漏（`PublishResult.workflow_thread_id`、`BloggerProfile.nickname/avatar_url`、`CompetitorPost.author`、`ShootingPlan.creator_nickname/profile_link`、`HumanFeedback.reviewer`、`post_id/note_id/post_url`） | 标识符表扩充到这些真实字段（thread/user/creator/post 假名）；`*_url`/`*_link` 一律清空；路径类键（`*_path`/`*_image`/`image_paths`/`images`）规范化为 `image/NN.ext`；任意字符串值命中绝对路径（Windows 盘符 / `/Users`/`/home`/…）→ 清空并计数 |
| `JudgeBudget` 可被 `max_calls=10**9` 绕过；`judge_content(budget=None)` 每次新建 199 预算 | `JudgeBudget` 拒绝 >199（`ValueError`）；`budget` 改为**必填**；docstring 写明 provider 内部重试不计入 |

## 2. 中危修复

| 问题 | 修复 |
|---|---|
| 空语料 `[PASS]`、`--fail-on-red` 也不红 | `total == 0` → 红 |
| 旧脱敏版本语料永远绿 | manifest `redaction_version` 必须等于当前值，否则红（`SCHEMA/REDACTION/EXTRACTOR` 均升到 2） |
| 未列入 manifest 的 `fixture-*.json` 被忽略 | 枚举目录，出现未列出文件 → 红 |
| required benchmark 只看「存在且非 FAIL」（`SKIP`/`ERROR` 也算过） | F1/F2/F4 必须 `PASS`；未知状态 → 红 |
| `check_policy` 只查真值（空白字符串/`0`/`[ "" ]` 也算答案） | 模型 id 必须非空字符串；`context_budget` None 或非负 int；`escalation` 任务→字符串列表；`tool_limits` 条目形状与类型 |
| 决策完全相同的 variant 显示 PASS（接线错误无法发现） | `--variant` 且 diff 为空 → 红 |
| `mode=gate` 只表示「传了 variant」，与阻断无关 | mode 由 `--fail-on-red` 决定（`report`/`block`） |
| `--include-messages` 在真实 checkpoint 上把 BaseMessage 塞进 redact → 0 fixture、exit 0，且 docstring 与事实矛盾 | **移除该开关**：messages 永远丢弃；schema 升 v2 |
| 抽取器 `aiosqlite.connect` + `setup()` 会创建空库，"只读/不写"是假的；路径打错得到 0 fixture + exit 0 | 先 `is_file()` 检查（不存在报错），再用 `mode=ro` URI 打开；捕获 `sqlite3.OperationalError` |
| `alist(None)` 忽略 `checkpoint_ns`，subgraph checkpoint 可能成为线程「最新」 | 跳过非空 ns，计入 `subgraph_checkpoint` |
| `--phases` 放行空 phase 的 fixture | `if phases and fixture.phase not in phases` → 跳过 |
| `plan_l3` 只数裁判调用，50 样本"≤199"仍可严重超支 | 新增 `--calls-per-sample` 必填，按 `samples x (1 + calls_per_sample) <= 199` 校验；报告输出估算总量 |

## 3. 验证

- `test_eval_fixtures.py`：14 passed（新增真实 schema 泄漏回归、绝对路径护栏、空 phase 过滤、
  subgraph 跳过、manifest 版本）
- `test_eval_gate.py`：23 passed（空语料/旧脱敏版本/未列出文件/篡改 hash 必红、F1 SKIP 必红、
  决策相同 variant 必红、policy 类型检查、report/block 姿态）
- `test_eval_judge.py`：12 passed（含 >199 预算拒绝）
- `test_eval_plan_l3.py`：13 passed（含总量预算、缺估算阻断）
- `test_ci_local.py`：eval-gate 带 `--fail-on-red`
- `tests/unit/scripts` 全量、docs 门禁、全量 pytest 见 notes

## 4. 不做什么

- 不做 live 执行；不引入 out-of-band manifest 签名（低危，记录在审查结论里未实现）；
- 不改生产默认路由；不接受 >199 的任何"覆盖"参数。
