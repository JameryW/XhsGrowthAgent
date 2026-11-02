# Adaptive Harness 评测集方案（提案 → 已拍板，E1/E2/E3 + E4 裁判已交付）

> **状态：E1（语料抽取）、E2（策略接口）、E3（离线 A/B 门禁）、E4 质量裁判
> （LLM-as-judge + 预算护栏）已交付；E2/E3 未接线生产默认；E4 的 live 端到端执行
> 仍是 external-only（需真实平台凭据与测试账号授权窗口）。**
> 关联：`docs/agent-os-upgrade-2026q4.md` 路线图 10（P3 = Adaptive Harness + A/B 门禁）、
> §8 Harness Benchmarks、§9 剩余工作清单。

## 0. 已拍板

| 日期 | 问题 | 决定 | 对方案的影响 |
|---|---|---|---|
| 2026-11-01 | 评测口径 | **都需要**：决策正确性 + 内容质量 | L3（质量维度）是必须项，不能只做 L1/L2 |
| 2026-11-01 | 数据来源 | **真实**：真实 workflow checkpoint | 需要 E1 抽取器 + 强制脱敏；fixture 本地生成、gitignore |
| 2026-11-01 | 预算 | **可配置或选择** | `--limit`/`--all`、`--phases`、可选 `--postgres-uri`/`--sqlite-path`；L3 用同一套开关 |
| 2026-11-02 | judge | **允许 LLM-as-judge** | E4 质量维度用 LLM 裁判；`JudgeBudget` 把调用计入预算 |
| 2026-11-02 | 预算上限 | **< 200 次模型调用** | `JudgeBudget` 默认 `max_calls=199`，先扣费后调用 |
| 2026-11-02 | L3 账号 | **测试账号** | live 执行需显式指定测试账号（external-only，未接线） |

## 1. 为什么需要评测集

架构文档对 P3 的裁定是「无评测数据前做自适应是赌博」。仓库现有三道**确定性**防线：

| 资产 | 回答的问题 | 局限 |
|---|---|---|
| `scripts/benchmarks/harness_benchmarks.py` | runtime 是否可靠（F1/F2/F4），故障注入是否被正确拦截 | F5/F7/F8 记 SKIP（并发 workspace / run 级预算 / LLM verifier 未实现） |
| `scripts/benchmarks/context_compiler_baseline.py` | 上下文编译的 token 成本与层稳定性是否漂移 | 只测编译产物，不测决策收益 |
| `scripts/benchmarks/llm_route_benchmark.py` | 新旧轻量路由的时延/结构质量对照（合成 prompt，`--live` 可选） | 单点路由对照，不是 harness 级 A/B |

它们回答「runtime 靠不靠谱」，不回答「换一个 harness 决策是否更好」。评测集要补的就是后者，
并且必须是**可离线、可复现、可作为门禁**的，否则又会变成一次性脚本。

## 2. 评测对象：变体允许改变什么

一个 Harness 变体只允许在下列决策点上与基线不同，其余一律冻结：

| 可变 | 位置（现行实现） | 说明 |
|---|---|---|
| 模型路由 | `backend/models/router.py` `resolve_model_id` | TaskType → model id |
| 上下文策略 | Context Compiler 的层/预算/裁剪顺序 | 影响 token 与召回 |
| 重试/并发/超时 | 各 node 与 Gateway 调用参数 | F7 的前置是「run 级预算字段」 |
| 升级/降级触发 | 何时换更强模型、何时降级到确定性路径 | Adaptive Harness 的核心 |

**不可变（红线）**：publish 协议与 `PublishRequest` 载荷、人工审批门、`EffectLedger`
六态语义、工具声明与 `auth_scope`。任何变体改动这些语义都应被结构测试直接判失败。

## 3. 评测集三层设计

### L1 决策回放（离线、确定性，优先）
- 输入：state/上下文 fixture（从现有 workflow checkpoint 抽取并脱敏 + 手写边界样例）。
- 断言：变体在给定输入下产生的**决策**（路由、预算、升级/降级）与预期一致。
- 判据：标为「必须」的规则 100% 一致；偏好类规则允许差异但必须报告。

### L2 工具/网关回放
- 输入：录制的 `ToolResult` 序列（成功 / timeout / domain 失败 / 结果未知）。
- 断言：结果分类、回执、账本状态与基线一致（复用 `harness_benchmarks` 的注入故障思路）。
- 判据：分类与账本状态 100% 一致——这是安全线，不做"统计上更好"的妥协。

### L3 端到端 A/B（可选，需预算与真实账号）
- 输入：小样本 workflow（真实或沙箱账号），按变体分流。
- 指标：成功率、时延（p50/p95）、成本（token/调用次数）、内容质量（rubric 或双盲 judge）。
- 判据：安全线全过，且质量/成本至少一项显著优于基线、另一项不劣化超过阈值。

## 4. 指标与门禁

| 维度 | 指标 | 建议门槛 |
|---|---|---|
| 正确性 | L1「必须」规则一致率；L2 分类/账本一致率 | 100% |
| 成本 | token / 模型调用次数相对基线漂移 | ≤ 5%（沿用 context baseline 的 drift-pct 5 口径） |
| 时延 | p50 / p95 | 不劣化 > 10% |
| 质量 | L3 rubric 或 LLM judge 双盲一致性 | ≥ 0.8（若启用 judge） |
| 安全 | 审批门/账本语义不可变 | 结构测试 + claim 扫描，任一变化即 FAIL |

## 5. 分阶段落地（每阶段独立票）

1. **E1 数据集框架**：checkpoint → fixture 抽取脚本、fixture 目录与 schema 校验（离线）。
2. **E2 变体接口**：把上面四个决策点抽成可注入策略对象，默认实现 = 现行行为，**无行为变化**。
3. **E3 A/B 门禁脚本**：跑 L1/L2 + 阈值判定，接入 `scripts/ci_local.py` 与 CI（可单独 job）。
4. **E4 L3 小样本**：需要真实账号/预算，单独审批后再做。

## 6. 需要拍板的问题（阻塞 E1/E2）

1. **评测口径**：只评决策正确性，还是必须包含内容质量？（决定 L3 是否必须）
2. **数据来源**：真实 checkpoint 抽取（需确认脱敏边界）还是纯合成？
3. **预算**：L3 每轮可接受的调用成本与样本量？
4. **judge**：允许 LLM-as-judge 吗？是否需要双盲人工复核？
5. **变体边界**：允许改线上默认路由，还是只允许 A/B 分流、默认值保持不变？
6. **门禁强度**：评测红是阻断合并，还是只产出报告供人判断？

## 6.5 E1 已交付：数据集框架（票 5cd）

`scripts/eval/extract_fixtures.py` + `scripts/eval/fixtures.py`：

| 能力 | 实现 |
|---|---|
| 真实来源 | `--sqlite-path`（默认 `.xhs/checkpoints.sqlite`）或 `--postgres-uri`；只读 `AsyncSqliteSaver`/`AsyncPostgresSaver` 的 `alist` |
| 预算可配置 | `--limit N`（默认 100）、`--all`、`--phases a,b`、`--include-messages`、`--dry-run` |
| 脱敏（唯一实现） | 标识符 → 稳定假名（`acct_/thread_/session_/user_`…）；cookie/token/api_key 等 → 空；`cdp_endpoint`/`chrome_profile_path` → 空；图片路径 → `image/NN.ext`；`messages` 默认丢弃；**内容字段保留**（质量评测需要） |
| 语料格式 | `fixture-<id>.json`（`EvalFixture`）+ `manifest.json`（计数、每文件 sha256、跳过明细）；schema/版本号显式 |
| 本地安全 | 输出目录默认 `.eval-fixtures/`（gitignore）；测试断言写入物中不含账号/线程/路径/密钥明文 |
| 验证 | `tests/unit/scripts/test_eval_fixtures.py` 10 passed（含"真实 sqlite 往返"：用 AsyncSqliteSaver 播种子后跑完整抽取管线） |

用法：

```bash
python scripts/eval/extract_fixtures.py --dry-run
python scripts/eval/extract_fixtures.py --limit 20 --phases reviewing,publishing
python scripts/eval/extract_fixtures.py --postgres-uri "$XHS_POSTGRES_URI" --all
```

**本地现实说明**：本 checkout 的 `.xhs/checkpoints.sqlite` 是空的（0 checkpoints），
因此 E1 的"真实语料"要在有数据的部署（Postgres）或已填充的 sqlite 上生成；E1 自身的
正确性由上述种子库测试覆盖，而不是靠本地空库。

## 6.6 E2 已交付：可注入策略接口（票 5ce，未接线）

`backend/harness/policy.py`（+ `backend/harness/__init__.py`）：

| 决策点 | 默认实现（= 现行行为，逐项委托） |
|---|---|
| 模型路由 | `DefaultHarnessPolicy.route_model` → `config.models.resolve_model_id` |
| 上下文预算 | `context_budget()` → `None`（今天 agents 调 `compile_prompt` 不传 budget） |
| 工具重试/并发/超时 | `tool_limits(capability)` → 工具目录 `ToolSpec.max_concurrency` / `effective_timeout_s` |
| 升级/降级触发 | `escalation_targets()` → `()`（今天只有 `MODEL_FALLBACKS` 兜底，没有升级） |

- `HarnessPolicy` 是 `runtime_checkable` Protocol；`describe(policy)` 输出**可 JSON 序列化
  的决策快照**（models / context_budget / escalation / tool_limits），E3 用它做 baseline
  与 variant 的 diff。
- **未接线**：生产代码没有任何调用点使用这个接口，因此默认行为零变化。接线（默认值是否
  允许被变体替换）依赖提案第 6 节问题 5/6 的拍板。
- 测试：`tests/unit/harness/test_policy.py` 8 passed，逐项对比 router/目录的当前答案，
  并钉住"未知名能力必须拒绝而不是编造"以及 snapshot 的 diff 行为。

## 6.7 E3 已交付：离线 A/B 门禁（票 5cf，默认只报告）

`scripts/eval/run_gate.py`：

| 检查 | 判定 |
|---|---|
| `corpus` | `.eval-fixtures/` 缺失 → **SKIP**（缺语料是缺口，不是通过，也不是红）；manifest schema 不符、文件 sha256 不匹配、fixture 的 `state_sha256` 重算不符 → 红 |
| `policy` | 默认策略的 `describe()` 必须覆盖四个决策点、每个 TaskType 都有非空模型、快照可 JSON 序列化 |
| `variant` | 仅在显式 `--variant module:factory` 时运行；输出**决策 diff**（差异是 A/B 的目的，本身不算红）；变体坏了（空路由/describe 抛错）才红 |
| `benchmarks` | 真实跑 `harness_benchmarks.py`：F1/F2/F4 必须存在且通过，任何 FAIL 都红；F5/F7/F8 若仍 SKIP 则作为缺口列出（缺口后来实现成 PASS 也不算失败） |

- **门禁强度可配置**：默认 `mode=report`，红也返回 0；`--fail-on-red` 才返回 1。这对应
  提案第 6 节问题 6 未拍板时的安全姿态——先出报告，不阻断合并。
- **变体边界**：只能通过显式 `--variant` 注入，脚本从不改生产默认值（对应问题 5 的
  A/B-only 姿态，最终拍板后如需改默认再单独接线）。
- 接入本地 runner：`python scripts/ci_local.py --only eval-gate`；无 `.eval-fixtures/` 时
  该 job 显式 SKIP（CI 无法提供本地语料，故不进 GitHub workflow）。
- 测试：`tests/unit/scripts/test_eval_gate.py` 13 passed（含"红但不阻断"与 `--fail-on-red`
  两个 CLI 姿态、篡改 fixture 必红、benchmark FAIL 必红、缺口实现成 PASS 不算失败）；
  `tests/unit/scripts/test_ci_local.py` 补 2 个用例（无语料 SKIP / 有语料运行）。

## 6.8 变体示例（票 5cg）：证明 `--variant` 注入链路可用

`scripts/eval/variants/route_lighter.py` 是一个**只改一个决策**的示例变体：
`content_analysis` 从 MiMo 路由切到较轻的 `deepseek-v4-flash`（与 POLISH/MOCK_GEN 同类）。
它不被生产代码导入，因此不可能改默认。用法：

```bash
python scripts/eval/run_gate.py --skip-benchmarks \
    --variant scripts.eval.variants.route_lighter:make_policy
```

输出 `[PASS] variant: ...; decisions changed: models`，diff 只含 `models` 一类——这钉住
了 E3 的 diff 语义（只报告变化，不把差异当红）。测试新增 2 个用例（模块加载 + CLI 注入）。

**E4 的三件事已于 2026-11-02 拍板**（judge 允许 / 预算 <200 / 测试账号），裁判与预算
护栏见 §6.9；live 端到端执行仍需部署侧凭据与账号授权窗口，不在本仓库内跑。

## 6.9 E4 质量裁判（LLM-as-judge）+ 预算护栏（票 5ch）

`scripts/eval/judge.py`：

| 组件 | 行为 |
|---|---|
| `JudgeScores` | 五维 0-10 整数（copywriting/visual/compliance/reach/audience，沿用 evaluator 维度词汇）+ rationale + bias_warning；`overall` 为均值 |
| `build_judge_prompt` | 确定性消息：system 规定只输出 JSON、禁止复述原文；human 携带 niche/title/body/visual_summary |
| `parse_judge_output` | 容忍 ```json 围栏与前后散文；缺维度/超范围/非 JSON 一律 `JudgeOutputError`（带输出预览） |
| `JudgeBudget` | 默认 `max_calls=199`（"<200" 的直译）；`consume()` **先扣费后调用**——模型崩了也不会让账目乐观；超限抛 `JudgeBudgetExceededError` |
| `judge_content(model, ...)` | 一次判定 = 一次调用；模型返回非文本/非 JSON 时该次调用仍计入预算 |

测试 `tests/unit/scripts/test_eval_judge.py` **11 passed**（假模型，无网络）：
提示词确定性、围栏/散文解析、缺维度与超范围拒绝、199 上限与先扣费语义、
预算耗尽时**不调用模型**、模型给出坏输出仍扣一次。

**仍 external-only 的部分**（如实标注，不在本仓库伪造）：真实 workflow 的 live 调用、
测试账号的登录态/凭据、平台验收窗口。`judge_content` 接受任意 chat model，接线到部署侧
只是传一个 `get_model(TaskType.EVALUATION)`。

## 6.10 L3 live 计划门闸与部署 runbook（票 5ci）

`scripts/eval/plan_l3.py` 是 live 运行的**授权门闸（只校验，不执行）**：

| 规则 | 来源 |
|---|---|
| `1 <= samples <= 50` | 单轮样本上限，避免失控实验 |
| `judge_calls = samples <= max_calls` | 每样本一次裁判 |
| `max_calls <= 199` | 用户拍板「<200 次模型调用」的直译 |
| `account` 必填 | 拍板「测试账号」 |
| `judge != none` | 拍板「决策正确性 + 内容质量都要」 |
| `XHS_EVAL_LIVE=1` | 花钱的运行必须显式武装 |

- `--armed` 不满足时 exit 1，可当脚本门禁；`--json` 输出计划（不含凭据）供留档；
- 门闸**不会**启动工作流——live 步骤属于部署环境，步骤与停止条件写在
  `docs/adaptive-harness-runbook.md`（抽语料 → E3 门禁 → plan 校验 → 测试账号跑 N 次 →
  裁判打分 → 记录/停止条件）。

## 7. 明确不做

- 不训练/微调模型；不改线上默认路由与发布协议；不影响审批与账本语义。
- 不在没有真实预算前跑 L3。
- 不把 SKIP 当通过：F5/F7/F8 的缺口继续显式记录，直到有实现。
