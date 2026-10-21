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
2. **真正的 P0 缺口只有两个**（审计时点；均已落地，见 §5）：
   - **Effect 账本只覆盖 publish 一个工具**，没有 PREPARED→IN_FLIGHT→
     CONFIRMED/UNKNOWN/RECONCILING 的统一状态机与对账动作 → **已补**：P0-B 统一
     六态账本 + 票 5c 的互动账本（`engagement_effects`，提交前 claim）；
   - **没有 Progress Detector**：`revise_content` 回路只靠轮次上限兜底，
     无法区分"第 3 次修改在变好"与"第 3 次修改在原地打转" → **已补**：P0-A
     （`backend/state/progress.py`，§5.5）。
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
| Effect | publish：`publish_id` + P0-B `EffectLedger`；互动两条：票 5c `engagement_effects` | **有**（两条路径）：PREPARED → IN_FLIGHT → CONFIRMED / FAILED / UNKNOWN（↔ RECONCILING）；键在提交动作前 claim |

关键判断（与原文一致）：**Attempt 与 Effect 不能混用**。当前两条外部副作用路径都已经有
独立的 Effect 层：publish 是 `compute_publish_id(account + content + images + window)`
（逻辑动作的稳定键，重试复用）+ P0-B 六态 `EffectLedger`（含 `RECONCILING`）；互动两条是
票 5c 的 `engagement_effects`（键 `eng:{kind}:{account_id}:{target_id}:{sha256[:16]}`，在
提交前 claim）。仍然缺的是 **Attempt 实体本身**（没有 attempt_id / attempt 级事件）——
Effect 与 Attempt 的分离在实现上成立，在命名与遥测上不成立。

## 3. 差距矩阵（原文十条 → 本仓库）

| # | 原文主张 | 本仓库现状 | 差距等级 |
|---|---|---|---|
| 1 | 事件驱动状态机，不是追加 Chat Message | checkpoint 是状态、EventStore 是 telemetry；agent 层无 chat 追加 | ✅ 已满足 |
| 2 | Task/Run/Step/Attempt/Effect 五实体 | Task/Step 有；Run/Attempt 缺；Effect 有 publish（P0-B 六态）+ 互动两条（票 5c `engagement_effects`） | ⚠️ 部分 |
| 3 | Event Log 是事实、Snapshot 是物化视图、Context 是临时视图 | 三者已分离（checkpoint / events / compiler） | ✅ 已满足 |
| 4 | Replay 不重调 LLM，读已提交决策 | **节点级成立**（superstep 完成即不重跑）；**节点内不成立**（节点重试会重调 LLM） | ⚠️ 部分（见 §4） |
| 5 | Effect Ledger + UNKNOWN ≠ FAILED | P0-B 已落地六态账本（§5.1）；publish 全量接入；票 5c 为互动两条加上 `engagement_effects`（提交前 claim）；对账仍为"记录 + ContentHistory 匹配"，无自动平台查询 | ✅ 已满足（对账增强留 P1） |
| 6 | Context Compiler（P0-P5 优先级 + provenance） | L0-L5 分层、budget、stability 门禁已有；P1-A 补齐 trust_class / verified / ttl / source_version 与可选标注渲染（§5.2）；trust 尚未参与 rerank | ✅ 已满足（排序融合留 P1 后续） |
| 7 | Memory Promotion Pipeline | hy-memory 有 LLM 抽取 + reconciler，无"来源验证→去重→晋升"显式流水线；设计 PRD 已出：verify → dedupe → promote、封闭拒因、append-only ledger、observe-only 先行切片（`.trellis/tasks/10-21-memory-promotion-pipeline/prd.md`） | ⚠️ 设计已定、未实现（P1） |
| 8 | 多 Agent 并行按 Artifact 分工 + Workspace 冲突 | 当前为单 Agent 串行图；无子 Agent、无并发 workspace | ❌ 缺（P2，先不建） |
| 9 | Model Gateway 按阶段路由 + Verifier 触发公式 | P1-B Verifier 触发（§5.3）+ P2 恢复策略分派（§5.4）；`router.py` 仍按 TaskType 路由，无阶段/推理预算矩阵 | ⚠️ 部分（Verifier ✅ / 恢复分派 ✅ / 阶段路由 P2） |
| 10 | Adaptive Harness Controller + A/B 门禁 | 无；有 P1b 基线门禁可作为回归基础设施 | ❌ 缺（P3，需评测集先行） |

## 4. 与假设相悖的两条结论（诚实披露）

**4.1 "节点级重放"掩盖了节点内的不确定性。**

LangGraph checkpoint 只保证**已完成的 superstep 不重跑**。节点失败重试时，
节点内部的 LLM 调用会重新执行——同一输入可能得到不同输出。原文的判断
（"内核可以调用 LLM，但不能假设同一请求恢复时产生相同输出"）在这里
**部分不成立**：我们确实没有持久化"节点内已提交的决策"。

当前可接受的三个理由：
- 节点级幂等由 artifact seam 兜底（`_artifact_seam`）；
- **可及的外部副作用已有 3 条**（`xhs.publish`，加票 5f 注册的 `xhs.comment_reply` /
  `xhs.dm_send`），三条都有稳定 effect 键、且都在**提交动作前 claim**（publish 走 P0-B
  幂等账本；互动两条走票 5c 的 `engagement_effects`）—— 重试撞的是账本，不是平台；
- 其余节点重试是"重算幂等"的（纯函数式输入→输出）。

**触发升级的条件（票 5f 后重述）**：原文写的是"出现第二个**能到达 agent 的**外部副作用
工具（发评论、发私信）"。5f 把互动两条注册进目录后，这句话**按字面已经成立**（可及面
1 → 3，见 §4.1.1）；但它守护的性质——"重试导致重复动作"——没有随之失守：两条新能力都
要求提交前 effect claim，5f 又钉了 `max_attempts=1` 与逐条审批闸门。因此判据改为：
**出现一条不经 effect 级 claim 的外部副作用路径**（新工具直接写平台/服务，或现有路径在
claim 之前就发出请求），那才是 attempt 级决策记录必须补上的时刻。

#### 4.1.1 这条前提的实测边界（2026-10-19 复核；2026-10-20 票 5f 后同步第一行）

上一版这条写的是"外部副作用只有 publish 一条"。用 AST 把整棵树数一遍后，**这句话只在
"目录可及"这一层成立**（下表为 2026-10-19 实测；票 5f 之后第一行的数字已变，见行内注）：

| 层 | 数量 | 内容 |
|---|---|---|
| 目录（agent 可经 Gateway 到达） | **1 → 3**（票 5f） | 2026-10-19 时 `xhs.publish` 是唯一声明为 `SIDE_EFFECTING` 的能力；票 5f 把 `xhs.comment_reply` / `xhs.dm_send` 注册进目录，可及面变成 3 条。后两者**没有任何 `.invoke` 调用点**，也没有任何 agent 的 `tool_capabilities` 声明它们——可及 ≠ 被调用；集合由 `test_catalogue_audit.py::test_the_reachable_side_effecting_surface_is_three_capabilities` 从 `build_registry()` 复算 |
| `backend/tools/**` 里写**平台**的 `@tool` | **2** | `comment_replier`（回复真实评论）、`dm_handler`（发真实私信）—— 都走 `XHSEngagement` → CDP → 平台。票 5f 起它们在**目录里**（经 Gateway + effect 账本 + 审批闸门），静态导入者仍为零 |
| 声称会写、其实是 stub | 2 | `post_scheduler`、`ab_test_manager` 只返回 canned 结果（`post_scheduler` 注释自己写着"需接 APScheduler"） |
| 写**本仓服务**（非平台） | 2 | `ripple_cancel_simulation`、`ripple_generate_report` |
| 有外部通知 | 1 | `escalation_flagger`（配了 webhook 时发通知，不写平台） |

结论（票 5f 后重述）：**"可及面 1 条"已过期** —— 注册后 agent 可经 Gateway 到达 3 条
`SIDE_EFFECTING` 能力，但其中两条没有任何调用点，"可及"与"被调用"仍是两件事。模块里能
真正改外部状态的有 5 条（2 条写平台、2 条写本仓的 Ripple 服务、1 条发通知），另有 2 条
stub 只在返回值上假装会写。

这件事现在由 `backend/tools/runtime/audit.py::audit_tool_catalogue` **守**：26 个
`@tool` 里每一个都必须是"已注册"或"已登记（`UNGATED_TOOLS`，含它到底能写什么）"，
新出现的第 27 个会直接让单测变红；登记项与目录指向的函数若消失也会红。
**票 5f 之后未登记的平台写集合是空的**（`platform_writes == ()` 被测试钉住），可及面是
3 条 `SIDE_EFFECTING`；`test_catalogue_audit.py` 从 `build_registry()` 复算这个集合——
**它变大的那天，本节与 attempt 级决策记录的判据都要一起重审。**

**4.2 "Event Log 作为恢复依据"在本仓库不成立，且不应成立。**

`backend/state/events.py` 明确 best-effort（"emitting is telemetry. Nothing in
a workflow node may fail because an event could not be stored."）。原文主张
Event Log 是事实记录——在我们的架构里，这个角色由 **checkpoint + artifact**
承担，events 只服务于观测与审计。ADR-0007 固化这一分工，防止未来有人
把 events 当恢复源（那会引入"telemetry 丢失导致不可恢复"的故障模式）。

## 5. 升级路线（按杠杆排序）

| 优先级 | 切片 | 交付 | 为何是现在 |
|---|---|---|---|
| **P0-A（已完成）** | Progress Detector | `backend/state/progress.py` 纯函数库 + `kind:"progress"` 事件契约 + 单测；已接入结构化重试循环（log-only，§5.5）与 revise 回路（`detect_revision_stall`，§5.7） | 零行为变更即可先观测；为 revise 回路提供"是否在变好"的客观信号 |
| **P0-B（已完成）** | 统一 Effect 账本 | `backend/state/effects.py` 六态账本；publish 成为第一个消费者（下文 §5.1） | 第二个外部副作用工具出现前必须完成，否则 F2 类故障会重演 |
| **P1-A（已完成）** | Context Provenance 扩展 | `ContextItem` 增加 `trust_class / verified / ttl_seconds / source_version`；渲染可选标注（默认关闭，基线零漂移）（§5.2） | 外部网页/记忆注入风险随 hy-memory 接入上升 |
| **P1-B（已完成）** | Verifier 触发 | `backend/services/verification_policy.py`：风险下限 + 期望成本公式 + 预算降级；真实发布路径发射判定事件（§5.3） | 有 acceptance_signoff 人工验收作基线 |
| **P2-部分（已完成）** | 恢复策略分派 | `backend/models/recovery_policy.py`：按错误类型分派 retry/degrade/escalate/stop，retry 层记录决策（§5.4） | 文章 recovery 表可直接落地，且不需要多模型路由矩阵 |
| P2 | 子 Agent 并行（按 Artifact 分工） | 仅当出现明确的独立验收产出时启动；**证据采集器已就绪（§5.6）** | 当前串行图无瓶颈证据，不提前建 |
| **P3-前置（已完成）** | Harness Benchmarks 套件 | `scripts/benchmarks/harness_benchmarks.py` + CI job：F1/F2/F4 可跑，F5/F7/F8 记 SKIP（§8） | 评测集是 Adaptive Harness 的前提；先把确定性防线变成可跑的 gate |
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

### 5.3 P1-B 落地记录（Verifier 触发）

| 项 | 实现 |
|---|---|
| 决策函数 | `decide(VerificationInput) → VerificationDecision`（required / tier / reason / expected_benefit） |
| 风险下限 | CRITICAL（真实发布等不可逆外部副作用）→ 强制 `HUMAN`；HIGH → 至少 `DETERMINISTIC`。**下限先于公式判定**——低错误概率不能买通高风险门 |
| 期望成本 | `p_e·p_d·L > C_v` 才验证；MEDIUM/HIGH 正收益落 `LLM` 档，LOW 落 `DETERMINISTIC` 档 |
| 预算降级 | 预算不够所选档位时降到 `DETERMINISTIC` 并标 `budget_exhausted`；**绝不静默跳过有下限的检查** |
| 事件 | 新增 `kind:"verification"`（已注册 `EVENT_KINDS`）；真实发布路径在领取 Effect 后发射判定，纯观测、零行为变更 |
| 诚实边界 | `p_e/p_d` 是输入先验（仓库暂无校准评估集）；`LLM` 档是决策槽位，本仓库尚无独立 verifier 实现（接入是独立变更，需评测门槛） |

### 5.4 P2-部分落地记录（恢复策略分派）

| 项 | 实现 |
|---|---|
| 四档动作 | `RETRY_SAME`（429/5xx/网络）/ `DEGRADE_MODEL`（400/422/schema/结构化解析失败）/ `ESCALATE_MODEL`（同错误重复 = stalled）/ `STOP_AND_REPORT`（401/403/内容策略/重试预算耗尽） |
| 优先级 | **拒绝优先**：401/403/策略拒绝即使同时"像瞬时错误"也直接 STOP——重试拒绝就是绕过路径 |
| 与 retry 层一致 | 一致性测试：`retry._is_retryable(exc)` 为真 ⇔ 分类为 `RETRY_SAME`（两张规则表不允许漂移） |
| 接入 | `retry._RetryChatModel` 的放弃路径记录分类（log-only，行为零变更） |
| 诚实边界 | `DEGRADE/ESCALATE` 是决策，不是执行——tier 切换需要模型矩阵配置，暂无（`action_available=False` 时 ESCALATE 降级为 RETRY_SAME，不撒谎） |

### 5.5 P0-A 接线记录（结构化重试循环）

Progress Detector 此前只有单测消费者。接入 `BaseAgent._llm_structured` 的内层重试：

| 项 | 实现 |
|---|---|
| 事件构造 | 每次 payload 被拒 → 一个 `{"kind":"llm","error": correction}` 事件；两次相同 correction 即判 `same_error_repeated` |
| 判定窗口 | `window=2`（与 `attempts_per_level` 默认值对齐） |
| 联动 | stalled 时调用 `classify_recovery(..., stalled=True)`，日志标出建议动作（`degrade_model`——重复 schema 失败换结构化模式，与文章 bad_arguments 分支一致） |
| 行为 | **零变更**：重试预算仍决定是否继续；变化只是日志从"又拒了一次"变成"这条在打转，指纹=…" |

### 5.6 P2 证据采集器（Node Latency Report）

P2 的启动条件是"瓶颈证据"。证据不能靠猜，所以先把遥测变成判定：

| 项 | 实现 |
|---|---|
| 聚合 | `backend/services/node_latency.py`：按 agent 统计 calls / total / mean / p95 / max / share / errors |
| 串行度 | `serial_ratio = Σ节点耗时 / 墙钟`：`[0.9, 1.05]` → **node_bound**（时间全在节点里，加并集无收益）；`>1.05` → **parallel_time_present**（节点区间已重叠）；`<0.9` → **waiting_not_parallel**（时间花在等待/审批，不是可并行的活） |
| 热点 | 单 agent 占比 ≥ 40% 时点名 |
| 无数据 | `has_data=False` + `verdict=no_data`——**不编造零值**；CLI 退出码 0（"没有数据"是结论，不是失败） |
| 用法 | `python scripts/benchmarks/node_latency_report.py --events run.json` 或 `--thread <id>` |

样例判定（5 节点合成数据）：`serial ratio 1.00 → node_bound，hotspot: strategist 43%`
——即"当前图是纯串行，且半壁时间在 strategist"，这正是启动 P2 前需要看到（或推翻）的事实。

### 5.7 P0-A 第二半（revise 回路进展信号）

§5.5 只接了**节点内部**的重试循环；§6.1 的问题陈述是**跨节点**的
evaluator→revise_content→copywriter 回路——那里才是"第 3 次修改在变好还是原地
打转"真正发生的地方。这一片把信号接到它本来要回答的问题上：

| 项 | 实现 |
|---|---|
| 轮次记录 | `revision_record(round_no, evaluation)` → `{round, score, hints_digest, decision, degraded}`；**存摘要不存正文**（hint 文本已在 `evaluation_result`，append-only 历史里再存一份会让 checkpoint 每轮增长且无法脱敏） |
| 状态字段 | `XHSGrowthState.revision_history`（additive，`_append_list`）；无 router 读取，轮次上限仍是唯一裁决者 |
| 规则一 | `same_hints_repeated`：尾部 `window` 轮 verdict 的 hint 摘要相同（非空）——同一个"改这里"，改完还是同一个"改这里" |
| 规则二 | `revised_without_improvement`：尾部 `window` 轮 panel 分数增益 < `min_gain`（默认 1 分 / 100）——吐槽点换了，数字没动 |
| 降级轮 | `score=None`（panel degraded）**不参与分数规则**：没人量过 ≠ 没进步 |
| 人类重置 | 人工 `revise` resume 会把 `revision_count` 归零，轮号因此重启；检测按**连续轮号**取尾部 epoch，重置处自动断开，不跨 epoch 比较 |
| 行为 | **零变更**：`revision_count` / `copy_content` / `visual_plan` / hints 透传全部原样；stalled 时只写 `kind:"progress"` 事件 + warning 日志 |
| 诚实边界 | 分数来自本仓 panel（LLM judge），`min_gain=1.0` 是**先验**不是校准值；`budget_without_acceptance` 仍不实现（state 无 run 级预算，与 §8 F7 的 SKIP 同因） |

### 5.8 信号读面（Signal Inventory）

前六片全是"先观测"：node/llm 遥测（P1a）、effect/action 拒绝（P0-B/P2a）、
verification 判定（P1-B）、progress 信号（P0-A ×2）。**但没有任何读面把它们
当成一条时间线读回来**——"这轮 stall 了几次 / 走的哪档验证 / 几个动作被拒"
只能靠手工翻 JSON，等于"观测层建好了，判决还是凭印象"。

| 项 | 实现 |
|---|---|
| 聚合 | `backend/services/signal_inventory.py`：按 `kind` 计数 + progress 的 reason 直方图 + verification 的 tier/reason 直方图 + action 拒绝分类 |
| 只做查找不做判断 | 计数是事实；"这回路太慢"需要本模块没有的基线 ⇒ 明确不评分、不排序、不推荐 |
| 不编造零值 | 无事件 → `has_data=False`（不是"0 次 stall"）；**"没观测到"与"观测到没有问题"是两条事实** |
| 无 kind 条目 | 按全仓口径计为 `node`，并**单独报数**（S2 之前的条目），不悄悄合并 |
| 未知 kind | 出现在 `unknown_kinds` 并照常计数 —— 这就是 #676 那类声明漂移的唯一可见出口 |
| 坏条目 | 非 mapping 的条目计数后跳过，不抛错（部分导出也是证据） |
| 样本 | progress 只回显前 3 条 `{reason, window, evidence, thread_id}`；完整计数不受影响 |
| 用法 | `python scripts/benchmarks/signal_inventory.py --events run.json` 或 `--thread <id>`；无数据退出码 0 |

`--thread` 走 `load_perf_log`（legacy-aware 的唯一正确读法），因此 S2 之前
把遥测写在 checkpoint 里的线程也能读。集成测试直接用真实发射器
（`node_perf_entry` / `progress_event` / `verification_event`）写一遍再读回来
—— 手写 dict 的单测防不住"字段改名"，真实发射器能。

## 6. P0-A 切片设计：Progress Detector

### 6.1 问题

`revise_content` 回路目前只有"最大轮次"兜底。第 3 次修改可能是因为审核意见
在收敛，也可能是在同一处反复失败。两种情况的正确处置不同（继续 vs 升级人工），
但系统无法区分。

### 6.2 设计原则

- **只读事件，不改行为**：先让信号可观测（后续已接入结构化重试的日志面，§5.5）。
- **证据优先于计数**：判定依据是"错误指纹重复 / 工具输出重复 / 验收项无变化"，
  不是"执行了多少次"。
- **结构化输出**：返回 dataclass，携带 evidence，便于事件与前端消费。

### 6.3 信号规则（首批两条，纯事件可得）

| 信号 | 判定 | 依据 |
|---|---|---|
| `same_error_repeated` | 连续 N 条事件携带相同 error fingerprint | llm/tool 事件的 `error` 字段归一化 |
| `tool_output_repeated` | 连续 N 条工具事件的输出摘要相同 | payload 的稳定摘要（sha256 前 16 位） |

两条验收导向规则的状态（2026-10-19 更新）：

- `revised_without_improvement` —— **已落地**（§5.7）。它的输入不是"验收"数据，
  而是 revise 轮自带的 panel 分数与 revision hints；设计时以为要等外部验收，
  实际本仓的 evaluator 每轮已经给了。
- `budget_without_acceptance` —— 仍不实现：state 里没有 run 级预算字段，
  编一个会让信号看起来比它实际知道的更多（同 §8 F7 的 SKIP）。

### 6.4 接口

```python
detect_progress(events, *, window=3) -> ProgressSignal
detect_revision_stall(rounds, *, window=2, min_gain=1.0) -> ProgressSignal  # §5.7
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

`scripts/benchmarks/harness_benchmarks.py` 是可跑的确定性矩阵（CI job：
`Harness Benchmarks`），对生产代码注入故障：

| 项 | 状态 | 证据 |
|---|---|---|
| F1 崩溃恢复 | ✅ 可跑 | IN_FLIGHT 无判定 → 新 ledger（模拟重启）begin 被拦，不重复提交 |
| F2 响应丢失 | ✅ 可跑 | UNKNOWN 阻塞、FAILED 释放；attempt 递增 |
| F4 权限不被绕过 | ✅ 可跑 | 双自动门（审核自动 + 发布自动）必拒；单门放行（两半都断言） |
| F5 并发 workspace | ⏭ SKIP | 仓库尚无子 Agent/并发 workspace |
| F7 预算耗尽 | ⏭ SKIP | state 无 run 级预算字段 |
| F8 Verifier 误放行 | ⏭ SKIP | 尚无 LLM verifier 实现（P1-B 只交付触发） |

SKIP 是**记录在案的缺口，不是通过**——脚本单独打印 skip 清单，只对 FAIL
返回非零退出码。F1 的边界：这里测的是**副作用层**恢复（账本）；节点内 LLM
决策仍未持久化（§4.1 已披露），F1 的 full 版本需要 attempt 级决策记录。
