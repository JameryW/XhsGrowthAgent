# Agent OS 架构升级：从 Harness 到可持久执行（2026Q4）

> 输入：Harness Engineering 深入分析（二）——确定性内核 + 概率性智能、任务契约、
> Brain/Hands/History 分离、Effect 账本、Context Compiler、自适应 Harness。
> 本文是**在本仓库已落地能力上的差距审计与升级路线**，不是对原文的复述。
> 每条判定都对应代码位置；与假设相悖的结论单独标注。

## 0. 结论先行

1. 本仓库不是"从零建 Agent OS"，而是**已经处于阶段 2（Execution-Centric）的中段**：
   LangGraph checkpoint 是状态权威，租约覆盖接管边界，Context Compiler 有
   L0-L5 与漂移门禁，Tool Runtime 有双失败模式，publish 有确定性幂等键与
   UNKNOWN 处理。
2. **真正的 P0 缺口只有两个**：
   - **Effect 账本只覆盖 publish 一个工具**，没有 PREPARED→IN_FLIGHT→
     CONFIRMED/UNKNOWN/RECONCILING 的统一状态机与对账动作；
   - **没有 Progress Detector**：`revise_content` 回路只靠轮次上限兜底，
     无法区分"第 3 次修改在变好"与"第 3 次修改在原地打转"。
3. **不建议**引入 Temporal 或重写内核：LangGraph checkpoint + 租约已提供
   等价语义（节点级重放成立）；缺口在节点内部的 Attempt/Effect 粒度，
   补这两个实体即可，不需要换执行引擎。
4. **一条必须先写下来的边界**（ADR-0007）：checkpoint 是恢复的唯一权威，
   EventStore 是 telemetry，**永远不能**作为恢复依据。当前代码守住这条线
   （`backend/state/events.py` 的 best-effort 契约），升级不得破坏它。

## 1. 四层判断在本仓库的落位

原文的四层区分（Harness / Loop / Workflow Engine / Agent OS）在本仓库的实际
落位如下——四层都已存在，但成熟度不同：

| 层 | 本仓库载体 | 成熟度 | 证据 |
|---|---|---|---|
| Agent Harness | `backend/agents/*` + `backend/context/compiler.py` + `backend/tools/runtime/` + policy gate | **高**：prompt 分层编译、工具 schema 层、策略门、双失败模式 | P1b 基线门禁、`tool-runtime.md` 三条不可回退决定 |
| Agent Loop | `backend/graph/builder.py` 的 revise 回路 + 各 agent 内部结构化重试 | **中**：有回路，无进展判定 | `revise_content` 节点、`_llm_structured` 重试 |
| Workflow Engine | LangGraph checkpoint 4.1.1 + 租约（`docs/execution-plane.md`） | **中高**：节点级重放、接管边界明确；S4 单进程降级已裁定 | checkpoint 迁移、租约拒绝事件（`lease_refused`） |
| Agent OS | `backend/workflow/*` + 多账号/多线程 + `services/privacy_retention` | **低**：无跨任务调度、无资源配额、无生命周期治理 | 单进程现实（execution-plane §3） |

结论：**下一步不是补"层"，而是补"层与层之间的协议"**——Attempt/Effect 的
身份协议、进展信号协议、验收证据协议。

## 2. 五实体映射与缺口

原文要求区分 Task / Run / Step / Attempt / Effect。本仓库现状：

| 实体 | 现状载体 | 判定 |
|---|---|---|
| Task | `thread_id`（workflow 实例） | 有，但"同 thread 多次 /start"会覆盖语义，run 边界不可见 |
| Run | **无独立实体** | **缺口**：resume 与 rerun 无法从 ID 区分 |
| Step | graph node（superstep） | 有，checkpoint 天然记录 |
| Attempt | 节点内 `with_retry` 的隐式计数 | **缺口**：没有 attempt_id，也没有 attempt 级事件 |
| Effect | `publish_id` 幂等键（`backend/agents/publisher.py`） | **半有**：仅 publish，状态机只有 published/unknown/failed |

关键判断（与原文一致）：**Attempt 与 Effect 不能混用**。当前 publish 幂等键
已经做对了一半——`compute_publish_id(account + content + images + window)` 是
逻辑动作的稳定键，重试复用；但它没有独立的 `effect_id` 命名与账本表，
状态也没有 `RECONCILING`。

## 3. 差距矩阵（原文十条 → 本仓库）

| # | 原文主张 | 本仓库现状 | 差距等级 |
|---|---|---|---|
| 1 | 事件驱动状态机，不是追加 Chat Message | checkpoint 是状态、EventStore 是 telemetry；agent 层无 chat 追加 | ✅ 已满足 |
| 2 | Task/Run/Step/Attempt/Effect 五实体 | Task/Step 有；Run/Attempt 缺；Effect 仅 publish | ⚠️ 部分 |
| 3 | Event Log 是事实、Snapshot 是物化视图、Context 是临时视图 | 三者已分离（checkpoint / events / compiler） | ✅ 已满足 |
| 4 | Replay 不重调 LLM，读已提交决策 | **节点级成立**（superstep 完成即不重跑）；**节点内不成立**（节点重试会重调 LLM） | ⚠️ 部分（见 §4） |
| 5 | Effect Ledger + UNKNOWN ≠ FAILED | P0-B 已落地六态账本（§5.1）；publish 全量接入；对账仍为"记录 + ContentHistory 匹配"，无自动平台查询 | ✅ 已满足（对账增强留 P1） |
| 6 | Context Compiler（P0-P5 优先级 + provenance） | L0-L5 分层、budget、stability 门禁已有；P1-A 补齐 trust_class / verified / ttl / source_version 与可选标注渲染（§5.2）；trust 尚未参与 rerank | ✅ 已满足（排序融合留 P1 后续） |
| 7 | Memory Promotion Pipeline | hy-memory 有 LLM 抽取 + reconciler，无"来源验证→去重→晋升"显式流水线 | ❌ 缺（P1/P2） |
| 8 | 多 Agent 并行按 Artifact 分工 + Workspace 冲突 | 当前为单 Agent 串行图；无子 Agent、无并发 workspace | ❌ 缺（P2，先不建） |
| 9 | Model Gateway 按阶段路由 + Verifier 触发公式 | `backend/models/router.py` 按 TaskType 路由 + fallback/retry；无预算/风险策略，无 verifier | ⚠️ 部分（P2） |
| 10 | Adaptive Harness Controller + A/B 门禁 | 无；有 P1b 基线门禁可作为回归基础设施 | ❌ 缺（P3，需评测集先行） |

## 4. 与假设相悖的两条结论（诚实披露）

**4.1 "节点级重放"掩盖了节点内的不确定性。**

LangGraph checkpoint 只保证**已完成的 superstep 不重跑**。节点失败重试时，
节点内部的 LLM 调用会重新执行——同一输入可能得到不同输出。原文的判断
（"内核可以调用 LLM，但不能假设同一请求恢复时产生相同输出"）在这里
**部分不成立**：我们确实没有持久化"节点内已提交的决策"。

当前可接受的三个理由：
- 节点级幂等由 artifact seam 兜底（`_artifact_seam`）；
- 外部副作用只有 publish 一条，且有稳定幂等键；
- 其余节点重试是"重算幂等"的（纯函数式输入→输出）。

**触发升级的条件**：一旦出现第二个外部副作用工具（发评论、发私信），
就必须把 attempt 级"决策记录"补上，否则会重演"重试导致重复动作"。

**4.2 "Event Log 作为恢复依据"在本仓库不成立，且不应成立。**

`backend/state/events.py` 明确 best-effort（"emitting is telemetry. Nothing in
a workflow node may fail because an event could not be stored."）。原文主张
Event Log 是事实记录——在我们的架构里，这个角色由 **checkpoint + artifact**
承担，events 只服务于观测与审计。ADR-0007 固化这一分工，防止未来有人
把 events 当恢复源（那会引入"telemetry 丢失导致不可恢复"的故障模式）。

## 5. 升级路线（按杠杆排序）

| 优先级 | 切片 | 交付 | 为何是现在 |
|---|---|---|---|
| **P0-A（本次）** | Progress Detector | `backend/state/progress.py` 纯函数库 + `kind:"progress"` 事件契约 + 单测 | 零行为变更即可先观测；为 revise 回路提供"是否在变好"的客观信号 |
| **P0-B（已完成）** | 统一 Effect 账本 | `backend/state/effects.py` 六态账本；publish 成为第一个消费者（下文 §5.1） | 第二个外部副作用工具出现前必须完成，否则 F2 类故障会重演 |
| **P1-A（已完成）** | Context Provenance 扩展 | `ContextItem` 增加 `trust_class / verified / ttl_seconds / source_version`；渲染可选标注（默认关闭，基线零漂移）（§5.2） | 外部网页/记忆注入风险随 hy-memory 接入上升 |
| P1-B | Verifier 触发 | 按风险分级（发布前强制、草稿按期望成本 `p_e·p_d·L > C_v`） | 有 acceptance_signoff 人工验收作基线 |
| P2 | 子 Agent 并行（按 Artifact 分工） | 仅当出现明确的独立验收产物时启动 | 当前串行图无瓶颈证据，不提前建 |
| P3 | Adaptive Harness | 依赖评测集 + A/B 门禁；P1b 基线是起点 | 无评测数据前做自适应是赌博 |

### 5.1 P0-B 落地记录（统一 Effect 账本）

| 项 | 实现 |
|---|---|
| 状态机 | `PREPARED → IN_FLIGHT → CONFIRMED / FAILED / UNKNOWN`；`UNKNOWN ↔ RECONCILING → CONFIRMED / FAILED`；`FAILED → IN_FLIGHT`（新一次尝试） |
| 阻塞规则 | `IN_FLIGHT / CONFIRMED / UNKNOWN / RECONCILING` 阻塞重试；**`PREPARED`（仅意图）与 `FAILED`（明确未生效）不阻塞** |
| 领取语义 | `EffectLedger.begin()` 一次完成读 + 判 + 写 IN_FLIGHT；被拦时抛 `EffectBlockedError`（携带记录，供调用方写拒绝结果） |
| 乐观锁 | `mark(..., expect_version=N)` 拒绝覆盖并发写入；**诚实边界：BaseStore 无 CAS，多写者部署需数据库唯一约束**（代码注释已写明） |
| 旧词兼容 | 读侧归一化 `published → CONFIRMED`、未知状态 → `UNKNOWN`（绝不落 FAILED）；历史行零迁移 |
| publish 接入 | 提交前写 `PREPARED`（意图落盘）→ `begin()` 领取 → 成功 `CONFIRMED` / 确定失败 `FAILED` / 提交后无判定 `UNKNOWN`（显式写入，不再靠"保持不写"隐含） |
| 行为等价 | 既有 53 项 publish 测试全绿；对外 `publish_result.status` 词表（published/failed/unknown）未变 |

### 5.2 P1-A 落地记录（Context Provenance）

| 项 | 实现 |
|---|---|
| 数据面 | `ContextItem` 新增 `trust_class`（`internal_fact / memory / external_document / model_generated / unspecified`）、`verified`、`ttl_seconds`、`source_version`，全部带默认值（additive） |
| 默认值 | `trust_class=unspecified`、`verified=False` —— 未标注的生产者不得被呈现为可信 |
| 生产方标注 | `item_to_context_item`：content_history → `INTERNAL_FACT`，其余三命名空间 → `MEMORY`；hy-memory 召回 → `MEMORY` + `verified=False` |
| 渲染 | `compile(..., annotate_provenance=True)` 追加单行标签 `[source=… trust=… verified version=… ttl=…]`；**默认 False** —— P1b 基线钉住渲染字节，开启标注必须是显式迁移（同一次改动刷新快照） |
| 零漂移证明 | `context_compiler_baseline.py --compare --drift-pct 5` → `drift within threshold`，107 项 context 测试全绿 |
| 未做（诚实边界） | trust 尚未进入 rerank 排序；`verified=True` 本切片无任何生产者（没有可校验的来源），字段先就位 |

## 6. P0-A 切片设计：Progress Detector

### 6.1 问题

`revise_content` 回路目前只有"最大轮次"兜底。第 3 次修改可能是因为审核意见
在收敛，也可能是在同一处反复失败。两种情况的正确处置不同（继续 vs 升级人工），
但系统无法区分。

### 6.2 设计原则

- **只读事件，不改行为**：本切片不接入任何 agent，不改变图；先让信号可观测。
- **证据优先于计数**：判定依据是"错误指纹重复 / 工具输出重复 / 验收项无变化"，
  不是"执行了多少次"。
- **结构化输出**：返回 dataclass，携带 evidence，便于事件与前端消费。

### 6.3 信号规则（首批两条，纯事件可得）

| 信号 | 判定 | 依据 |
|---|---|---|
| `same_error_repeated` | 连续 N 条事件携带相同 error fingerprint | llm/tool 事件的 `error` 字段归一化 |
| `tool_output_repeated` | 连续 N 条工具事件的输出摘要相同 | payload 的稳定摘要（sha256 前 16 位） |

预留但暂不实现（需要验收数据接入）：
`budget_without_acceptance`、`revised_without_improvement`。

### 6.4 接口

```python
detect_progress(events, *, window=3) -> ProgressSignal
# ProgressSignal(stalled: bool, reason: str, evidence: dict, window: int)
```

### 6.5 验收

- 单测覆盖：无停滞、错误重复、输出重复、窗口边界、异构事件混入；
- ruff / mypy 通过；
- 不新增依赖，不改变任何现有调用路径。

## 7. 状态权威分工（ADR-0007 摘要）

| 持有者 | 权威内容 | 禁止 |
|---|---|---|
| LangGraph checkpoint | 任务生命周期、superstep 状态、中断点 | 存 telemetry / 大对象 |
| Artifact store | 结果与证据（artifact seam） | 存流程控制 |
| EventStore | 观测与审计时间线（best-effort） | **作为恢复依据** |
| Graph store（publish.idempotency） | 外部副作用的逻辑键与结果 | 存与副作用无关的状态 |
| Context Compiler | 每次调用的临时上下文（编译产物） | 回写状态 |

## 8. 验证矩阵（对应原文 Harness Benchmark Suite）

当前可测：F2（publish UNKNOWN 不重复发布，已有测试）、F7（预算耗尽保存状态，
已有 interrupt）、F6（契约变更 → 重新验收，部分有 acceptance）。

待补：F1（LLM 调用期间崩溃 → 安全恢复）、F3（Sandbox 重建）、F4（外部工具
恶意指令 → 权限不绕过）、F5（并发 workspace 冲突）、F8（Verifier 误放行 → 独立回归识别）。

F1/F3 的测试前提是节点内 attempt 记录（P0-B），**不先做 P0-B 就无法诚实地测 F1**。
