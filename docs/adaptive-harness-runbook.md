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
# 若输出出现 unresolved_artifacts 警告：store URI 不对或该线程内容缺失，先修再继续
# 记下输出里的 manifest 指纹（相当于语料的 out-of-band 摘要）
# 产物：.eval-fixtures/fixture-*.json + manifest.json + manifest.sha256（已 gitignore，别提交）
```

## 2. 跑离线门禁（先确认基线没坏）

```bash
RECORDED_DIGEST="<第 1 步记下的 manifest 指纹>"
python scripts/eval/run_gate.py            # report-only
python scripts/eval/run_gate.py --fail-on-red \
    --expect-manifest-sha256 "$RECORDED_DIGEST"   # 想让它阻断 + 核对 out-of-band 指纹
```

期望：`corpus` pass（哈希完整、非空、`redaction_version`/`extractor_version` 与当前一致且
`manifest.sha256` 存在——旧语料会被判红，重跑第 1 步即可）、`policy` pass、
`benchmarks` F1/F2/F4 状态为 PASS。

## 3. 校验 live 计划（授权门闸，不花钱）

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

## 6. 记录与停止条件

| 情况 | 动作 |
|---|---|
| `budget.used` 接近 199 | 停止新增样本，记录已完成部分 |
| 裁判输出连续解析失败 | 停止并报告（每次失败仍扣费） |
| 测试账号异常/平台告警 | 立即停止，不重试 |
| 结果与基线差异 | 用 E3 的 `describe()`/diff 报告解释，不要直接改默认路由（问题 5 未拍板） |

## 7. 明确不做

- 不在 CI 里跑 live L3（无凭据、会产生费用）。
- 不把 cookie/token/真实正文写进仓库或日志（`.eval-fixtures/`、`plan.json` 均不提交正文）。
- 不因为 L3 结果直接改生产默认路由：默认变更需要单独拍板。
