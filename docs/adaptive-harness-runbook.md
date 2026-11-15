# Adaptive Harness L3 部署侧 runbook（授权、预算与记录）

> 本文件只覆盖 **live L3**（真实账号跑端到端 + LLM 裁判）在**部署环境**里怎么跑。
> 仓库内能做的部分（语料抽取、离线门禁、裁判与预算护栏、计划校验）都已交付；
> 这里没有凭据，也不应该出现凭据。
>
> 已拍板（2026-11-02）：允许 LLM-as-judge；**每轮 <200 次模型调用**；只在**测试账号**跑。

## 0. 前置条件（缺一不可）

| 条件 | 说明 |
|---|---|
| 部署环境的测试账号 | 账号 id 已知；登录态/cookie 只存在于部署环境（`XHS_*` 凭据） |
| 运行窗口 | 平台可接受的时段；避免与真实用户的发布/私信冲突 |
| 预算批准 | 每轮**总**模型调用 **<200**（工作流 + 裁判）；`plan_l3` 用 `--calls-per-sample` 做估算校验，实测数必须记录——它不是运行时上限（F7 尚无 run 级预算字段） |
| 语料来源 | 有数据的 Postgres checkpoint（或已填充的 sqlite）**+ 同一个 Postgres Artifact Store**：真实节点会把内容字段 ref 化，抽取时必须用 `--store-uri` 解析，否则这些记录会被跳过并计入 `unresolved_artifacts` |

## 1. 抽取真实语料（在部署环境，输出不入库）

```bash
# 建议设置：用部署侧密钥做 HMAC 假名（不写入语料；不设则假名可被字典攻击）
export XHS_EVAL_REDACTION_KEY="<deployment-secret>"
python scripts/eval/extract_fixtures.py \
    --postgres-uri "$XHS_POSTGRES_URI" --store-uri "$XHS_POSTGRES_URI" \
    --limit 20 --phases reviewing,publishing
# 繁忙库可加 --scan-limit 5000 限制扫描量；若输出 scan_capped 警告，说明语料可能不完整
# 若输出出现 unresolved_artifacts 警告：store URI 不对或该线程内容缺失，先修再继续
# 记下输出里的 manifest 指纹（相当于语料的 out-of-band 摘要）
# 产物：.eval-fixtures/fixture-*.json + manifest.json + manifest.sha256（已 gitignore，别提交）
```

## 2. 跑离线门禁（先确认基线没坏）

门禁现在有七项检查（corpus / policy / l1 / l2 / thresholds / variant / benchmarks）。
l1、l2 各自读本地产物；thresholds 只有你提供 live 指标时才有值，否则显式 SKIP。

```bash
RECORDED_DIGEST="<第 1 步记下的 manifest 指纹>"

# 工具回放语料：先用 seed 生成 5 个边界 case（成功/timeout/domain/异常/结果未知）
python scripts/eval/record_tool_results.py --seed --out .eval-tool-corpus

python scripts/eval/run_gate.py            # report-only（缺语料/缺指标会 SKIP 而不是红）
python scripts/eval/run_gate.py --fail-on-red \
    --expect-manifest-sha256 "$RECORDED_DIGEST"   # 想让它阻断 + 核对 out-of-band 指纹
python scripts/eval/run_gate.py --fail-on-red \
    --tools-corpus .eval-tool-corpus \
    --metrics .eval-tmp/live-metrics.json         # live 指标到位后连同阈值一起阻断
```

期望：

- `corpus` pass（哈希完整、非空、`redaction_version`/`extractor_version` 与当前一致且
  `manifest.sha256` 存在——旧语料会被判红，重跑第 1 步即可）；
- `policy` pass、`l1` 决策与基线一致；
- `l2` pass：每个 case 的 ToolResult 分类、唯一 invoke 回执、`EffectLedger` 终态
  （ok→CONFIRMED、timeout→UNKNOWN、异常/domain→FAILED）与 `blocks_retry` 都与录制一致，
  且两次回放确定；语料缺失或为空时 SKIP（不会假装通过）；
- `thresholds`：`--metrics` 给出 live 产物后，token/调用漂移 ≤5%、p50/p95 退化 ≤10%、
  judge 一致性 ≥0.8 才 PASS；无 `--metrics` 或基线为 0 / 缺 judge 数据时 SKIP；
- `benchmarks` F1/F2/F4 状态为 PASS。

`--skip-l2` / `--skip-thresholds` 只用于明确知道这两项不适用时显式跳过（输出里会记为 SKIP，
不是静默略过）。

## 3. 校验 live 计划与预检（都不花钱）

### 3.1 授权门闸（plan_l3）

```bash
XHS_EVAL_LIVE=1 python scripts/eval/plan_l3.py \
    --samples 3 --account "<测试账号 id>" --phases reviewing \
    --calls-per-sample 5 --armed
```

- `ready: yes` 才能继续；`ready: no` 会列出原因（缺账号 / 未 set `XHS_EVAL_LIVE=1` /
  judge=none / 超过 199 / 缺 `--calls-per-sample` 调用估算）。**人审裁判也要武装**：
  只要跑 live，工作流就会花模型调用。
- **预算按总量估算**：`estimated_total_calls = samples x (1 judge + calls_per_sample)`，
  必须 ≤199。只数裁判会低估真实花费。
- 想留档：`--json > plan.json`（不含凭据，可提交到实验记录，含估算值）。

### 3.2 离线预检（live_preflight，开跑前最后一道门）

```bash
XHS_EVAL_LIVE=1 python scripts/eval/live_preflight.py \
    --samples 3 --account "<测试账号 id>" --calls-per-sample 5 --armed
```

七项检查（任一 `[BLOCK]` 即 exit 1，什么都不启动）：

| 检查 | 通过条件 | 失败含义 |
|---|---|---|
| `plan` | 复用 `plan_l3.validate`（样本/账号/裁判/总量估算/武装） | 计划本身未授权 |
| `judge_budget` | `JudgeBudget(max_calls=plan.max_calls)` 可构造且 `used == 0` | 预算护栏被绕过或复用 |
| `redaction_key` | `XHS_EVAL_REDACTION_KEY` 非空 | live 产物假名可被字典攻击 |
| `model_egress` | `MAGPIE_API_KEY` + `MAGPIE_BASE_URL` 都已设 | 裁判/工作流没有出网凭据 |
| `corpus` | `.eval-fixtures/manifest.json` 存在且至少 1 个 fixture | 跑完没有 E3 基线可比 |
| `tool_corpus` | `.eval-tool-corpus/manifest.json` 可读 —— 缺失仅 WARN | E3 的 L2 会 SKIP（不是错误） |
| `out_dir` | `--out`（默认 `.eval-live/`）在仓库外，或被 git 忽略 | live 产物可能被提交 |

- 产物目录默认 `.eval-live/`（已 gitignore）；预检用 `git check-ignore` 验证，git 不可用
  时降级为 WARN 而不是假装通过。
- 预检**不打印任何 env 值**，`--json` 只含检查名/状态/说明，可整段落进实验记录。
- 21 条单测覆盖：未武装、缺账号、judge=none、人审提示、缺脱敏键、缺 magpie、
  语料缺失/空/损坏、工具语料降级、目录未忽略/在仓库外/等于仓库根、git 不可用降级、
  预算固定 199、armed 退出码、JSON 不含凭据。

## 4. 在测试账号上跑 N 次工作流（外部执行）

用现有入口（CLI 或 API），每次记录 `thread_id`：

```bash
xhs-growth run --account-id "<测试账号 id>" --phase reviewing
# 或 POST /api/workflow/start（异步），记下返回的 thread_id
```

- 样本数 N 就是计划里的 `samples`；不要超过它在 `plan_l3` 里通过的值。
- 每次结束后确认没有进入真实发布：L3 只评估内容质量与决策，不触发对外发布动作
  （发布链路由审批门控制，runbook 不要求、也不授权绕过）。

## 5. 用裁判打分（每样本一次调用，受预算护栏约束）

在仓库根目录执行（需要部署环境的模型凭据）：

```python
import asyncio, json, sys
sys.path.insert(0, "scripts/eval")

from backend.config.models import TaskType
from backend.models import get_model
from judge import JudgeBudget, judge_content

budget = JudgeBudget()          # max_calls=199，>199 会被拒绝；先扣费后调用
SAMPLES = [
    {"thread": "t-1", "title": "标题1", "body": "正文1", "niche": "家居"},
    # ... 与 plan 的 samples 数量一致
]

async def main():
    model = get_model(TaskType.EVALUATION)
    results = []
    for sample in SAMPLES:
        scores = await judge_content(
            model,
            title=sample["title"],
            body=sample["body"],
            niche=sample["niche"],
            budget=budget,          # 必填：没有隐式预算，循环多少次就扣多少次
        )
        results.append({"thread": sample["thread"], **scores.model_dump(), "overall": scores.overall})
    print(json.dumps({"used": budget.used, "results": results}, ensure_ascii=False, indent=2))

asyncio.run(main())
```

> 护栏数的是**判定次数**：一次 `ainvoke` 内部的 provider 重试/兜底不可见，不会额外计入。
> 因此 plan 里的 `calls_per_sample` 要按工作流真实模型调用量估计，不要只算裁判。

- 输出只保留分数与 thread id；**不要把正文/账号写进仓库**。
- `used` 必须 ≤199；解析失败的那次也算一次调用，不要为同一份样本无限重试。

## 6. 记录、停止与回滚

### 6.1 停止条件

| 情况 | 动作 |
|---|---|
| `budget.used` 接近 199 | 停止新增样本，记录已完成部分 |
| 裁判输出连续解析失败 | 停止并报告（每次失败仍扣费） |
| 测试账号异常/平台告警 | 立即停止，不重试 |
| 结果与基线差异 | 用 E3 的 `describe()`/diff 报告解释，不要直接改默认路由（问题 5 未拍板） |

### 6.2 回滚预案（按需执行，全部在部署侧）

1. **停工作流**：CLI 前台 Ctrl-C；异步运行用
   `POST /api/workflow/cancel/<thread_id>`（或 `xhs-growth` 对应入口）取消，记下
   `thread_id` 与取消时刻。
2. **关测试账号会话**：关闭浏览器/登录态与临时资料，不在平台留下待发布草稿。
3. **不触发发布**：L3 只评估内容质量与决策；发布链路由审批门控制，任何"顺手试发"
   都不在本 runbook 的授权范围内。若已误触，立即按平台人工撤回流程处理并记入复盘。
4. **记账**：汇总 `budget.used` + 工作流实测调用数，与 plan 的估算对比（估算是口径，
   实测是事实；两者都要记录）。
5. **写复盘**：24 小时内把停止原因、花费、产物路径写进 journal；不改默认路由、
   不动发布协议。

### 6.3 live 数据留存与脱敏规则

| 类别 | 规则 |
|---|---|
| `.eval-live/` 产物 | 已 gitignore；**不提交、不进 CI artifact、不贴到 issue/PR** |
| 账号标识 | 用 `XHS_EVAL_REDACTION_KEY` 做 HMAC 假名（预检强制）；不写平台 uid 明文 |
| 正文/图片 | judge 的 rationale 可能引用原文，**默认不提交**；要留档先人工检查并摘要化 |
| 敏感字段 | cookie/token/平台返回敏感字段一律不落盘；日志只留 thread 假名 |
| 留存期 | 原始上下文与逐样本 rationale 在部署机保留 ≤30 天，到期删除；汇总指标（样本数、`used`、各维度 PASS/FAIL/评分）可长期保留 |
| 实验记录 | `plan.json`（预检/计划报告）不含凭据，可提交；`--json` 报告同样只含检查名/状态/说明 |

## 7. 明确不做

- 不在 CI 里跑 live L3（无凭据、会产生费用）。
- 不把 cookie/token/真实正文写进仓库或日志（`.eval-fixtures/`、`plan.json` 均不提交正文）。
- 不提交 `.eval-live/` 产物（预检强制其 gitignore；见 §6.3）。
- 不因为 L3 结果直接改生产默认路由：默认变更需要单独拍板。
