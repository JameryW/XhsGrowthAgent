# feat(eval): L3 live 计划门闸 + 部署 runbook（票 5ci）

> E4 里剩下的是 **live** 端到端执行：它需要部署环境的测试账号、登录态、平台窗口和真实
> 模型调用费用，本仓库跑不了。本票交付两件不花钱但能防止事故的东西：
> **授权门闸**（把用户拍板的预算/账号/裁判条件变成可执行校验）与**部署 runbook**
> （把外部步骤写成可审计的清单，而不是某人的 shell 历史）。

## 1. 交付

| 文件 | 作用 |
|---|---|
| `scripts/eval/plan_l3.py` | live 运行授权门闸（只校验不执行）：`1<=samples<=50`、`judge_calls=samples<=max_calls<=199`、`account` 必填、`judge!=none`、`XHS_EVAL_LIVE=1`；`--armed` 不满足 exit 1；`--json` 输出可留档计划 |
| `tests/unit/scripts/test_eval_plan_l3.py` | 11 个用例：完整计划 ready、未武装阻断、缺账号阻断、200 上限阻断、样本边界、judge=none 阻断、预算不足、human judge 只提示不阻断、报告 JSON、CLI armed/json 两个姿态 |
| `docs/adaptive-harness-runbook.md` | 部署侧 live L3 步骤：抽语料 → E3 门禁 → plan 校验 → 测试账号跑 N 次 → 裁判打分（JudgeBudget 199）→ 记录与停止条件；明确不存凭据、不提交正文、不因结果直接改默认路由 |
| `docs/adaptive-harness-eval-plan.md` §6.10 | 门闸规则与来源表 |

## 2. 顺手修复的脱敏漏洞（同一轮，独立于门闸）

审计 E1 时发现 `redact_state` 的两个真实缺口，已修：

1. **密钥形状的键若值是容器**，旧逻辑会继续走进容器——`{"api_key": {"value": "sk-..."}}`
   的内层键名是无辜的，于是密钥被保留。现在密钥形状的键一律整段置空（含容器）；
2. **标识符非字符串**（列表/嵌套）时旧逻辑直接走进容器；现在字符串→假名、字符串列表→
   假名列表、其他→置空，并计数。

新增 2 个用例钉住这两点（`test_a_secret_shaped_key_never_leaks_through_a_container_value`、
`test_identifiers_keep_their_shape_without_keeping_the_value`）。

## 3. 验证

- `test_eval_plan_l3.py`：11 passed；`test_eval_fixtures.py`：12 passed；
- 实跑 `plan_l3.py --json`：缺账号 + 未武装时 `ready:false` 并列出原因；
- docs/claim 门禁与全量 pytest 见 notes（本轮含 E4 裁判与 E3 门禁的完整回归）。

## 4. 不做什么

- 不执行 live 运行、不接触凭据、不写任何账号信息；
- 不改 E3 门禁默认强度；不改生产默认路由。
