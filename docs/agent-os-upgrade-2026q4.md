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
     六态账本 + 票 5c 的互动账本（`engagement_effects`：DB 级唯一约束 + 提交前 claim）；
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
| Task | `thread_id`（workflow 实例） | **有**：Task 即 `thread_id`（`/start` 每次生成新 id，`backend/api/routes/_wf_application.py:178`）；run 边界见 Run 行（票 5x） |
| Run | `run_id` + `run_seq` + `kind:"run"` 事件（票 5x，`backend/state/runs.py`） | **有**：`/start` 铸造 seq=1；pause/error resume 与 `/recover` 复用；completed/cancelled terminal restart 铸造新 `run_id`（seq+1，cause=`rerun`）。legacy 线程无 stamp 时 status 回显 null |
| Step | graph node（superstep） | 有，checkpoint 天然记录 |
| Attempt | 节点内结构化重试：`attempt_id` + `kind:"attempt"` 事件（票 5w，`backend/state/attempts.py`） | **有**：每次（档位 × 重试序号）一条事件，封闭 outcome（succeeded / payload_rejected / semantic_rejected / unreachable）、数据最小化、确定性 id。**节点内重试仍会重调 LLM**（§4.1 未变：本切片只补身份与遥测，不是重放） |
| Effect | publish：`publish_id` + P0-B `EffectLedger`；互动两条：票 5c `engagement_effects`（DB 级唯一约束账本 + CAS 状态迁移） | **有**（两条路径）：publish 走 PREPARED → IN_FLIGHT → CONFIRMED / FAILED / UNKNOWN（↔ RECONCILING）；互动两条在提交动作前 claim |

关键判断（与原文一致）：**Attempt 与 Effect 不能混用**。当前两条外部副作用路径都已经有
独立的 Effect 层：publish 是 `compute_publish_id(account + content + images + window)`
（逻辑动作的稳定键，重试复用）+ P0-B 六态 `EffectLedger`（含 `RECONCILING`）；互动两条是
票 5c 的 `engagement_effects`（键 `eng:{kind}:{account_id}:{target_id}:{sha256[:16]}`，在
提交前 claim；持久层是 DB 级唯一约束账本 —— `(account_id, idempotency_key)` UNIQUE +
`INSERT ... ON CONFLICT DO NOTHING`，状态迁移走 CAS：`backend/db/engagement_effects.py` +
`backend/services/xhs_effect_ledger.py`）。Attempt 实体已由票 5w 补上（`attempt_id` + attempt 级事件）；
**Run 已由票 5x 补上**（`run_id` / `run_seq` / cause 词表；resume 复用、rerun 铸造），行 2 的五实体现已齐。

## 3. 差距矩阵（原文十条 → 本仓库）

| # | 原文主张 | 本仓库现状 | 差距等级 |
|---|---|---|---|
| 1 | 事件驱动状态机，不是追加 Chat Message | checkpoint 是状态、EventStore 是 telemetry；agent 层无 chat 追加 | ✅ 已满足 |
| 2 | Task/Run/Step/Attempt/Effect 五实体 | Task/Step 有；**Attempt 有**（票 5w）；**Run 有**（票 5x：`run_id` + `kind:"run"`，resume 复用 / rerun 铸造）；Effect 有 publish（P0-B 六态）+ 互动两条（票 5c `engagement_effects`） | ✅ 已满足 |
| 3 | Event Log 是事实、Snapshot 是物化视图、Context 是临时视图 | 三者已分离（checkpoint / events / compiler） | ✅ 已满足 |
| 4 | Replay 不重调 LLM，读已提交决策 | **节点级成立**（superstep 完成即不重跑）；**节点内不成立**（节点重试会重调 LLM） | ⚠️ 部分（见 §4） |
| 5 | Effect Ledger + UNKNOWN ≠ FAILED | P0-B 已落地六态账本（§5.1）；publish 主链全量接入（`backend/agents/publisher.py`；free.py 经单一执行入口 `execute_mainline_publish`），**creator_agent 控制面 execute 路径也已接入六态账本**（票 5bi：dispatch 前 `EffectLedger.begin`，按 outcome mark CONFIRMED/UNKNOWN/FAILED；重复/不明 attempt 以 typed 409 拒绝）；票 5c 为互动两条加上 `engagement_effects`（提交前 claim）；**票 5ai**：本地对账确认（幂等行 / ContentHistory）已写账本 `UNKNOWN→RECONCILING→CONFIRMED`；uncertain 不动账本；**票 5ak**：本地均 miss 且 title 非空时，创作者中心笔记列表标题精确匹配 → 同路径确认账本（`source=platform_note_list`）；**票 5al**：默认 fetcher 最多拉 3 页（`page_size=50`，空页/短页提前停）；无 cookie / 拉列表失败 / 未命中 → uncertain；**票 5am**：`/publish-retry` reconciled 早退同步 checkpoint `publish_result`→`published`（与账本同形）；**笔记详情页深查 / CDP 仍可后续** | ✅ 已满足（主链 + 控制面 execute 均过账本；详情页深查可后续） |
| 6 | Context Compiler（P0-P5 优先级 + provenance） | L0-L5 分层、budget、stability 门禁已有；P1-A 补齐 trust_class / verified / ttl / source_version 与可选标注渲染（§5.2）；票 5ad 起 `rerank_items` 乘 `TRUST_RERANK_WEIGHTS`（`verified`/TTL 仍不进排序） | ✅ 已满足 |
| 7 | Memory Promotion Pipeline | hy-memory 有 LLM 抽取 + reconciler，无"来源验证→去重→晋升"显式流水线；**四片 + 人审写入 + TTL / policy_version / 样本阈值 / 语义近邻 hint 已落**：A 纯决策协议；B 账本 + observe + 管理面 + 调用者；C 独立重读 + 首次机晋升 + provenance 透传；D hy 候选机器 REVIEW（`promotion_hy.py`）；票 5y `POST .../memory-promotions/{id}/review` 人审 `approved`/`dismissed`（`promotion_review.py`，human-authored 账本行，不重跑 `decide_promotion`）；票 5z 全 ns 默认 `ttl_seconds=null`（`promotion_ttl.py`，只靠 supersede）；票 5aa `DEFAULT_PROMOTION_POLICY_VERSION` + `default_promotion_policy()`（Git 常量权威，无 env/远端）；票 5ab `DEFAULT_PROMOTION_MIN_SAMPLES=5`（对齐 `CreativeMemory.MIN_SAMPLES`，无冷却）；票 5ac 仅 `NEEDS_REVIEW` 后语义近邻 hint（`promotion_semantic.py`，unavailable → skip-hint，永不自动合并）。PRD §9 开放项已清空 | ✅ 已满足（P1） |
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

票 5w 给节点内尝试补上了 **Attempt 身份与 attempt 级事件**（§5.9），但**这没有满足上面的
判据，也没有让 §4.1 成立**：事件只说明"第几次尝试、结果类别、耗时"，不保存模型输出、不
改变重试路径，重试仍会重调 LLM。判据要求的是"决策可重放"，身份与遥测只是它的前提。

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
| **P1-A（已完成）** | Context Provenance 扩展 | `ContextItem` 增加 `trust_class / verified / ttl_seconds / source_version`；渲染可选标注（默认关闭，基线零漂移）；票 5ad 起 trust 乘数进 `rerank_items`（§5.2） | 外部网页/记忆注入风险随 hy-memory 接入上升 |
| **P1-B（已完成）** | Verifier 触发 | `backend/services/verification_policy.py`：风险下限 + 期望成本公式 + 预算降级；真实发布路径发射判定事件（§5.3） | 有 acceptance_signoff 人工验收作基线 |
| **P2-部分（已完成）** | 恢复策略分派 | `backend/models/recovery_policy.py`：按错误类型分派 retry/degrade/escalate/stop，retry 层记录决策（§5.4） | 文章 recovery 表可直接落地，且不需要多模型路由矩阵 |
| P2 | 子 Agent 并行（按 Artifact 分工） | 仅当出现明确的独立验收产出时启动；**证据采集器已就绪（§5.6）** | 当前串行图无瓶颈证据，不提前建 |
| **P3-前置（已完成）** | Harness Benchmarks 套件 | `scripts/benchmarks/harness_benchmarks.py` + CI job：F1/F2/F4 可跑，F5/F7/F8 记 SKIP（§8） | 评测集是 Adaptive Harness 的前提；先把确定性防线变成可跑的 gate |
| P3 | Adaptive Harness | 依赖评测集 + A/B 门禁；P1b 基线是起点；路由对照铺垫 `scripts/benchmarks/llm_route_benchmark.py` 已存在 | 无评测数据前做自适应是赌博 |

### 5.1 P0-B 落地记录（publish 六态 Effect 账本；互动账本按设计独立）

| 项 | 实现 |
|---|---|
| 状态机 | `PREPARED → IN_FLIGHT → CONFIRMED / FAILED / UNKNOWN`；`UNKNOWN ↔ RECONCILING → CONFIRMED / FAILED`；`FAILED → IN_FLIGHT`（新一次尝试） |
| 阻塞规则 | `IN_FLIGHT / CONFIRMED / UNKNOWN / RECONCILING` 阻塞重试；**`PREPARED`（仅意图）与 `FAILED`（明确未生效）不阻塞** |
| 领取语义 | `EffectLedger.begin()` 一次完成读 + 判 + 写 IN_FLIGHT；被拦时抛 `EffectBlockedError`（携带记录，供调用方写拒绝结果） |
| 乐观锁 | `mark(..., expect_version=N)` 拒绝覆盖并发写入；**诚实边界：BaseStore 无 CAS，多写者部署需数据库唯一约束**（代码注释已写明）。**现状**：`backend/agents/publisher.py` 的 `EffectLedger.mark(...)` 写入点**今天不传** `expect_version` —— 发布路径的并发正确性靠租约 + 幂等键，不靠 CAS；不要把"能力存在"读成"已启用" |
| 旧词兼容 | 读侧归一化 `published → CONFIRMED`、未知状态 → `UNKNOWN`（绝不落 FAILED）；历史行零迁移 |
| publish 接入 | 提交前写 `PREPARED`（意图落盘）→ `begin()` 领取 → 成功 `CONFIRMED` / 确定失败 `FAILED` / 提交后无判定 `UNKNOWN`（显式写入，不再靠"保持不写"隐含） |
| 接入边界（诚实披露） | 主链 `PublisherAgent` 与 free 路径已接账本（PREPARED + `EffectLedger.begin()`：`backend/agents/publisher.py:1165-1187`；free 路径经 `backend/api/routes/free.py` 的单一执行入口 `execute_mainline_publish`）；**creator_agent 控制面 `execute` 路径也已接入 `EffectLedger`**（票 5bi：`_publish_with_effect_ledger` 在 dispatch 前 claim、按 outcome 结算），receipt 仍记录执行结果，账本负责崩溃窗口的重复提交防护。**分支 B 已落地（票 5bs）**：有 durable mainline intent 的发布现在经 `CreatorAdvisor.execute_action` 执行（receipt-backed、attempt 级 receipt），主链仍持有唯一的 `publish_id` 账本 claim；无 intent 的路径保持原直调。 |
| 本地对账写账本（票 5ai） | `reconcile_unknown_publish` 本地证据确认 published 后 best-effort `UNKNOWN→RECONCILING→CONFIRMED`（evidence 入 `extra.reconcile_evidence`）；uncertain **不动**账本；写失败仅 warn，不阻断 gate 返回值 |
| 平台列表对账（票 5ak） | 本地幂等行 / ContentHistory 均 miss 且 title 非空 → cookie httpx 拉创作者中心笔记列表标题 **精确** strip 匹配；命中则 `source=platform_note_list` + note id，走同一 `_confirm_ledger_after_reconcile`；无 cookie / fetch 失败 / 未命中 → `uncertain`（warn，不 raise、不伪确认）；可注入 `platform_note_fetcher`；**CDP / 详情页深查 out of scope** |
| 平台列表多页（票 5al） | 默认 `_default_fetch_platform_notes` 循环 page 1..`_PLATFORM_NOTE_LIST_MAX_PAGES`（锁定 **3**），`page_size=50`；某页 `extract_note_items` 为空或 `len(items) < page_size` 提前停；任一页抛错 → 整次平台刀 `uncertain`（与 5ak 一致）；匹配/确认语义不变；**CDP / 详情页深查仍 out of scope**；`max_pages` 不配 env |
| 对账同步 publish_result（票 5am） | `POST /publish-retry` gate `status=reconciled` 时 best-effort `aupdate_state`：checkpoint `publish_result` → `status=published`（合并原字段、`post_id`/`reconcile_evidence`/`result_known=True`）；`requires_force` / 非 unknown **不**写；写失败仅 warn，仍返回 gate |
| 行为等价 | 既有 publish 测试全绿（含 5al 多页用例）；对外 `publish_result.status` 词表（published/failed/unknown）未变 |

### 5.2 P1-A 落地记录（Context Provenance）

| 项 | 实现 |
|---|---|
| 数据面 | `ContextItem` 新增 `trust_class`（`internal_fact / memory / external_document / model_generated / unspecified`）、`verified`、`ttl_seconds`、`source_version`，全部带默认值（additive） |
| 默认值 | `trust_class=unspecified`、`verified=False` —— 未标注的生产者不得被呈现为可信 |
| 生产方标注 | `item_to_context_item`：content_history → `INTERNAL_FACT`，其余三命名空间 → `MEMORY`；hy-memory 召回 → `MEMORY` + `verified=False` |
| 渲染 | `compile(..., annotate_provenance=True)` 追加单行标签 `[source=… trust=… verified version=… ttl=…]`；**默认 False** —— P1b 基线钉住渲染字节，开启标注必须是显式迁移（同一次改动刷新快照） |
| 零漂移证明 | `context_compiler_baseline.py --compare --drift-pct 5` → `drift within threshold`，115 项 context 测试全绿 |
| 排序融合（票 5ad） | `rerank_items` 有效置信度 = `confidence * source_weight * trust_weight`；封闭表 `TRUST_RERANK_WEIGHTS`（`internal_fact=1.0` / `memory=0.85` / `model_generated=0.7` / `external_document=0.55` / `unspecified=0.5`）；始终应用、无开关；缺字段走 `UNSPECIFIED` |
| 诚实边界（仍成立） | `verified` / TTL **仍不**进排序（生产者仍少）；无 LLM rerank；`verified=True` 生产者仍稀缺，字段先就位 |

### 5.3 P1-B 落地记录（Verifier 触发）

| 项 | 实现 |
|---|---|
| 决策函数 | `decide(VerificationInput) → VerificationDecision`（required / tier / reason / expected_benefit） |
| 风险下限 | CRITICAL（真实发布等不可逆外部副作用）→ 强制 `HUMAN`；HIGH → 至少 `DETERMINISTIC`。**下限先于公式判定**——低错误概率不能买通高风险门 |
| 期望成本 | `p_e·p_d·L > C_v` 才验证；MEDIUM/HIGH 正收益落 `LLM` 档，LOW 落 `DETERMINISTIC` 档 |
| 预算降级 | 预算不够所选档位时降到 `DETERMINISTIC` 并标 `budget_exhausted`；**绝不静默跳过有下限的检查** |
| 事件 | 新增 `kind:"verification"`（已注册 `EVENT_KINDS`）；真实发布路径在领取 Effect 后发射判定，纯观测、零行为变更。发射范围：主链在 `backend/agents/publisher.py:1216-1229`；控制面 creator-origin 发布在 `backend/creator_agent/advisor.py:905-933`（2026-11-14 补）；mainline-origin 经执行器分发时**不重复发射**（主链已发一条）。两侧均有测试守护：`tests/unit/agents/test_run_publish.py::test_a_real_publish_emits_exactly_one_verification_entry` 与 `tests/unit/creator_agent/test_publish_effect_ledger.py::TestTheVerificationTelemetry` |
| 诚实边界 | `p_e/p_d` 是输入先验（仓库暂无校准评估集）；`LLM` 档是决策槽位，本仓库尚无独立 verifier 实现（接入是独立变更，需评测门槛） |

### 5.4 P2-部分落地记录（恢复策略分派）

| 项 | 实现 |
|---|---|
| 四档动作 | `RETRY_SAME`（429/5xx/网络）/ `DEGRADE_MODEL`（400/404/409/422/schema/结构化解析失败）/ `ESCALATE_MODEL`（同错误重复 = stalled）/ `STOP_AND_REPORT`（401/403/内容策略/重试预算耗尽） |
| 优先级 | **拒绝优先**：401/403/策略拒绝即使同时"像瞬时错误"也直接 STOP——重试拒绝就是绕过路径 |
| 与 retry 层一致 | 一致性测试：**在重试预算内** `retry._is_retryable(exc)` 为真 ⇔ 分类为 `RETRY_SAME`（两张规则表不允许漂移）。到达重试上限后，瞬时错误分类为 `STOP_AND_REPORT`，此时 `_is_retryable` 仍为真——两张表回答的是不同问题（能否重试 vs 现在适合哪种恢复），见 `tests/unit/models/test_recovery_policy.py::TestTransient::test_transient_past_budget_stops` |
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

### 5.9 票 5w 落地记录（Attempt 身份协议）

§2 的 Attempt 缺口：节点内重试只有日志行，没有 attempt_id、没有 attempt 级事件。

| 项 | 实现 |
|---|---|
| 词表 | `AttemptOutcome`：`succeeded / payload_rejected / semantic_rejected / unreachable`（封闭）。两种拒绝**必须分开**：schema 不合法永不可成为结果；validator 拒绝可能是 advisory |
| 身份 | `attempt_id(agent, level, attempt_no, started_at)` = `att_` + sha256[:16]；**含 attempt_no**，否则同档位重试会复用上一条 id |
| 条目 | `attempt_entry(...)` 返回与 perf entry 同形的 dict（`kind:"attempt"`）；键集合是保留位，新增字段要走评审 |
| 数据最小化 | 不含 prompt / 模型输出 / 异常消息，只留 `error_class`（异常类名）；`tests/unit/state/test_attempts.py` 断言字段集合恰为白名单 |
| 接入 | `_llm_structured` 每次（档位 × 序号）尝试后 append 到既有 perf contextvar；`execute()` 的 drain/emit 路径不变（`emit_events` 仍是 best-effort） |
| 事件类型 | `ATTEMPT_EVENT_KIND = "attempt"` 注册进 `EVENT_KINDS`（`tests/unit/state/test_attempts.py` 钉住声明与注册一致） |
| 行为变更 | **零**：重试预算、控制流、prompt、模型调用都不改；只多一条遥测 |
| 诚实边界 | 不是重放：节点内重试仍会重调 LLM（§4.1 的判据与触发条件不变）；Run 实体由票 5x 单独落地（§5.10） |

可复核的防线在 `tests/unit/state/test_attempts.py:40-81`：字段白名单
`test_the_entry_has_exactly_the_reserved_keys`、词表封闭
`test_the_outcome_vocabulary_is_closed`、`EVENT_KINDS` 注册
`test_the_kind_is_registered_once`、数据最小化
`test_the_entry_carries_no_content`。原文的「突变自检 9/9 断言红」
**无仓内产物**（仅 PRD 把它列为验收要求），不能作为可复核证据。


### 5.10 票 5x 落地记录（Run 身份协议）

§2 的 Run 缺口：同一 `thread_id` 上 resume（继续）与 terminal restart（重开）无法从 ID 区分。

| 项 | 实现 |
|---|---|
| 词表 | `RunCause`：`start / resume / rerun / recover`（封闭）。铸造事件只允许 `start`/`rerun`；`resume` / `recover` 目前是**保留词**——`run_entry` / `mint_run_stamp` 会拒绝它们，因此 checkpoint 里的 `run_cause` 只可能是 `start` 或 `rerun`，读者不得把它们当作可观测原因 |
| 身份 | `run_id(thread_id, run_seq, started_at)` = `run_` + sha256[:16]；**含 run_seq**，否则同 thread 重开会复用上一条 id |
| 条目 | `run_entry(...)` → `kind:"run"`；键集合是保留位 |
| 数据最小化 | 不含 goal / brief / 内容字段 |
| 接入 | `Goal.compile_initial_state` 铸造 seq=1 + cause=`start`；`/start` emit；terminal restart（completed/cancelled）经 `mint_run_stamp(cause=rerun)` 写入 checkpoint 并 emit；pause/error resume 与 `/recover` **复用**既有 stamp |
| 事件类型 | `RUN_EVENT_KIND = "run"` 注册进 `EVENT_KINDS` |
| 行为变更 | **零控制流**：图重入语义不变；只多 stamp + 遥测；`/status` 与 start/resume 响应 additive 回显 |
| 诚实边界 | legacy 无 stamp 时回显 null，不在普通 resume 上偷偷回填；不做 Run 级预算（F7 仍 SKIP） |

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

## 9. 剩余工作与本地 CI 核对（2026-11-01）

> 目的：让「所有剩余任务」可审计——哪些能本地跑、哪些是决策/外部/环境依赖。
> 本轮已在本地逐项核对 CI（**下表计数为 2026-11-01 时点**）；
> 2026-11-14 复核：**5113 passed / 14 skipped / 0 failed**，见 §9.3。

### 9.1 CI 作业本地核对矩阵

| CI 作业 | 本地核对方式 | 结果 |
|---|---|---|
| Lint & Format | `ruff check` + 改动文件 `ruff format --check` | ✅ 绿（2026-11-14 复核：`ruff check backend tests scripts` 全绿；LF 归一 format 709 个 tracked `.py` 全绿，早期记录的 CRLF 假阳性未复现） |
| Mypy | `mypy --python-version 3.12 backend`（本地 numpy 2.5.1 stub 与 `python_version=3.11` 冲突） | ✅ 267 source files，0 issues（2026-11-14 复核：E2 接线新增 `backend/harness/runtime.py` 后 266→267） |
| Test（py3.11/3.12 + PG parity） | `pytest -q` | ✅ 4800 passed / 14 skipped（2026-11-01 时点）；**2026-11-14 复核 5113 passed / 14 skipped / 0 failed**；PG parity 需 CI 的 postgres service，本地无凭据可用端口 |
| Context Compiler Baseline | `python scripts/benchmarks/context_compiler_baseline.py --compare --drift-pct 5` | ✅ drift within threshold |
| Harness Benchmarks | `python scripts/benchmarks/harness_benchmarks.py` | ✅ pass=3 fail=0 skip=3（F5/F7/F8 是文档化缺口） |
| Tool Runtime Gate | `python scripts/gates/tool_runtime_gate.py` | ✅ P1c-S5 OK |
| Compliance Baseline Gate | `python scripts/gates/stealth_default_off.py` | ✅ OK |
| Frontend（type-check/test/i18n） | `npm run type-check` / `i18n:check` | ✅ type-check、i18n(2372 keys) 通过（2026-11-01）；2026-11-14 复核：i18n 仍绿；本 checkout 补齐 `frontend/node_modules`（`npm install`，270 packages）后，`vue-tsc --noEmit` 与 `vitest run`（788 passed / 75 files）也均本地通过——node_modules 不入库，CI 仍为权威 |
| OMP Typecheck | `npm install && npm run typecheck` | ✅ 2026-11-14 复核：本地 node_modules 就绪，`npm run typecheck`（`tsc --noEmit`）通过；CI 仍为权威 |

### 9.2 剩余工作（本地可执行项已清零）

| 项 | 类型 | 状态 / 触发条件 |
|---|---|---|
| P4 分支 B：入口直落 `execute_action` 回执路径 | 已完成 | 2026-11-01 拍板并落地 B1–B4（票 5bn/5bo/5br/5bq/5bs）及加固（5bu/5by）：receipt attempt 级、intent 先于持久效果、executor 接受 caller-supplied request、有 intent 的发布经 `execute_action` 执行且只保留主链一个账本 claim；claim 表新增两条并带阳性对照。**已推送 origin/main 并经 CI 验证**：run 41306901460 / 41307361407 的 10 个作业全部 success（含 mypy、py3.11/3.12 的 Postgres parity、frontend、OMP） |
| 路线图 8：多 Agent 并行 / workspace 冲突（F5） | 裁定 | 本文档裁定「先不建」，F5 保持 SKIP |
| 路线图 10：Adaptive Harness + A/B 门禁（F7/F8） | 已交付（live 除外） | 评测集先行：E1 真实 checkpoint 抽取+脱敏+指纹/加盐（5cd/5cj/5ck/5cm/5cp）、E2 HarnessPolicy（5ce，**2026-11-14 已接线**：`backend/harness/runtime.py` + router/compiler/gateway 四个决策点，默认策略逐字节等价）、E3 离线 A/B 门禁 report/block（5cf/5cj/5cn，现为 **corpus/l1/l2/thresholds/variant/benchmarks 七项检查**）、变体示例（5cg/5cn）、E4 质量裁判 + 199 预算护栏 + live 计划门闸 + runbook（5ch/5ci/5cj/5co）；多轮独立审查（含 5cm 第二轮两处高危）发现的高/中/低危均已修复；**L1 决策回放（同日）、L2 工具/网关回放与成本/时延/质量阈值判定均已实现（2026-11-14 后续轮，§9.3）**，仅 live 端到端仍 external-only |
| 私信 DOM 真机读法、笔记详情页深查/CDP | external-only | 需真实账号与平台环境，沙箱内不可验证 |
| frontend vitest、OMP typecheck、PG parity | 环境 | CI 正常执行；本地：2026-11-14 补齐 node_modules 后 frontend type-check + vitest(788) 与 OMP typecheck 均已跑通，PG parity 仍需凭据/服务——非仓库缺陷 |

**结论**：仓库内可本地执行、可验证的剩余任务已清零（分支 B 已于 2026-11-01 完成并推送，
票 5bn–5by；CI 10 作业全绿）。路线图 10 从「进行中」推进到「**已交付（live 除外）**」：
E1–E3（含 L1 决策回放、**L2 工具/网关回放、成本/时延/质量阈值判定**）、E2 生产接线、
变体示例与 E4 的裁判/预算护栏/计划门闸全部落地（票 5cd–5cp，含 5cm 第二轮两处高危修复、
5cp 的 artifact 写缝/`--store-uri`/扫描上限），多轮独立审查发现的高危/中危/低危均已修复；
E4 的 live 端到端仍 external-only（需部署侧凭据、测试账号窗口与真实费用）。其余为已裁定
延后项（路线图 8：多 Agent 并行，裁定先不建）与外部/环境依赖项。

### 9.3 2026-11-14 复核与修复（文档同步）

> 复核方式：本地 CI 等价全量 + 逐条「文档声明 → 生产调用点 → 测试」审计。
> 结论：§9.1 的「绿」仍然成立，但计数与若干锚点已过期；漂移已在本轮修正，
> 并补上两处「已接线但无测试守护」的缺口。

| 项 | 2026-11-14 实测 | 说明 |
|---|---|---|
| 全量 pytest | **5113 passed / 14 skipped / 0 failed**（5127 collected，166s） | §9.1 的 4800/14 与 journal 的 4979/11 均为历史快照（后者带 PG parity）；3 项 PG parity、11 项 Windows symlink 为环境 skip；较 2026-11-14 早先的 5006 增加 107 条：E2 接线 36 + L2 23 + 阈值 40 + gate 集成 8 |
| Lint / Format | `ruff check backend tests scripts` 全绿；LF 归一 `ruff format --check`（709 个 tracked `.py`）全绿 | 早期记录的 CRLF 假阳性未复现 |
| Mypy | `mypy --python-version 3.12 backend` → 266 source files，0 issues | 直接 `mypy backend` 仍只被本地 numpy 2.5.1 stub 的 PEP-695 语法卡住（环境） |
| Gates | context baseline `drift within threshold`；harness `pass=3 fail=0 skip=3`；tool runtime / compliance OK | F5/F7/F8 仍为记录在案缺口，不当通过 |
| OMP / Frontend | OMP `tsc --noEmit` 本地通过；i18n `2372 keys` 通过；补齐 `frontend/node_modules` 后 type-check 与 vitest（**788 passed / 75 files**）亦本地通过 | node_modules 为本地环境（不入库）；CI 仍为权威 |

本轮修正的文档漂移：§2 `/start` 锚点（177→178）；§5.1 标题（「统一」仅指 publish 跨路径
共用六态，互动账本按设计独立）；§5.1 发布接入锚点（927-945→1165-1187）；§5.3 发射范围
（主链 + 控制面 creator-origin 各一条，mainline-origin 不重复）；§5.4 一致性判据补
「重试预算内」限定；§5.10 `RunCause` 补「resume/recover 为保留词」；§9.2 路线图 10 票号
补到 5cp；`docs/adaptive-harness-eval-plan.md` 的本地语料说明（0→27 checkpoints）与
`test_policy.py` 用例数（8→9）。

本轮补的守护（此前是「已接线但删掉也全绿」）：主链真实发布必须恰好发射一条
`kind:"verification"`（`tests/unit/agents/test_run_publish.py`）；控制面 creator-origin
发布发射一条、mainline-origin 不重复发射（`TestTheVerificationTelemetry`）；
`tests/unit/api/test_publish_retry.py` 关闭未 await 的租约心跳协程（全量 warnings 5→1，
仅剩环境级 Starlette 弃用提示）；`.gitignore` 忽略 `.workbuddy/` 与 `data-gym-cache/`；
E1 抽取器的 sqlite/Postgres 两条入口都改用项目 `checkpoint_serde()`（与 graph 同一
allowlist，消除真实 checkpoint 的 "unregistered type `WorkflowPhase`" 警告并防止未来
strict 反序列化把决策字段降级成裸字符串；`tests/unit/scripts/test_eval_fixtures.py`
26 passed）。

仍未完成（裁定/外部项）：路线图 8（多 Agent 并行）保持「先不建」；E4 live 端到端
external-only（需部署侧凭据、测试账号窗口与真实费用）。本段此前记录的三项缺口已在
**2026-11-14 后续轮消除**：E2 接线（`XHS_HARNESS_POLICY` + `backend/harness/runtime.py`，
默认策略行为等价）、L2 工具/网关回放（`tool_replay.py` + `record_tool_results.py`，真实
`ToolGateway` 分类/回执/`EffectLedger` 状态校验）、成本/时延/质量阈值（`thresholds.py`）；
本地 `.eval-fixtures/` 也已生成（5 fixtures，digest `17e331e3…`，此前记录「仍不存在」已过期）。

**2026-11-14 追加：E3 L1 决策回放已落地**（`scripts/eval/decision_replay.py` +
`scripts/eval/run_gate.py` 的 `l1` 检查）。逐 fixture 回放四个决策（model 路由 / 该 phase
的 context budget / escalation / tool limits）；**强制不变量**（路由非空、预算 None 或非负
int、escalation 目标非空且不重复、tool limits 形状不变、JSON 可序列化）与**非确定性**
（两次回放不一致）判红；与基线的差异按 fixture 逐字段写入 `l1_diff`，作为 preference
**只报告不判红**；未传 `--variant` 却偏离基线判红。语料缺失时显式 SKIP，`--skip-l1`
亦显式 SKIP（缺口不当通过）。验证：`tests/unit/scripts/test_eval_l1.py` **16 passed**；
真实语料（5 fixtures）回放 `[PASS] l1: decisions identical to the baseline`；示例变体
`phase_budget`（publishing budget=4000）在 publishing fixture 上产生
`context_budget: null → 4000` 的 preference diff。（当时）L2 工具回放与阈值判定尚未实现，
两者已在同日后续轮补齐，见 §9.4。

**推送与 CI 验证（2026-11-14）**：本轮修复已 rebase 到 origin/main 的 `96bf61f1` 之上并推送
（`de5ad5cc` telemetry / `43a88329` test / `ae06d01e` eval / `c83ac772` docs / `c49ce79b`
journal）。CI run **43592668170**（commit `c49ce79b`）的 10 个作业全部 **success**：
Lint & Format、Mypy、Test (py3.11)、Test (py3.12)、Context Compiler Baseline、
Harness Benchmarks、Tool Runtime Gate、Compliance Baseline Gate、Frontend、OMP Typecheck。
L1 切片 `3bc05c4c` 推送后，CI run **43596029485** 同样 10 个作业全部 **success**。

### 9.4 2026-11-14 后续轮：E2 接线 + E3 L2/阈值 + 本地语料（补齐路线图 10 最后可本地项）

- **E2 接线**：新增 `backend/harness/runtime.py`——`XHS_HARNESS_POLICY=module:factory`
  惰性解析（坏 spec 抛 `HarnessPolicyLoadError`，不静默回退）、`configure_policy` /
  `reset_policy` / `policy_generation` / `is_default_policy`。四个决策点的生产读取方：
  `ModelRouter._candidate_model_ids`（overrides → policy.route_model → MODEL_FALLBACKS →
  escalation，`with_fallback` 惰性嵌套；cache key 含 policy_generation）、
  `compile_prompt`（仅 `budget is None` 时问 `policy.context_budget(phase=...)`）、
  `ToolGateway._effective_limits`（**默认策略完全不查目录**，保持 `ToolSpec` 与自定义
  registry 语义；非默认策略的 ToolLimits 生效，未知能力回退 spec，非法 limits 抛
  `ValueError` 点名能力）。默认策略行为逐字节等价。测试：`test_runtime.py` 36 passed、
  `test_policy.py` 9 passed、models+context+tools+harness 770 passed，mypy 267 files 0 issues。
- **E3 L2 工具/网关回放**：`scripts/eval/tool_replay.py`（manifest+逐 case sha256、真实
  `ToolGateway` + 脚本化工具、分类/唯一 invoke 回执/`EffectLedger` 终态与 blocks_retry
  校验、两次回放确定性）+ `scripts/eval/record_tool_results.py`（`--seed` 生成 5 个边界
  case；`--sqlite-path` 从真实 checkpoint 抽取，无记录时写空 manifest 并如实报告）。
  语料缺失/空 manifest 显式 SKIP；manifest 坏、sha 不符、分类/回执/账本不符、非确定判红。
  `tests/unit/scripts/test_eval_l2.py` 23 passed。
- **成本/时延/质量阈值**：`scripts/eval/thresholds.py`——token/调用漂移 ≤5%、p50/p95
  退化 ≤10%、judge 一致性 ≥0.8；baseline 为 0、无 judge 数据的维度显式 SKIP（不可计算
  ≠ 通过），坏 metrics 文件判红。`tests/unit/scripts/test_eval_thresholds.py` 40 passed。
- **门禁集成**：`scripts/eval/run_gate.py` 现为 **corpus / policy / l1 / l2 / thresholds /
  variant / benchmarks 七项检查**，新增 `--tools-corpus` / `--metrics` / `--skip-l2`
  / `--skip-thresholds`；`test_eval_gate.py` 37 passed（含 l2/thresholds 集成用例），
  l1/l2/thresholds/gate 合计 116 passed。
- **本地语料**：`extract_fixtures.py` 已生成本地 `.eval-fixtures/`（5 fixtures，
  manifest digest `17e331e321f4adce36961d2b35f2785c617ed8df8403c1e4e50a17d0f02ad88c`；
  未设 `XHS_EVAL_REDACTION_KEY` → 指纹未加盐；10 个 checkpoint 的 artifact refs 因无法
  解析而跳过，均属已知诚实缺口）；`record_tool_results.py --seed` 生成
  `.eval-tool-corpus/`（5 cases）。两者均 gitignored（`.gitignore` 新增
  `.eval-tool-corpus/`），CI 仍拿不到语料、对应检查显式 SKIP。
- **本地 runner 实测**：`python scripts/ci_local.py --only eval-gate` 在本地语料存在时
  真实运行 `--fail-on-red`：corpus / policy / l1 / l2 / benchmarks 全 PASS，
  thresholds 因无 `--metrics` 显式 SKIP（live 产物，external-only）。


- **全量回归**：`pytest -q` → **5113 passed / 14 skipped / 0 failed**（5127 collected，166s）；
  较上一轮 5006 增加 107 条（E2 接线 36 + L2 23 + 阈值 40 + gate 集成 8），无新增环境 skip。


