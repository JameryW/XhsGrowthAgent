# Adaptive Harness 评测集方案（提案 → 已拍板，E1 已交付）

> **状态：决策已拍板（2026-11-01），E1 已交付；E2–E4 未开始。**
> 关联：`docs/agent-os-upgrade-2026q4.md` 路线图 10（P3 = Adaptive Harness + A/B 门禁）、
> §8 Harness Benchmarks、§9 剩余工作清单。

## 0. 已拍板（2026-11-01）

| 问题 | 决定 | 对方案的影响 |
|---|---|---|
| 评测口径 | **都需要**：决策正确性 + 内容质量 | L3（质量维度）是必须项，不能只做 L1/L2 |
| 数据来源 | **真实**：真实 workflow checkpoint | 需要 E1 抽取器 + 强制脱敏；fixture 本地生成、gitignore |
| 预算 | **可配置或选择** | `--limit`/`--all`、`--phases`、可选 `--postgres-uri`/`--sqlite-path`；L3 用同一套开关 |

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

## 7. 明确不做

- 不训练/微调模型；不改线上默认路由与发布协议；不影响审批与账本语义。
- 不在没有真实预算前跑 L3。
- 不把 SKIP 当通过：F5/F7/F8 的缺口继续显式记录，直到有实现。
