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

> **实现状态（2026-11-14）**：已实现 —— `scripts/eval/decision_replay.py` + E3 的 `l1` 检查。
> 「预期」= 基线策略（`DefaultHarnessPolicy`，即现行代码路径）+ 强制不变量：四个决策点齐全、
> model id 非空、预算 None/非负整数、escalation 目标非空且不重复、tool limits 形状不变、
> 两次回放必须一致（非确定性策略判红）。与基线的任何差异按 fixture **逐字段**报告为
> preference diff（不判红，这正是 A/B 要看的证据）；未传 `--variant` 却偏离基线判红
> （基线回放必须与自身一致）。依赖语料：无 `.eval-fixtures/` 时该检查显式 **SKIP**
> （与 corpus 检查同一口径，缺语料不是通过）。**仍未实现**：L2 工具/网关回放（需要录制的
> `ToolResult` 序列）与 §4 的成本/时延/质量阈值判定。

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

> **实现状态（诚实标注，2026-11-14 更新）**：**L1 决策回放已实现**（见 §3 的 L1 段与
> §6.7 的 `l1` 检查：按 fixture 回放四个决策、强制不变量、确定性与基线 preference diff）。
> 但上表的**成本/时延/质量阈值判定与 L2 工具/网关回放仍未实现**；E3 仍按 §6.7 执行
> corpus / policy / variant / benchmarks 四项既有门禁，阈值计算属于 E4 live 实验
> （外部执行）的产出。

## 5. 分阶段落地（每阶段独立票）

1. **E1 数据集框架**：checkpoint → fixture 抽取脚本、fixture 目录与 schema 校验（离线）。
2. **E2 变体接口**：把上面四个决策点抽成可注入策略对象，默认实现 = 现行行为，**无行为变化**。
3. **E3 A/B 门禁脚本**：跑 L1/L2 + 阈值判定，接入 `scripts/ci_local.py` 与 CI（可单独 job）。
   *实际交付范围：corpus 完整性 / **L1 决策回放（2026-11-14 补）** / policy 快照 / variant diff /
   harness benchmarks 五项门禁；L2 回放与阈值判定尚未实现（见 §4 实现状态说明）。*
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
| 真实来源 | `--sqlite-path`（默认 `.xhs/checkpoints.sqlite`，以 `mode=ro` 只读打开；路径不存在直接报错，不再创建空库）或 `--postgres-uri`；两者都走 `alist`，并跳过非空 `checkpoint_ns` 的 subgraph checkpoint。**真实节点经 `artifact_seam` 把内容字段 ref 化**：必须用 `--store-uri` 打开 Artifact Store 解析；无 store 或解析不出的记录不会写成"无内容 fixture"，而是跳过并计入 `unresolved_artifacts`。`alist` 默认读取**全部** checkpoint，繁忙库请用 `--scan-limit` 限制扫描量（会记录 `scan_capped` 警告，表示语料可能不完整） |
| 预算可配置 | `--limit N`（默认 100）、`--all`、`--phases a,b`、`--scan-limit N`（限制**读取**的 checkpoint 数）、`--dry-run`；`--phases` 选的是"该线程在目标 phase 内最新的 checkpoint" |
| 脱敏（唯一实现） | 标识符 → 稳定假名（`acct_/thread_/session_/user_/creator_/post_/run_/target_/id_`，覆盖 `workflow_thread_id`、`platform_post_id`、`run_id`、`target_id`、`ids`、`reviewer`、`confirmer`、`confirmed_by`、`nickname`、`author`、`post_id/note_id` 等真实 schema 字段）；cookie/token/api_key 等 → 空（含容器值）；`*_url(s)`/`*_link(s)`/`*_uri(s)` 链接 → 空；`cdp_endpoint`/`chrome_profile_path` → 空；路径类键 → `image/NN.ext`；任意字符串命中绝对路径（盘符、UNC `\\\\`、`file://`、`/Users`/`/home`/`/tmp`/`/var`/`/opt`/`/root`/`/mnt`/`/data`/`/srv`/`/private`）→ 空；`messages` **总是丢弃**；`artifacts` 引用映射 → 丢弃；**内容字段保留** |
| 语料格式 | `fixture-<id>.json`（`EvalFixture`）+ `manifest.json`（计数、每文件 sha256、跳过明细、schema/extractor/redaction 版本、`pseudonym_mode`）+ `manifest.sha256`（manifest 字节指纹）；schema v2 / redaction v3 / extractor v3 |
| 本地安全 | 输出目录默认 `.eval-fixtures/`（gitignore）；**可选 HMAC 假名**：`XHS_EVAL_REDACTION_KEY` 由部署侧提供、不写入语料，manifest 记录 `pseudonym_mode=sha256|hmac`，无密钥时打印"短 id 可被字典攻击"警告；`hmac` 是**声明**，仓库内无法验证（密钥不能进语料）；`manifest.sha256` 必需（缺失即红），`--expect-manifest-sha256` 做 out-of-band 核对 |
| 验证 | `tests/unit/scripts/test_eval_fixtures.py` **26 passed**（真实 sqlite 往返、两轮真实 schema 身份字段回归、绝对路径护栏、artifact 解析/跳过、**artifact 写缝（refify_updates）回归**、Postgres 入口契约、扫描上限、加盐模式与指纹、**sqlite/Postgres 两条入口都使用项目 checkpoint serde**） |
| Checkpoint 反序列化 | 两条入口都传 `backend.state.checkpoint_serde.checkpoint_serde()`（与 graph 同一 `allowed_msgpack_modules` 白名单，票 5cz）；否则真实 checkpoint 会持续打印 "unregistered type `backend.state.enums.WorkflowPhase`"，并在 LangGraph 收紧后把决策字段降级成裸字符串——语料正好丢掉的正是它要保存的字段 |

用法：

```bash
python scripts/eval/extract_fixtures.py --dry-run
python scripts/eval/extract_fixtures.py --limit 20 --phases reviewing,publishing
python scripts/eval/extract_fixtures.py --postgres-uri "$XHS_POSTGRES_URI" --all
```

**本地现实说明（2026-11-14 复核）**：本 checkout 的 `.xhs/checkpoints.sqlite` **不再是空库**
——实测 **27 checkpoints / 5 threads**，`--dry-run` 可抽出 **5 条** fixture，另有 **10 条**
checkpoint 的内容字段在 Artifact Store（`--store-uri`）里、本地解析不出而被跳过；
runbook 推荐的 `--phases reviewing,publishing` 在本地当前得到 **0 条**（17 条被 phase 过滤）。
所以本地没有 `.eval-fixtures/` 的原因是「抽取器没有被运行 + 部分内容需要部署侧 Artifact Store」，
而不是「无数据可抽」。E3 的 corpus 检查在本地仍是 **SKIP**（缺语料是缺口，不是通过）；
E1 自身的正确性由 26 个种子库测试覆盖。

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
- 测试：`tests/unit/harness/test_policy.py` 9 passed，逐项对比 router/目录的当前答案，
  并钉住"未知名能力必须拒绝而不是编造"以及 snapshot 的 diff 行为。

## 6.7 E3 已交付：离线 A/B 门禁（票 5cf，默认只报告）

`scripts/eval/run_gate.py`：

| 检查 | 判定 |
|---|---|
| `corpus` | `.eval-fixtures/` 缺失 → **SKIP**（缺语料是缺口，不是通过）；**空语料（0 fixture）→ 红**；manifest schema / `redaction_version` / `extractor_version` 不符 → 红；`manifest.sha256` 缺失且未给 `--expect-manifest-sha256` → 红；指纹不匹配 → 红；传 `--expect-manifest-sha256` 与该值不符 → 红（out-of-band 才能发现"fixture+manifest+指纹成对重写"）；出现未列入 manifest 的 `*.json` → 红；文件 sha256 不匹配、fixture 的 `state_sha256` 重算不符 → 红 |
| `policy` | `describe()` 必须覆盖四个决策点（快照含 `context_budgets` 逐 phase 采样，阶段专属预算的变体也可见）；每个 TaskType 的模型 id 必须是**非空字符串**；`context_budget` 与每个 phase 预算为 None 或非负整数；`escalation` 必须是「任务 → 非空字符串列表」；`tool_limits` 条目的 `capability` 非空、`max_concurrency` 为 None 或 ≥0 的 int、`timeout_s` 为 None 或 >0；快照可 JSON 序列化 |
| `l1` | 逐 fixture 回放四个决策（model 路由 / 该 phase 的 context budget / escalation / tool limits）：**强制不变量**（路由非空、预算 None 或非负 int、escalation 非空且不重复、tool limits 形状、JSON 可序列化）任一违反 → 红；**两次回放不一致**（非确定性策略）→ 红；与基线的差异按 fixture 逐字段进 `l1_diff`（preference，不判红）；未传 `--variant` 却偏离基线 → 红。语料缺失 → **SKIP**（缺语料是缺口，不是通过）；`--skip-l1` 显式 SKIP |
| `variant` | 仅在显式 `--variant module:factory` 时运行；输出**决策 diff**（差异是 A/B 的目的，不算红）；**决策完全相同 → 红**（多半是工厂返回了默认策略，属于接线错误）；变体坏了（空路由/describe 抛错）也红 |
| `benchmarks` | 真实跑 `harness_benchmarks.py`：F1/F2/F4 必须**状态为 PASS**（仅仅存在不算），任何 FAIL 或未知状态红；F5/F7/F8 若仍 SKIP 则作为缺口列出（缺口后来实现成 PASS 不算失败） |

- **门禁强度可配置**：`mode` 反映是否阻断（默认 `report`，红也返回 0；`--fail-on-red` 时
  `mode=block` 并返回 1），与是否传 `--variant` 无关。这对应提案第 6 节问题 6 未拍板时的
  安全姿态——先出报告，不阻断合并。
- **变体边界**：只能通过显式 `--variant` 注入，脚本从不改生产默认值（对应问题 5 的
  A/B-only 姿态，最终拍板后如需改默认再单独接线）。
- 接入本地 runner：`python scripts/ci_local.py --only eval-gate`；该 job 在无 `.eval-fixtures/`
  时显式 SKIP，有语料时以 `--fail-on-red` 运行（CI 无法提供本地语料，故不进 GitHub workflow）。
- 副作用（如实记录）：不跳过 benchmarks 时，`run_gate.py` 会把 harness 输出写到仓库内
  `.eval-tmp/`（gitignored）——沙箱禁止管道 stdio，用文件重定向是刻意设计，不是"只读门禁
  却在写仓库"的缺陷。
- 测试：`tests/unit/scripts/test_eval_gate.py` 29 passed（覆盖面：空语料/旧脱敏或抽取器
  版本/未列出 JSON/篡改 hash/缺失指纹必红、policy 类型与逐 phase 预算校验、F1 SKIP 必红、
  决策相同的 variant 必红、report/block 两个 CLI 姿态、真实 variant 注入）；
  `tests/unit/scripts/test_eval_l1.py` **16 passed**（L1：基线回放干净、预算变体降级为
  preference diff、无 `--variant` 偏离基线必红、空路由/重复 escalation/非确定性必红、
  缺语料 SKIP、空语料 SKIP、不可读语料红、gate 集成与 `--skip-l1` 姿态）；
  `tests/unit/scripts/test_ci_local.py` 覆盖无语料 SKIP / 有语料带 `--fail-on-red` 运行。

## 6.8 变体示例（票 5cg，5cn 随 #756 调整）：证明 `--variant` 注入链路可用

`scripts/eval/variants/phase_budget.py` 是一个**只改一个决策**的示例变体：把
`publishing` 阶段的 context budget 设为 4000。它不被生产代码导入，因此不可能改默认。

> **为什么不是"换路由"**：#756 之后所有任务都经 magpie 网关落到同一个上游
> （`magpie-deepseek-v4.1-flash`），直连 DeepSeek 已禁用，"路由到更轻的直连模型"不再是
> 一个真实决策；而逐 phase 预算仍是 harness 自己的决策，且 E2 会采样
> `context_budget(phase=...)`，因此这个变体在 diff 里恰好只出现一类。

用法：

```bash
python scripts/eval/run_gate.py --skip-benchmarks \
    --variant scripts.eval.variants.phase_budget:make_policy
```

输出 `[PASS] variant: ...; decisions changed: context_budgets`，diff 只含
`context_budgets` 一类——这钉住 E3 的 diff 语义（只报告变化，不把差异当红）。测试覆盖
模块加载（含具体 phase 值）与 CLI 注入。

**E4 的三件事已于 2026-11-02 拍板**（judge 允许 / 预算 <200 / 测试账号），裁判与预算
护栏见 §6.9；live 端到端执行仍需部署侧凭据与账号授权窗口，不在本仓库内跑。

## 6.9 E4 质量裁判（LLM-as-judge）+ 预算护栏（票 5ch）

`scripts/eval/judge.py`：

| 组件 | 行为 |
|---|---|
| `JudgeScores` | 五维 0-10 整数（copywriting/visual/compliance/reach/audience，沿用 evaluator 维度词汇）+ rationale + bias_warning；`overall` 为均值 |
| `build_judge_prompt` | 确定性消息：system 规定只输出 JSON、禁止复述原文；human 携带 niche/title/body/visual_summary |
| `parse_judge_output` | 容忍 ```json 围栏与前后散文；缺维度/超范围/非 JSON 一律 `JudgeOutputError`（带输出预览） |
| `JudgeBudget` | 默认 `max_calls=199`；**上限不可绕过**：>199 直接 `ValueError`，`max_calls` 构造后只读（赋值抛 `AttributeError`），`used` 必须满足 `0 <= used <= max_calls`（负计数同样被拒）；`consume()` **先扣费后调用**；超限抛 `JudgeBudgetExceededError` |
| `judge_content(model, ..., budget=...)` | `budget` **必填**（隐式预算会让循环 N 次各"独立合规"）；一次判定 = 一次调用；模型返回非文本/非 JSON 时该次调用仍计入预算；provider 内部重试/兜底不可见，不计入此护栏（已在 docstring 写明） |

测试 `tests/unit/scripts/test_eval_judge.py` **13 passed**（假模型，无网络）：
提示词确定性、围栏/散文解析、缺维度与超范围拒绝、199 上限与先扣费语义、
预算耗尽时**不调用模型**、模型给出坏输出仍扣一次、**>199 的预算被拒绝**、
**`used` 负值/越界被拒绝且 `max_calls` 构造后不可改**。

**仍 external-only 的部分**（如实标注，不在本仓库伪造）：真实 workflow 的 live 调用、
测试账号的登录态/凭据、平台验收窗口。`judge_content` 接受任意 chat model，接线到部署侧
只是传一个 `get_model(TaskType.EVALUATION)`。

## 6.10 L3 live 计划门闸与部署 runbook（票 5ci）

`scripts/eval/plan_l3.py` 是 live 运行的**授权门闸（只校验，不执行）**：

| 规则 | 来源 |
|---|---|
| `1 <= samples <= 50` | 单轮样本上限，避免失控实验 |
| `calls_per_sample >= 1` 必填 | 工作流自身的模型调用必须计入预算，不能只数裁判 |
| `estimated_total_calls = samples x (1 judge + calls_per_sample) <= max_calls` | 「<200 次模型调用」的**总量口径**；它是**估算不是运行时上限**（F7 尚无 run 级预算字段），必须记录实测调用数 |
| `max_calls <= 199` | 用户拍板「<200 次模型调用」的直译 |
| `account` 必填 | 拍板「测试账号」 |
| `judge != none` | 拍板「决策正确性 + 内容质量都要」 |
| `XHS_EVAL_LIVE=1` | **任何** live 运行（不论裁判是 LLM 还是人）都会花模型调用，必须显式武装 |

- `--armed` 不满足时 exit 1，可当脚本门禁；`--json` 输出计划（不含凭据）供留档；
- 门闸**不会**启动工作流——live 步骤属于部署环境，步骤与停止条件写在
  `docs/adaptive-harness-runbook.md`（抽语料 → E3 门禁 → plan 校验 → 测试账号跑 N 次 →
  裁判打分 → 记录/停止条件）；
- 测试：`tests/unit/scripts/test_eval_plan_l3.py` 15 passed（含总量估算、缺失调用估算、
  human 裁判也需武装、estimate_basis 不是上限、armed/json 两个 CLI 姿态）。

## 7. 明确不做

- 不训练/微调模型；不改线上默认路由与发布协议；不影响审批与账本语义。
- 不在没有真实预算前跑 L3。
- 不把 SKIP 当通过：F5/F7/F8 的缺口继续显式记录，直到有实现。
