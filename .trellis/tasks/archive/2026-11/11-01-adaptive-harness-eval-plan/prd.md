# docs: Adaptive Harness 评测集方案（提案，待拍板）（票 5ca）

> 路线图 10（P3 = Adaptive Harness + A/B 门禁）的裁定是「无评测数据前做自适应是赌博」，
> 且文档写明「需评测集先行」。本票交付**可审的评测方案**，不含实现；六个待拍板问题
> 在方案第 6 节。

## 1. 依据（仓库现有资产）

| 资产 | 已确认的事实 |
|---|---|
| `scripts/benchmarks/harness_benchmarks.py` | F1/F2/F4 可跑（故障注入、账本/策略），F5/F7/F8 显式 SKIP；离线、CI job |
| `scripts/benchmarks/context_compiler_baseline.py` | token 成本 + 层稳定性 + drift gate（drift-pct 5） |
| `scripts/benchmarks/llm_route_benchmark.py` | 新旧轻量模型路由对照：合成 prompt、时延/token/结构质量、`--live` 才产生真实调用 |
| `docs/agent-os-upgrade-2026q4.md` §5/§8/§9 | P3 依赖评测集；F5/F7/F8 是记录在案的缺口 |

## 2. 提案内容（写入 `docs/adaptive-harness-eval-plan.md`）

1. **可变决策点**（且仅这些）：模型路由、上下文策略、重试/并发/超时、升级/降级触发。
2. **不可变红线**：publish 协议与载荷、人工审批门、EffectLedger 六态、工具声明与 auth_scope。
3. **三层评测集**：L1 决策回放（离线确定性）、L2 工具/网关回放（复用注入故障思路）、
   L3 端到端 A/B（需预算与真实账号，可选）。
4. **指标与门禁**：正确性 100%、成本漂移 ≤5%（沿用 context baseline 口径）、
   p50/p95 不劣化 >10%、质量 rubric/judge ≥0.8、安全红线结构测试。
5. **分阶段**：E1 数据集框架 → E2 变体接口（默认=现行行为）→ E3 门禁脚本接入
   `ci_local`/CI → E4 小样本 L3（单独审批）。
6. **六个待拍板问题**：评测口径、数据来源/脱敏、预算、judge 允许性、变体边界、门禁强度。

## 3. 验证

- `tests/unit/scripts`（含 docs citations/claims）：108 passed（新增文档不破坏引用规则）。
- `ruff`：绿。
- 纯文档，不改代码/默认路由。

## 4. 不做什么

- 不写评测实现、不训练模型、不改路由默认值；没有拍板前不进入 E1/E2。
