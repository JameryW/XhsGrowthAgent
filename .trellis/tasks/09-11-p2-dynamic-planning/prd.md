# P2c Dynamic Planning — 侦察与切片计划

**状态**：规划中。本文件是本任务的 prd；实现按切片逐片交付，**每片独立 PR**。

依据：父任务 roadmap（`09-11-runtime-upgrade/prd.md` §P2c）；架构评估 `research/architecture-review-2026-09-11.md:1857`。

## Background（票面原话）

> P2c `09-11-p2-dynamic-planning` — 动态 Planning（依赖 P1a/P1c/P2a）
> Planner 按 Goal 编译 Task Graph（保留常用模板为 deterministic path），停止新增 workflow_mode+router+edge；workflow.py（2519 行）按 api/application/runtime/artifacts/actions 分层拆分。

评估原文的同一条（`:1857`）：

> **P2：真正动态的 Planning。** 保留常用 Content Workflow 模板，但 Planner 根据 Goal 编译 Task Graph，而不是继续新增 `workflow_mode + router + conditional edge`。简单任务继续 deterministic workflow，复杂任务才动态规划。

票面是**空白占位**（`status: planning`、`subtasks: []`、无 prd.md、两个 jsonl 只有示例行），所以本轮是**规划/侦察轮**，产出本文件；实现按下面的切片逐片交付。

## 现状侦察（2026-09-16，逐条对代码核实）

| # | 事实 | 位置 | 含义 |
|---|---|---|---|
| 1 | **「计划」没有所有者**：它是 18 个 router 各自重读 state 的副产品 | `graph/builder.py:69` `build_graph`（**361 行的单体函数**）装了 **24 个节点 / 18 条 conditional edges / 7 条直边**；每条边挂一个 router（`graph/routers.py` 27 个顶层函数，18 个是 edge router） | **没有任何一处**持有"这次 run 会走哪些节点"。要回答这个问题只能模拟 18 个 router |
| 2 | 「这次 run 是不是结束了」被**重新推导 18 次** | `graph/routers.py:13` `_check_terminal`，调用点 `:82`、`:141`、`:154`、`:300`、`:317`、`:338`、`:354`、`:386`、`:402`、`:412`、`:428`、`:483`、`:510`、`:534`、`:563`、`:574`、`:598`（18 处） | 终止判定是本图最常被复制的一行；它是**只读**判定，但没有集中点 |
| 3 | **`workflow_mode` 有 11 个读取点，其中 8 个把默认值写成 `"trend"`** | `graph/routers.py:86`/`:431`/`:467`/`:541`/`:581`/`:605`（**6 处**）、`agents/orchestrator.py:35`、`agents/copywriter.py:169`/`:389`、`api/routes/workflow.py:968`、`db/workflows.py:376` | 未知模式**静默按 trend 处理**；新增一个模式 = 在这 11 处里找出该改的那几处 |
| 4 | **入口路由是全图唯一「读不出目的地」的路由，而它恰好是计划的入口** | `graph/routers.py:80` `orchestrator_router` 返回裸 `str`；它是**唯一**被 `tests/unit/graph/test_conditional_edge_wiring.py:31` 豁免的 `_NON_LITERAL_ROUTERS` 成员 | 18 条边里 17 条的目的地可从 `Literal` 注解静态读出，**入口这条不能** |
| 5 | 入口路由内部是**按模式复制两份**的 `phase → node` 表，并以静默兜底收尾 | brief 表 `routers.py:90-101`、trend 表 `:104-113`、兜底 `:116` `routing.get(phase, "trend_scout" if mode != "brief" else "brief_analyzer")` | 未知 phase **静默落到该模式的起点**（不是拒绝，也不是报错） |
| 6 | **同一个决定写了两遍**：先由 `OrchestratorAgent` 把状态压成 `phase`，再由 `orchestrator_router` 把 `phase` 映射成节点 | `agents/orchestrator.py:19-40`（`async def execute`，整个文件 40 行）是**纯确定性 if 链**（`analytics` → `error`/`retry_count` → `workflow_mode == "brief"` → 默认 `SCOUTING`），却包在 `class OrchestratorAgent(BaseAgent)` 里、带 `prompt_file = "orchestrator.yaml"` | "Agent 抽象"与"确定性路由"混在一起（评估表 Agent abstraction 6/10 的那一格） |
| 7 | **`WorkflowMode` 已经存在，就是票面说的「常用模板」，只有 2 个成员** | `state/enums.py:60`，docstring 自己写着 "determines starting node and pipeline path"：`TREND`/`BRIEF`。另一条正交轴 `ExecutionMode`（`:53`，`single`/`continuous`） | 模板不需要发明，只需要**被声明成数据** |
| 8 | **`WorkflowPhase` 的 13 个成员里有两个是历史遗留，而「PLANNING」这个词今天指的不是规划** | `state/enums.py:6`；`ENGAGING` 被所有 router 显式映射成 `__end__`（`routers.py:97`/`:110`，注释「no interaction node exists anymore」）；`PLANNING` 的语义是"进入 content_strategist"（`:92`/`:106`） | **两个词撞车**：本片要说的"计划"与 `phase=planning` 不是一回事 |
| 9 | **`WorkflowPhase` 有两份定义，当前成员逐字相同（13/13）** | `state/enums.py:6`（`StrEnum`）与 `api/generated/models.py:49`（`Enum`） | 是**重复**而不是**漂移** ⇒ 潜伏的漂移面，不是当前缺陷（不夸大：今天没有任何行为分歧） |
| 10 | **`TaskType` 这个名字已被占，但语义是「模型路由键」** | `config/models.py:6`，成员含 `ROUTING`/`SCOUTING`/…/`MOCK_GEN`，docstring 直说「任务类型 → 模型路由键」 | 评审里六个核心对象中的 **`Task` 尚未存在**；已交付的是 `ArtifactRef`（P1a，`state/artifacts.py:85`）· `RunContext`（P1b，`context/models.py:121`）· `ToolResult`（P1c，`tools/runtime/models.py:281`），`ActionIntent`/`DecisionRecord` 在 `creator_agent/models.py:669`/`:503`。**命名要避开 `TaskType`** |
| 11 | **「Goal」今天不是对象，而是「哪个端点 + 往 state 里塞了什么」** | 12 个 `_run_graph_and_persist` 调用点分布在 5 个文件（`workflow.py` 7 · `review.py:204`/`:385` · `optimization.py:93`/`:157` · `blogger.py:118`）；`/start` 的 `initial_state` 是字面量 **24 个键**（`workflow.py:726-754`；**票面原写 26，S3b 侦察实测 24**），模式差异是一句 `if req.workflow_mode == WorkflowMode.BRIEF:`（`:756`）改 `phase` 并决定正文内联还是进 Artifact Store（`:758-774`）。**★ 第二个同形（S3b 侦察）**：`execution_mode` 同样是裸 `str`（`:511`）配字面量兜底（`routers.py:320` 的 `state.get("execution_mode", "single")`），而 `ExecutionMode` 枚举（`state/enums.py:53`）明明存在、边界处却不用；`tests/unit/state/test_execution_mode.py` 的头两条断言还因 `StrEnum` 恒真而零信息量 —— 但**票面已裁界**（"拒绝"节第 2 条：不动这条轴），**登记不改** | 输入端没有 Goal，只有"端点 + 字典字面量" |
| 12 | **`workflow.py` 已经长到 2999 行（票面写 2519，**+480**）**，49 个顶层定义，前 7 个占 **47%** | 最大 7 个：`resume_workflow` 327 行（`:1288`）· `get_workflow_status` 244（`:874`）· `start_workflow` 193（`:678`）· `retry_publish` 179（`:2821`）· `recover_workflow` 159（`:1618`）· `retry_ripple_analysis` 153（`:2159`）· `stream_workflow_progress` 142（`:1835`），合计 1397 行；18 个端点（`@router.`） | 票面的行号已经过期，**返工的第一步是承认它不是 2519** |
| 13 | **这 7 个端点每一个都同时摸 2–6 层关注点** | 按 7 类探针（DB 写 / 事件 / 状态构造 / 图执行 / 响应体 / artifacts / 租约）统计：`start_workflow` 6、`retry_publish` 6、`get_workflow_status` 4、`retry_ripple_analysis` 4、`stream_workflow_progress` 4、`recover_workflow` 3、`resume_workflow` 2 | 缺的不是目录，是**边界**：同一个函数里既有 HTTP 关注点也有应用层与运行时关注点 |
| 14 | **拓扑已经有一张现成的结构门禁，是本片最便宜的安全网** | `tests/unit/graph/test_conditional_edge_wiring.py`：用 `builder.branches` 内省，**双向**都比 —— ① 每个 router 的 `Literal` 返回值必须能被 path_map 解析（`:78`）；② 每个 path_map 目标必须是真实节点或 `END`（`:115`）。它自己的 docstring 记录了 P1d 的 `KeyError: '__end__'` 事故 | 「把边变成数据」如果做错，这张网**当场**抓住，不需要新写检查器 |
| 15 | **图的测试面 1581 行 / 7 个文件，全仓 28 个测试文件碰 `build_graph`/`workflow_mode`/`add_conditional_edges`** | `tests/unit/graph/`（`test_routers.py` 876 · `test_builder.py` 195 · `test_conditional_edge_wiring.py` 126 · `test_graph.py` 53 · `test_router_guards.py` 49 · `test_retry_registry.py` 55） | 任何"等价改写"都有强绊线 ⇒ 风险可控，但**改形不删**的纪律必须逐条走 |
| 16 | **P2c 的三个依赖都已交付** | P1a（ArtifactRef/ArtifactStore/EventStore/RuntimeState，`10c972b7`）· P1c（ToolSpec/Registry/Gateway）· P2a（ActionIntent/DecisionRecord/人工闸门，`76da1e4b`） | Task Graph 的节点**可以**只声明能力需求、由 Gateway 解析（P1c 已就位），不需要本片再建执行设施 |

### 量化附录（本片的原始数据，可复核）

- `graph/builder.py`：620 行，5 个顶层定义，`build_graph` 单函数 361 行（`:69`）。
- `graph/routers.py`：610 行，27 个顶层定义；`_check_terminal` 被调 18 次。
- `api/routes/workflow.py`：2999 行，49 个顶层定义，18 个端点。
- `workflow_mode` 读取点 11 处，其中带 `"trend"` 默认值 8 处。
- 基线（本片开工实测）：`ruff check` 520 files 干净 / `ruff format --check` 520 files / `mypy backend --python-version 3.12` 207 files / `pytest -q` **3414 passed, 3 skipped**。

## ★ 要重写的定性：缺的不是 Planner，是「计划」这个对象

票面说"Planner 按 Goal 编译 Task Graph"。按实测，**今天不缺生成计划的东西，缺的是计划本身可被陈述**：

- **计划存在，但是分布式的**：18 条边 × 18 个 router × 11 个模式读取点，每一处都从同一个 state 包里重新推导"下一步该谁"。没有任何一处能回答"这次 run 打算做什么"。
- 所以"动态规划"的第一步**不是生成**一个计划，而是**让今天已经存在的计划变成可陈述的对象**（从一个隐含在固定拓扑里的形状，导出成一份数据）；然后才谈得上"由 Goal 编译"。
- **判据因此可测**：给一份 checkpoint，能否**在不执行图**的前提下说出"它还会走哪些节点"。今天答不出来 —— 要模拟 18 个 router 与它们各自的 `state.get(...)` 默认值。
- 同理，"停止新增 `workflow_mode + router + edge`"不该停在约定层：它要变成**机制** —— 新增一个模式若没在注册表里出现，测试就红（照 `RETRY_POLICIES` / `TAKEOVER_HAZARDS` 的穷举先例）。
- 沿评估的克制原则（父 prd `:9`：「能用 deterministic mechanism 解决的不放 Agent」），本片里的 **Planner 默认是一个确定性的编译函数**，不是 LLM Agent；"复杂任务才动态规划"是**开闸条件**，不是本片的默认路径（见 S5 与「拒绝」节）。

## 切片计划（每片独立 PR）

判据：按**依赖强度**排 —— 先让计划**可陈述**（只读，零行为变更），再让**边来自它**（等价改写），再把 **Goal 变成输入**，最后才拆文件；每一步都能被前一步的产物钉住。

| 切片 | 内容 | 风险 |
|---|---|---|
| **S1** ✅ | **Plan 的只读导出**：`Plan` / `PlanStep` 对象 + **穷举模板注册表**（`WorkflowMode` → 入口 / 词表 / 排除边），由一个**只读**函数从 `build_graph()` 的边导出并与注册表**双向比对**。执行路径**零改动**（没有执行代码读它）。判据 = 结构比对门禁，照 `test_conditional_edge_wiring.py` 的手法。**已交付**（`43580604` / [#618]，见本节末的 S1 小节） | 低 |
| **S2** ✅ | **边来自 Plan**：`build_graph()` 的 18 条 `add_conditional_edges` 改由**一张穷举的边表**（`backend/graph/wiring.py` 的 `CONDITIONAL_EDGES`：`source` + `router` + `answers` + `redirects`）生成，**逐边等价**（改写前后同一个 `builder.branches` 内省，差异精确等于 `orchestrator` 新增 `copywriter` 这一条）；入口路由（事实 4）是这一步的正题 —— `orchestrator_router` 拿到 `Literal` 注解，目的地从"读不出的 `str`"变成"可读出的声明"，`_NON_LITERAL_ROUTERS` 收窄到**空集**。**已交付**（`6727834f` / [#619]，见本节末的 S2 小节） | 中 |
| **S3a** ✅ | **模式注册表**：11 个模式读取点收敛到**注册表内部的 2 处**（`backend/state/modes.py` 的 `stored_mode` / `mode_spec`），未知模式在**请求边界被拒**（422，点名值 + 备选）、在 state 侧**声明式兜底 + 具名 warning**。**已交付**（`44ad59ff` / [#620]，见本节末的 S3a 小节） | 中 |
| **S3b** ✅ | **Goal 是一等输入**：`/start` 的 **24 键**字面量 + `if req.workflow_mode == WorkflowMode.BRIEF` 特例 → `Goal` → 编译。★ 侦察**取消了一个前提**：**`req.phase` 对"这次 run 去哪"从来无效** —— 图入口恒为 `orchestrator`（`builder.py:149` 的 `add_edge(START, "orchestrator")`），而它**无条件**写 `mode_spec(state).initial_phase`（实测：trend 请求 `phase=analyzing` ⇒ 写出 `SCOUTING`；brief 一律 `BRIEFING`），所以 `phase` 只影响 DB 的相位列与 `/start` 响应的 `phase`，**而这两个值恒与图不符**（响应说 analyzing、图从 scouting 跑）。于是"起点相位"收敛为**模式事实**（`ModeSpec.initial_phase`），`WorkflowStartRequest.phase` 随之移除。依赖 S3a —— 模式得先能被陈述，才谈得上被编译。**已交付**（`947ec505` / [#621]，见本节末的 S3b 小节） | 中-高 |
| **S4** ✅ | **`workflow.py` 分层**：3001 → **254 行**（-91.5%），6 层落进 5 个新模块 + 1 个新门禁；7 个巨型端点实测 1352 行（45.1%）**全部降到百行以内**（现在最大的函数 14 行）。**先立边界再挪代码**，纯搬移：搬移当刻用 AST 逐符号证明等价（55 符号 + 18 handler 签名），此后以 `/status` 形状快照 + 3572 用例钉住行为。★ 层名**不是**从既有门禁继承的（设计阶段的归因是错的，已撤回）；★ 最大风险是 ~125 处 patch 目标会静默失效，已按调用点重接线并加「不重新导出」断言。**已交付**（`a2904172` / [#622]，见本节末的 S4 小节） | 中 |
| **S5** | **契约与开闸条件**：`docs/planning.md` —— Goal / Plan 的定义、模板与"动态规划"的**开闸条件**（什么证据下才允许生成非模板图）、以及本片**明确不做**的三件事 | 小 |

## 红线（不可回退约束）

- **不改 `WorkflowStatus` 枚举**（前端只认已知状态，P0-W5 已立此规）。
- **新 run 新 schema、存量 checkpoint 不重写**（P1a 红线）；S1 的 Plan 必须是**导出**出来的，不得让旧线程因为缺新字段而不可读。
- **`/status` 保全文响应**（6 个读面已收口 hydration，前端零改动）。
- **不新增 LLM Agent**（父 prd 克制原则）；S3 的 Goal → Plan 是**确定性编译**，不是提示词。
- **等价改写要改形不删**：28 个相关测试文件里的绊线按设计变红时改形、不删（P2b-S2/S4a 同一纪律）。
- **不顺手做第四件事**：统一 retry 引擎已归 P0/P1（`error_handling.py` 的注释明写），执行平面已归 P2b，本片只做计划。

## 拒绝（本任务明确不做）

- **不做自由的图生成**（LLM 按 Goal 现编一张图）。评估的限制条件是"简单任务继续 deterministic workflow，复杂任务才动态规划"，而今天**没有任何复杂任务的样本**证明需要它；本片的产出是让这条路**可开闸**（S5 写下条件），而不是先建一个生成器。
- **不动 `ExecutionMode`（single/continuous）的语义**（事实 7 的第二条轴）：它与本片的"计划"正交，混在一起会让两件事互相污染。**S3b 实测发现这条轴上长着与 S3a 之前的 `workflow_mode` 一模一样的病**（请求模型是裸 `str`、路由处有 `"single"` 字面量兜底、枚举在边界不生效）—— 因为**票面在这里已经裁过界**，本片**登记不改**；将来若要收，照 S3a 的两读者形状（边界严格 422、state 侧 total + 具名 warning 兜底）即可，不需要新设计。
- **不合并 `WorkflowPhase` 的两份定义**（事实 9）：它们今天逐字一致、没有行为分歧，而动 `api/generated/**` 属于生成物边界之外的事。**登记为潜伏的漂移面**，不改。

## 验收

- 每片**独立 PR**，独立通过四道门禁（`ruff check` / `ruff format --check` / `mypy backend` / 基线对比 + 工具运行时门禁）与 `tests/unit` + `tests/integration`。
- **S1 的判据是双向结构比对**：注册表 ↔ `build_graph()` 的边，两个方向都比（注册表声明的每个节点必须在图里、图里每条边必须在注册表里有归属）；并且要有一条**非平凡用例**证明这个检查器不是空转（复现一次历史形状的缺陷）。
- **S2 的判据是等价性**：改写后的图与改写前**逐边相同**（同一个 `builder.branches` 内省），且 `test_conditional_edge_wiring.py` 的豁免清单**缩小或不变**（事实 4 修好后 `_NON_LITERAL_ROUTERS` 应当只剩空集）。
- **S3 的判据是收敛**：新增一个模式**只改一处**（注册表），`grep -rn 'get("workflow_mode"' backend/` 的命中数从 11 降到 1–2。
- **S4 的判据是行数口径可复核**：`workflow.py` 的 7 个巨型端点消失或降到百行以内，且 `/status` 的响应形状与拆分前逐字段相同。

## 待决（需要裁定，先登记不擅自动手）

1. **Plan 的粒度**：`PlanStep` 应该对齐**节点**（`trend_scout`、`content_strategist`…）还是对齐**能力**（P1c 的 ToolSpec capability）？前者与今天的 `builder.branches` 一一对应、S1 可零风险导出；后者才通向"由 Goal 编译"，但会引入第二套命名。S1 先按**节点**做（可导出即可验证），把能力粒度留到 S3 再定。
2. **未知 Goal / 未知模式的行为**：今天静默按 `trend`（事实 3、5）。改成拒绝会**改变行为**（新 4xx 路径），需要一次明确的裁定；本片默认在 S3 里按"拒绝 + 具名错误"处理。**S3a 已把"模式"这一半照此落地**：请求边界 **422**，state 侧**声明式兜底 + 具名 warning**（在图的节点里 raise 就是 P1d 形状，且会让存量 checkpoint 不可读）—— 两处分工的理由见 S3a 小节。**"Goal"那一半留给 S3b** —— S3b 的落点是**起点相位**：`Goal.start_phase` 由模式导出、客户端不可指定（`WorkflowStartRequest.phase` 已移除；`extra="ignore"` 实测保证老客户端传它**不会 422**，只是被忽略）。**未知 Goal 的其余面**（未知 `execution_mode`）**已登记不改**，理由同上节"拒绝"第 2 条。
3. **S5 是否应该是文档**：如果 S1–S4 暴露出"确实需要非模板图"的证据，S5 就不再是文档，而是那条路径本身（P2b 的 S4 就是这种形状）。**按证据走，不按计划走。**

## S1 交付 —— Plan 的只读导出 + 穷举模板注册表

**交付物**：`backend/graph/plan.py`（478 行）+ `tests/unit/graph/test_plan_registry.py`（304 行 / 24 用例）。

### 做了什么

1. **`Plan` / `PlanStep`**：一份计划 = 某个模式下这次 run 可能访问的节点，以及它们之间的边。
2. **`PLAN_TEMPLATES: dict[WorkflowMode, ModeTemplate]`** —— 穷举注册表，每个模式声明 `entry`（`orchestrator_router` 对一次新 run 给出的起点）、`destinations`（该模式下它能给出的**全部**答案）、`excludes`（图里有、但该模式**走不到**的边，每条注明是哪个 router 决定的）。`get_plan_template` 对未知模式 **`raise KeyError`** —— 照 `RETRY_POLICIES`（`error_handling.py:23`）与 `TAKEOVER_HAZARDS`（`takeover_safety.py:56`）的先例，默认值会替「没人分类过」的模式答一个值。
3. **`export_plan(mode)`** —— 只读地从 `build_graph()` 导出；`PlanExportError` 而不是产出一份丢掉解析不了的边的计划。
4. **`plan_registry_complaints()`** —— 9 类双向投诉，空 dict = 一致。
5. **执行路径零改动**：`build_graph()` 一行未改，没有 router 引用它，没有任何生产代码 import 它。

### ★ 与票面 S1 行文的偏离（登记，不是悄悄改）

票面写「`WorkflowMode` → **节点序列 / 依赖**」。实现改成「`entry` + `destinations` + `excludes`」，**节点集由图导出**而不是手写节点表。

理由是本片实测的一条事实：**图是 mode-blind 的**。从 `orchestrator` 起 24/24 节点可达；从两个模式的入口起各 **22** 个，而且两个集合**完全相同**（`reachable_nodes()`；差的 2 个是 `orchestrator`/`analyst`，因为回到根的唯一入边来自 `analyst` 自己，与模式无关）。⇒ 模式归属**不可能**从图导出，只能**声明**；而手写 24 个节点的归属是一份**没有任何东西能佐证**的声明。改成「入口 + orchestrator 词表 + 逐条排除边」之后，声明面缩到很小，且**每一条都能被现成的行为测试佐证**：三个 ripple router 与两个 gate 的模式分支已有测试（`tests/unit/graph/test_routers.py:601`/`:633`/`:669`、`tests/unit/test_brief_mode_status.py:47`/`:80`），入口则由本片新增的用例**真的去调** `orchestrator_router` 核验。

**附带收益**：`orchestrator_router` 的 **brief 分支此前没有任何测试**（`brief_analyzer` 只在三个 ripple router 与节点层被断言过）。`test_the_entry_is_what_the_router_answers_for_an_idle_run` 现在覆盖它。

### ★ 本片找到的缺陷（登记不修）

**`orchestrator_router` 在 brief 模式、`phase=creating` 时返回 `"copywriter"`（`routers.py:93`），而 `builder.py:168-174` 的 orchestrator 路径映射没有这个键。**

`WorkflowPhase.CREATING` 不是终态（`_check_terminal` 对它返回 `None`），所以这条分支确实可达；一旦可达，langgraph 解析不出目的地 —— 这正是 P1d 记录过的那种失败（`builder.py:194-200` 的注释：router 返回值在 path_map 里查不到 → `KeyError`，而事故恰好发生在没人看的那条路径上）。它今天**潜伏**的唯一原因是：没有任何实测路径会带着 `phase=creating` 走到 `orchestrator`。

**为什么只登记不修**：修它要往 orchestrator 的映射里加一个键，那是**改变行为**（决定了 brief 模式在 `phase=creating` 该跑哪个节点），而 S1 的契约是零改动。所以记在 `UNRESOLVED_ROUTER_VALUES`，并配一条**反向**断言：映射一旦补上，`plan_registry_complaints()` 会报 `exemption_no_longer_applies`、`test_state_graph_and_registry_agree` 当场红 ⇒ 强制显式删掉这条豁免，而不是让它变成长在树上的过期注释。

### ★ 另一处实测不对称：路径映射的 key 不是目的地

`Branch.ends` 是**路径映射本身**（`{router 答案: 节点}`），读成序列拿到的是**答案**，不是**目的地**。全图 18 条分支里**恰好一行**两者不同：`evaluator_gate` 的 `"publisher" → publish_gate`（`builder.py:394`）。

既有接线测试读的是 key（`test_conditional_edge_wiring.py:115`，函数名叫 `test_each_target_is_a_registered_node_or_the_end_sentinel`）—— 对它检查的东西是**对的**（router 的答案必须是 key），但**目的地这一侧从未被校过**。于是一个按 key 导出的实现会在 18 条分支里的 17 条上看起来完全正常，却在第 18 条上：① 发表一条图走不了的边（`evaluator_gate → publisher`，**绕过人工发布授权闸门**）；② 让 `publish_gate` 失去唯一的入边，从而**整个掉出计划**。

### 判据（票面 S1 行）如何被满足

| 票面判据 | 本片怎么落 |
|---|---|
| 注册表 ↔ 图**双向**比对 | 正向 3 类（`entry_not_a_graph_node` / `excluded_hop_not_in_graph` / `decider_is_not_the_router_at_that_source`）+ 词表双向 2 类（声明了但路由器不答 / 路由器答了但映射解析不出）+ 反向 2 类（`hop_dead_in_every_mode` / `node_dead_in_every_mode`）+ 豁免 2 类（未登记的不可解答案 / 过期豁免） |
| 注册表声明的每个节点必须在图里 | `entry_not_a_graph_node`；并且 `export_plan` 同时 `raise PlanExportError`（拒绝而不产出残缺计划 —— 「默认分支只许拒绝、不许产出」） |
| 图里每条边必须在注册表里有归属 | `hop_dead_in_every_mode`：一条**没有任何模式能走**的边 = 注册表漏了一块 |
| **一条非平凡用例证明检查器不是空转** | 8 条「检查器能发现」的用例（`monkeypatch.setitem` 注入做过手脚的模板），加 1 条**非空转核心**：`test_evaluator_gate_leads_to_the_publish_gate` 先断言图里的 key 确实是 `"publisher"`，再断言导出的是 `publish_gate` —— 按 key 读的实现在这条上必红 |

### 门禁与自检

| 项 | 结果 |
|---|---|
| `ruff check .` | 干净 |
| `ruff format --check .` | **522 files** already formatted（基线 520 + 本片 2 个新文件） |
| `mypy backend --python-version 3.12` | **208** source files，no issues（基线 207 + `plan.py`） |
| `context_compiler_baseline.py --compare --drift-pct 5` | drift within threshold |
| `tool_runtime_gate.py` | P1c-S5 tool runtime: OK |
| `pytest -q` | **3438 passed, 3 skipped**（基线 3414 + 24 个新用例；新用例数 **恒等于** pass 增量） |
| 突变自检 | **22/22 击杀、0 存活**、restore=OK；1 条（M14 `|=` vs last-wins）实测为**等价突变**并登记理由 |

**突变自检的两个中间发现**（都是"存活≠测试弱"那一类的正确处置）：

- **M11 存活两次，最后查出是死代码。** 它删掉 `followed_by` 的 `dst in node_set` 过滤。第二次存活才是结论：这个条件**永远为真**，因为计划本身就是"从根经 kept 边可达的集合"，所以计划节点的一条 kept 出边必然落在计划内（或落在 `__end__`）。它是一段**看起来在守不变量、其实守不到任何东西**的代码 ⇒ **删掉条件**，而不是为它补测试（不变量本身仍由 `test_the_export_never_invents_a_hop_the_graph_lacks` 断言）。`preceded_by` 的同名过滤**保留** —— M10 杀掉了它，说明它是承重的（前驱可以落在计划外：trend 模式下 `viral_matcher` 的另一条入边来自它到不了的 `brief_gate`）。
- **M14 是等价突变。** trend 的计划（22）是 brief 的（24）的**真子集**，所以 `|=` 与 last-wins 得到同一个集合；而这条包含关系本身被 `test_the_two_modes_do_not_get_the_same_plan` 钉住 ⇒ **改突变不改测试**，登记理由。

### S1 明确未做

没有一条边来自 Plan；`build_graph()` 未改一行；没有任何生产代码 import 这个模块；`_NON_LITERAL_ROUTERS` 仍然是 `{"orchestrator_router"}`（收窄它是 S2 的正题 —— **S2 已把它清空**，见下节）。

## S2 交付 —— 边来自 Plan

**交付物**：`backend/graph/wiring.py`（350 行）+ `tests/unit/graph/test_wiring_registry.py`（320 行 / 24 用例）；`builder.py`（-247 行净）、`routers.py`、`plan.py`、三个既有测试文件的等价改写。

### 做了什么

1. **一张穷举的边表**。18 条条件边从 18 段手写 `add_conditional_edges` 变成 `CONDITIONAL_EDGES` 里的 18 个 `ConditionalEdge(source, router, answers, redirects)`；`build_graph()` 遍历它。构造时拒绝五种"看起来合理其实不是"的形状（答案为空 / 答案重复 / 重定向不在答案里 / 重定向指向自己 / `source` 是 `__end__`），`_by_source` 拒绝**同一节点两条边**（langgraph 不禁止，但本表表达不了 —— 导出按 source 取一条，第二条会无声消失）。
2. **`answers` 是声明的，不是从注解读出来的**。看着像重复，是故意的：注解和这张表是对同一件事的两份独立陈述，**比对它们**才是其中一份错了能被发现的唯一途径；由一方推导另一方会把比对变成恒真。与 `RETRY_POLICIES` / `TAKEOVER_HAZARDS` 同一种契约。
3. **`ROUTERS_WITHOUT_AN_EDGE`**：`should_optimize`（被 `shooting_planner_router` 调用的 helper）与 `should_brief_or_optimize`（**没有任何调用者**）—— 两个有 router 形状却没有边的函数，登记而不是删。
4. **入口路由的目的地可读了**。`orchestrator_router` 由 `-> str` 变成 `-> OrchestratorDestination`（`Literal`），路径映射补上唯一缺的键。

### ★ 逐边等价：这一片的判据怎么被量的

改写**之前**先把 `builder.branches` 完整落盘成 golden snapshot（24 节点 / 7 直边 / 18 分支，含每条映射的键序），改写后逐条比对：

| 项 | 结果 |
|---|---|
| 节点集 | 24/24 相同 |
| 直边集 | 7/7 相同（`StateGraph.edges` 是 set，按集合比） |
| 18 个 source、注册名（= router `__name__`）与其**顺序** | 全部相同 |
| 每条边的路径映射 | **仅一处不同**：`orchestrator` 新增 `copywriter -> copywriter` |
| 注解 | **仅一处变化**：`orchestrator_router` 从 `<class 'str'>` 变成 `Literal[...]` |
| 计划 | TREND 22 / BRIEF 24 节点、`reachable_nodes` 24 / 22 全部不变 |

顺序之所以保住了：边表**按图原来的安装顺序写**，所以 `branches` 的插入顺序没变。这一条不是装饰 —— 有一条用例（`test_the_table_keeps_the_branch_order_the_graph_had`）把它钉成一个**字面量列表**，而另一条（`test_the_graph_installs_its_branches_in_the_tables_order`）钉"图确实按表走"；两条各自抓住对方看不见的缺陷（前者看不见 builder 怎么遍历，后者看不见表被重排），docstring 写明了为什么不是冗余 —— 这是本片踩到的坑，见下节 M16。

### ★ 关闭 S1 登记的那条豁免

S1 在 `UNRESOLVED_ROUTER_VALUES` 里登记：brief 模式 `phase=creating` 时 `orchestrator_router` 答 `copywriter`，而路径映射没有这个键（P1d 同形）。S1 留了**反向断言**要求本片显式关闭它。本片：

- 在边表里给入口补上 `copywriter`，于是 `copywriter` 成为**brief 专属**的边（TREND 模板登记 `ExcludedHop("orchestrator","copywriter")`：trend 表里根本没有 `CREATING` 键，`creating` 落到 `trend_scout` 兜底）；
- **删除豁免表与它的两个门类**（`router_answer_no_path_map_entry` 的豁免分支、`exemption_no_longer_applies`）—— 它们的前提"模板可以声明入口答不出的目的地"已经不可能成立，留着就是 S1 自己警告过的那种"长在树上的过期注释"；
- 换成一条**活**的检查 `entry_vocabulary_disagrees_with_the_edges`：各模式声明词表的**并集必须等于**入口边的答案集，**两个方向都比**。这是 `plan.py` 与 `wiring.py` 的接合点 —— 也是"边来自 Plan"这句话在本片里能被检验的形式：`export_plan` 仍只读图，但图现在由那张表装出来。

### ★ 与票面行文的偏离（登记，不是悄悄改）

票面写"改由注册表/Plan 生成"。实现里的注册表是**一张新的、mode-blind 的边表**，不是 `PLAN_TEMPLATES`。理由是本片实测的事实：**图是 mode-blind 的**（S1 已测：从 `orchestrator` 起 24/24 可达，从两个模式入口起各 22 且两集合完全相同），所以边**不可能**由按模式写的模板导出 —— 方向的真相是反的：**`Plan` 是这张表的投影（经图）**。`PLAN_TEMPLATES` 仍然只声明"哪条边属于哪个模式"，两份声明由 `entry_vocabulary_disagrees_with_the_edges` 接住。

### ★ 登记不修的两处

1. **`should_brief_or_optimize` 没有任何调用者**（`routers.py`）：它答 `viral_matcher` 之后的 hop，而图从那走到 `blogger_scout` 用的是直边，早于边表存在。登记进 `ROUTERS_WITHOUT_AN_EDGE`，并配反向断言：它一旦被接上，`test_the_unused_router_is_called_by_nothing` 当场红，强制来删这条豁免。**这是把边变成数据的直接产物** —— 以前没有任何东西会问"这个 router 有边吗"。
2. **trend 模式 `phase=creating` 静默兜底到 `trend_scout`**（trend 表没有 `CREATING` 键，事实 5）。本片只把它钉成行为（`test_trend_mode_creating_falls_through_to_the_scout`），不修：给 trend 选一个目的地是另一次行为裁定。

### 判据（票面 S2 行）如何被满足

| 票面判据 | 本片怎么落 |
|---|---|
| 18 条 `add_conditional_edges` 改由注册表生成 | `backend/graph/builder.py` 里只剩 1 个 `add_conditional_edges`（循环体内）；18 段手写块删净 |
| **逐边等价**（同一个 `builder.branches` 内省） | golden snapshot 逐条比对，差异精确等于那一条预期的修复（见上表） |
| 入口路由（事实 4）是正题 | `OrchestratorDestination`；补上被注解暴露出来的那个键 |
| `_NON_LITERAL_ROUTERS` 缩小或不变 | **空集** —— 18 条边现在**两个方向**都被读：答案无映射（P1d 的 `KeyError`）与映射里有答不出的键（**死键**，此前从未被检查过） |
| 靠现有结构门禁 + `test_routers.py` 钉住 | 接线门禁补上反向那一半；`test_routers.py` 补 7 条 brief 分支行为用例（该分支此前零覆盖）；**没有一条既有用例因为本片意外变红** |

### 门禁与自检

| 项 | 结果 |
|---|---|
| `ruff check .` | 干净 |
| `ruff format --check .` | **524 files**（基线 522 + 2 个新文件） |
| `mypy backend --python-version 3.12` | **209** source files，no issues（基线 208 + `wiring.py`） |
| 基线对比 / 工具运行时门禁 | drift within threshold / P1c-S5 OK |
| `pytest -q` | **3474 passed, 3 skipped**（基线 3438 + **36** 个新用例 = 24 + 2 + 3 + 7） |
| 突变自检 | **22/22 击杀、0 存活**、restore=OK（8/8 文件哈希核验） |

**突变自检首轮 20/22，两条存活都不是"测试太弱"**（这是本片最有价值的两条）：

- **M16（让 builder 反向遍历边表）存活。** 它暴露：我把原来那条"图 vs 表"的顺序断言当成恒真换成了"表的顺序 vs 字面量"，而后者**够不着 `build_graph()` 怎么走这张表**。补法不是二选一，而是**两条都要**：字面量钉表的顺序、图 vs 表钉遍历。**换掉一条恒真的比较，等于把中间那一层缺陷从两道网之间放过去** —— 这正是 S1 的 M11（恒真条件 = 死代码）的同一族，只是这次差一点被我自己的"修好了"掩盖。
- **M09（把 `!=` 改成单向差集）存活。** 查明两个条件**只在另一种门类已经会报的输入上**不同（模式声明了边没有的答案）。补的是行为断言：那种输入下**两级都要报**，把接合点的双向性从注释变成行为。

其余 20 条从锚点唯一性、答案集截断、重定向被忽略、注册名、brief 表、兜底、排除边、重复 source、少装一条边……逐条毙掉；每条击杀都记录了真实的 node id（`rc=4` 会当场报"BAD-ID"，不会被读成击杀）。

### S2 明确未做

没有一条边按模式分支（边表是 mode-blind 的，模式归属由 `PLAN_TEMPLATES` 声明）；`Goal` 仍未成一等输入（11 个 `workflow_mode` 读取点原样，是 S3 的正题）；`workflow.py` 未拆（S4）；没有写 `docs/planning.md`（S5）。

## S3a 交付 —— 模式注册表

**交付物**：`backend/state/modes.py`（278 行，新建）+ 4 个新测试文件
（`tests/unit/state/test_modes.py` 21 用例 · `tests/unit/graph/test_modes_registry.py` 13 ·
`tests/unit/api/test_workflow_mode_boundary.py` 8 · `tests/unit/db/test_workflow_row_mode.py` 5）
+ `tests/unit/api/test_status_label_reuse.py`（+3）；读取点收敛落在
`graph/routers.py`、`agents/orchestrator.py`、`agents/copywriter.py`、`api/routes/workflow.py`、
`graph/plan.py`、`state/hydration.py`、`api/routes/public_showcase.py`、`db/workflows.py`、
`context/models.py`；`docs/execution-plane.md` 的 15 处锚点重指。

### ★ 一次切片拆分（在实现之前，不是事后追认）

票面的 S3 是一次大切片（Goal + 收敛 + 拒绝，风险"中-高"）。侦察后先取消了一个前提：
**"模式是隐含在多处分支里的"** 才是"Goal 编译"与"11 处收敛"**共同依赖**的东西 ——
没有可陈述的模式，就没有可编译的 Goal。于是 S3 拆成 **S3a = 模式注册表**（本片）与
**S3b = Goal 成一等输入**。票面 S3 行在**实现之前**就已改写（见上面的切片表）。

### 做了什么

1. **`ModeSpec`**：一个模式的全部决策面 —— `initial_phase`（`OrchestratorAgent` 写入的相位）、
   `phase_routes`（相位 → 入口节点）、`reanalysis_node`（三个 ripple router 的共同答案）、
   `runs_blogger_selection`（是否走 blogger 循环）。`entry` 是**推导**的（IDLE 路由），
   不是第二次声明 —— 同一个事实的两种写法会漂移，而 `PLAN_TEMPLATES` 已经带着一份
   **独立**声明供 `plan.py` 比对。
2. **两个读者，按"谁有权拒绝"分工**：
   - `get_mode_spec` —— **严格**，未知值 `raise UnknownWorkflowModeError`（具名错误，报出值 + 备选）。
     给**从外面来的**值（请求字段、存储行）。
   - `mode_spec(state)` —— **total**，未知值**兜底到声明默认 + 具名 warning**（带值、带 thread_id）。
     给**从 checkpoint 读出来的** state。
   这个不对称是**刻意的**：在图的节点里 raise 就是 P1d 的形状（`KeyError` 落在没人看的那条路径上），
   且会让本模块出现**之前**持久化的线程变得不可读 —— 撞 P1 红线（存量 checkpoint 可读、永不重写）。
   所以 state 侧的兜底是**声明的**（`DEFAULT_WORKFLOW_MODE`）与**被报告的**，
   而不是由函数默认参数隐含的 —— "缺失"与"未知"因此可区分（前者静默、后者报警）。
3. **请求边界收紧、state 侧不收紧**：`WorkflowStartRequest.workflow_mode` 由 `str` 变成
   `WorkflowMode`（pydantic 对未知值答 **422** 并列出可接受值）；`CheckpointSnapshot`、
   响应模型与 `context/models.py` 的 `workflow_mode` **仍是 `str`** ——
   它们是"存量数据的形状 / 解析后的只读视图"，收紧会把存量线程变成错误。
4. **9 个决策点收敛**：`routers.py` 6 处（相位表、两个 gate 的循环字段、三个 ripple router 的
   reanalysis 答案）、`orchestrator.py` 1 处（初始相位）、`copywriter.py` 2 处（`writes_from_the_brief`）。
5. **`mode_registry_complaints()`**（`graph/plan.py`）：**6 个门类**，把注册表与 S1 的
   `PLAN_TEMPLATES` 逐条比对（模式无 spec / 入口不一致 / 相位表路由集不一致 / 初始相位不落在入口 /
   reanalysis 不是 router 的答案 / blogger 循环字段与排除边相反），并**合并进**
   `plan_registry_complaints()` 的返回值 —— 保持 `== {}` 是全部断言。
   两份声明**互相独立**是它能发现东西的唯一理由：把一方从另一方推导会把比对变成恒真。

### 判据（票面 S3 行）如何被满足

票面逐字：**新增一个模式只改一处（注册表），`grep -rn 'get("workflow_mode"' backend/`
的命中数从 11 降到 1–2。**

| 项 | 结果 |
|---|---|
| `grep -rn 'get("workflow_mode"' backend/` | **11 → 2**，且两处**都在 `state/modes.py` 内部**（`stored_mode` / `mode_spec`）⇒ **注册表之外的读取点 = 0** |
| 新增一个模式只改一处 | 加一行 `ModeSpec`；其余 8 个站点自动受益，而 `mode_registry_complaints` 的六类会检查它与图/模板是否自洽 |
| 未知模式不再静默按 trend | 请求边界：**422**（点名值 + 备选）；state 侧：**声明式兜底 + 具名 warning**（**不 raise**，理由见上） |
| 检查器非空转 | 六个门类逐个注入人造分歧，全部会响；真实树上 `mode_registry_complaints() == {}` 与 `plan_registry_complaints() == {}` 同时成立 |

### 行为等价性

9 个决策点逐点等价：trend/brief 的相位表、两个 gate 的短路、三个 ripple router 的答案、
orchestrator 的初始相位、copywriter 的 brief 分支 —— 全部**同表同值**，
`route()` 的 fallback 复现了原来那句三元兜底表达式。
`tests/unit/graph` + `tests/unit/state` + `tests/unit/agents` = **812 passed**，
**既有测试没有一条因为本片意外变红**。

### ★ 偏离与登记

1. **注册表放在 `state/` 层，但不在 `state/__init__.py` 里导出**。依赖方向是
   `graph/builder.py` → `backend/agents/nodes` → `agents/*` → `state/schema`，
   所以注册表若落在 `graph/`，会被 `agents` 导入成环。而 `state/__init__.py` 有一个明确设计
   （只急加载 stdlib 的 enums、其余 `__getattr__` 惰性，避免拖入 langchain），
   加一个会导入 `pydantic` 的模块会破坏它。⇒ **只加子模块**，调用方直接
   `from backend.state.modes import ...`。
2. **DB 列 `TEXT NOT NULL DEFAULT 'trend'` 保留**（`db/workflows.py:80`）：
   SQL 无法 import 这个模块，**这是唯一结构性的字面量重复**，已在代码里注明。
3. **`context/models.py` 与三个响应模型不收紧类型**（见"做了什么"第 3 条）。
4. **`/status` 的写回改成 `stored_mode(values)`**，并**删掉**外层恒真的
   `if "workflow_mode" not in update_fields` 守卫（那个 dict 四行前刚建成、只含 4 个键）。
   与 S1-M11 同形：**恒真条件 = 死代码，处置是删条件而不是补测试**。

### 门禁与自检

| 项 | 结果 |
|---|---|
| `ruff check .` | 干净 |
| `ruff format --check .` | **529 files**（基线 525 + 4 个新文件） |
| `mypy backend --python-version 3.12` | **210** source files，no issues（基线 209 + `modes.py`） |
| 基线对比 / 工具运行时门禁 | drift within threshold / P1c-S5 OK |
| `pytest -q` | **3527 passed, 3 skipped**（基线 3524 + **3** 个新用例，见下） |
| 突变自检 | **26/27 击杀、0 未预期存活、1 条显式登记**、restore=OK（9/9 文件哈希核验） |

**突变自检首轮 23/27**，4 条存活全部指向同一个结构性事实，且**都不是"测试太弱"**：

> 收敛到注册表的 9 个站点里，有 **3 个站点此前只有"默认模式下不炸"的测试** ——
> 它们的用例 state **根本不带 `workflow_mode`**，所以在"注册表把答案从字面量 `"trend"`
> 换成读 state"之后，这些站点用哪个答案都不可观测。

处置不是改突变，而是**补读者**（三处都是**行为分支**，不是只读字段）：

- **M22 → `test_execute_in_brief_mode_writes_from_the_brief`**：brief 模式的 state 必须走
  brief 分支（断言传进创作者中心的那一层拿到 `"brief"`）。
- **M26 → `test_a_case_payload_publishes_a_mode_it_can_name`**：未知存储值发表为默认值、
  已知值原样发表。顺带修正首轮的**击杀者选错**：三元式的归属函数是 `_case_payload`，
  而首轮挑的 `test_public_result_*` 根本不走它（`_public_result` 只吃 state）。
- **M27 → `test_a_threads_own_mode_survives_hydration`**：视图上的 mode 是线程创建时的 mode
  —— `"trend"` 是**缺失**的兜底，不是**存在**的归一化。这条直接关系红线。
- **M23 登记为已知缺口**：`_generate_style_variants` 里的同一表达式只决定**提示词的措辞**
  （"品牌/产品" vs "选题/角度"），不是行为分支；为它补测试会去断言提示词文本 ——
  那是把巧合钉成不变量。行为的那一半由 M22 覆盖。
  **这是"声明的**缺口**、不是测出来的"**。

其余 23 条从默认值、锚点、兜底、严格读、`is_known_mode`、六个门类、三个 ripple router、
两个 gate、orchestrator、行解码、`/status` 写回逐条毙掉。**`rc` 分档把关**：
只有 `rc == 1` 算击杀，`rc == 4/5` 是 node id 写错（**假击杀**）、`rc == 2` 是收集错误，后两者都不算。

**harness 自身的三条改进**（本片产出）：

- **锚点检查是"组"属性**：同一段文本出现 N 次、由 N 个条目按**出现序号**覆盖时，
  判据是**声明序号恰好等于 1..N** —— 写成"每条 `count == occ`"会把自己正确的条目报成坏的
  （首轮就误报 4 条）。
- **用 `subprocess.run(timeout=)` 替代进程内看门狗**：超时会 kill 子进程、异常在 `finally`
  覆盖的帧里抛出 ⇒ 恢复路径**必然执行**，不必走 `os._exit` 那条跳过 `finally` 的危险路径。
- **开局脏树拒绝**（`git status --porcelain` 必须逐行等于本片声明的文件集）——
  它在本次运行里**真的拦下过一次**（我补完三个测试文件后忘了更新声明）。

### S3a 明确未做

- **Goal 仍未成一等输入**：`/start` 的 26 键字面量、`if req.workflow_mode == WorkflowMode.BRIEF`
  特例原样（S3b 的正题）。
- **没有动 `PLAN_TEMPLATES`**：注册表声明"模式**怎么决策**"，`PLAN_TEMPLATES` 声明
  "哪条边**属于哪个模式**"，两份声明由 `mode_registry_complaints` 接住。
- **没有给 trend 模式 `phase=creating` 选目的地**（S2 登记的行为问题）。
- **`workflow.py` 未拆**（S4）；**`docs/planning.md` 未写**（S5）。
## S3b 交付 —— Goal 成一等输入

**交付物**：`backend/state/goal.py`（155 行，新建）+ 2 个新测试文件
（`tests/unit/state/test_goal.py` **23** 用例 · `tests/unit/api/test_start_goal.py` **16** 用例）；
`backend/api/routes/workflow.py` 的 `/start` 改为由 `Goal` 编译；前端 4 处
（`types/workflow.ts` · `stores/workflow.ts` · `views/AgentTUI.vue` · `views/Home.vue`）
随之不再传 `phase`。

### ★ 侦察取消了一个前提：`req.phase` 从来不影响「这次 run 去哪」

票面把 S3b 写成"26 键字面量 + BRIEF 特例 → Goal → 编译"。侦察先推翻了两件小事：

1. **字面量是 24 键，不是 26**（票面事实 11 的行号也已过期 —— 那是 S3a 改动造成的偏移）。
2. **`WorkflowStartRequest.phase` 对图完全无效**。图入口恒为 `orchestrator`
   （`builder.py:149` 的 `add_edge(START, "orchestrator")`），而它跳过自己的前两个分支后
   **无条件**返回 `mode_spec(state).initial_phase`（`orchestrator.py:38`）。实测：
   trend 请求 `phase=analyzing` ⇒ 写 `SCOUTING`；brief 一律写 `BRIEFING`。
   于是客户端指定的起点相位**只有两个读者**：DB 的相位列与 `/start` 响应的 `phase`
   —— 而**这两个值恒与图不符**（响应说 analyzing、图从 scouting 跑；前端
   `stores/workflow.ts` 还拿这个响应的值去初始化 UI 的相位）。

⇒ 起点相位因此收敛回**模式事实**（`ModeSpec.initial_phase`）：图里 orchestrator 读的、
`Goal` 编译的、DB 行与响应写的，**是同一个字段**。`Goal.start_phase` 是它的唯一陈述。

### 做了什么

1. **`Goal`**（`backend/state/goal.py`）：一次 run 的意图 —— 模式、执行模式、目标
   （`topic` / `niche` / `niche_resolution` / `brief`）、开关（`dry_run` / `auto_publish`）、
   thread 与创建时刻。冻结 dataclass；**不进 state、不进图**（不撞"新 run 新 schema、
   存量 checkpoint 不重写"）。
2. **`compile_initial_state()`** 是**全仓唯一**构造那 24 键的地方（原来是路由里的字面量）。
   逐键等价，含"不 seed `performance_log`"那条 P1a-S2 的理由。**一处精度收敛**：原来
   `created_at` / `updated_at` / DB 行的 `now` 是**三次** `datetime.now()`，现在同一个值
   —— 一次 run 只被创建一次，三个值互相差几微秒从来不是设计。
3. **`BriefInput`** 把"正文进 Artifact Store 还是内联"这对目的地变成一个值（`body` +
   可选 `ref`），`as_state_fragment()` 是唯一的落键处。`put_artifact` 的 IO 留在路由
   （`_seed_brief_payload`）—— 编译器不做 IO。
4. **`waits_for_brief_upload`** 替掉路由里的
   `req.workflow_mode == WorkflowMode.BRIEF and not req.brief_text`。
5. **`WorkflowStartRequest.phase` 移除**，前端 4 处同步。**向后兼容是实测的**：
   pydantic 默认 `extra="ignore"`，老客户端继续传 `phase` 得到 200，且**结果与不传完全相同**
   （`test_a_client_still_sending_one_is_not_refused` / `..._changes_nothing`）。
6. 顺带删掉两处 `isinstance(phase, WorkflowPhase)` 的字符串化守卫和一次重复的相位计算
   （`Goal.start_phase` 恒是具体成员）。

### 判据

票面没给 S3b 单独判据（S3 那条是**模式侧**的收敛，已由 S3a 兑现）。本片按同一精神取了
三条可复核的口径：

| 项 | 结果 |
|---|---|
| 模式判断离开流程 | `grep -n 'WorkflowMode.BRIEF' backend/api/routes/workflow.py` **2 → 1**，剩下那一处是 `_seed_brief_payload` 的**输入门**（"这个模式有没有 brief 正文可放"），不再改相位、不再决定是否启动 |
| 字面量消失 | `grep -n 'initial_state: dict\[str, Any\] = {' backend/api/routes/workflow.py` → **0**；`grep -rn 'req\.phase' backend/` → **0** |
| run 的起点只有一处陈述 | `Goal.start_phase` → `ModeSpec.initial_phase`；图输入、DB 行、响应三者由同一个值导出，且"请求说什么都不影响"被 `test_a_trend_run_starts_at_scouting_however_it_asked` 钉住 |

### 行为等价性

24 键**逐键等价**：键集做**双向**比对（`== SEEDED_KEYS` 与 `sorted(...) == sorted(...)`），
而 `SEEDED_KEYS` 是从被替换的字面量**转录**的、不是从被测对象导入的 —— 否则它就是恒真。
值逐键断言（`test_every_value_is_the_one_the_literal_wrote`）。

**改动的唯一可观测差异**：`trend` + 显式传非默认 `phase` 的请求，其 DB 相位列与响应
`phase` 从"客户端值"变成 `scouting` —— **这正是修掉那个矛盾**（原来响应与 DB 都和图不一致）。

### ★ 登记不改（票面已裁界）

**`execution_mode` 是同一个病的第二个实例**：`WorkflowStartRequest.execution_mode` 是裸
`str`（`:511`），`routers.py:320` 有 `state.get("execution_mode", "single")` 字面量兜底，
`ExecutionMode` 枚举（`state/enums.py:53`）在边界处不用，而
`tests/unit/state/test_execution_mode.py` 的头两条断言
（`ExecutionMode.SINGLE == "single"`）因 `StrEnum` 而**恒真、零信息量**。
但票面"拒绝"节第 2 条明确**不动这条轴**（它与本片的"计划"正交）⇒ 本片**只登记不修**。
将来若要收，照 S3a 的两读者形状即可（边界严格 422、state 侧 total + 具名 warning 兜底），
不需要新设计。

### S3b 明确未做

- **`_run_graph_and_persist` 的另外 11 个调用点**（`review.py:204`/`:385` ·
  `optimization.py:93`/`:157` · `blogger.py:118` · `workflow.py` 的 resume/retry 路径）
  各自的 `input_data` 构造**原样** —— `Goal` 让它们**可以**被收，但那是另一片。
- **`Goal` 不写进 state**：它是输入端的值，编译完就结束，所以没有任何 checkpoint schema 变化。
- **DB 的相位列与响应形状不变**（都还是 `str`）。
- `workflow.py` 未拆（S4）；`docs/planning.md` 未写（S5）。

### 突变自检

18 条突变 · **18 击杀 / 0 存活 / 0 bad-id / 0 error / restore=OK**（每条都先跑 step 0：
未改动树上全部击杀者必须为绿，否则"击杀"可能来自本来就是红的用例）。覆盖两个新增文件的
起点相位、等待条件、brief 的两种落点、24 键的增删、模式传递、时间戳一致性，以及请求边界上
"把 `phase` 加回去"这条反向断言。

首轮 **17/18**，唯一存活的 **M03 是击杀者挑错，不是覆盖缺口**：
`test_trend_starts_at_scouting` 测的是 `Goal.start_phase` **属性**，而 M03 改的是
`compile_initial_state()` 发出的**键值** —— 用例根本没有经过被突变那一层。换成直接读编译结果的
`test_the_phase_reaches_the_state_as_a_concrete_phase` 后击杀。与 S2/S3a 记的是同一个坑：
**击杀者必须真的走被突变那一层**，属性级用例杀不死同一事实在编译器里的突变。

**同轮撞到并修好的一处真实回归**：`workflow.py` 的行号变动让
`docs/execution-plane.md` 的 5 处 `file:line` 锚点（三条 `create_task`、一条
`_run_publish_retry`、一条 `ensure_future`）全部失效 —— 由 S3a 立的
`tests/unit/scripts/test_docs_anchors.py` 在**全量 pytest** 里当场抓住，已按
"离原行号最近的出现"重指。**这就是那个门禁存在的理由**：锚点腐烂不会自己报错，
而一个坏的锚点比没有锚点更糟，因为读者会信它。

## S4 交付 —— `workflow.py` 分层

**交付物**：`backend/api/routes/workflow.py` **3001 行 → 254 行**（-91.5%），按 **6 层**落进 5 个新模块，另加一个新门禁。**共 37 个文件**（31 改 + 6 新）。

| 层 | 模块 | 行数 | 装什么 |
|---|---|---|---|
| api | `workflow.py` | 254 | router + 18 个薄 handler + 转出的请求/响应模型 |
| application | `_wf_application.py` | 1876 | 16 个端点实现 |
| runtime | `_wf_runtime.py` | 406 | 任务注册表 / resume / takeover / 孤儿判定 |
| actions | `_wf_actions.py` | 371 | **唯二绕过 `_run_graph_and_persist` 的 retry** |
| artifacts | `_wf_artifacts.py` | 251 | 历史文件 / checkpoint 快照 / 文档渲染与抽取 |
| models | `_wf_models.py` | 195 | 9 个 pydantic 模型 |

其余 31 个改动文件：2 处生产导入点（`_takeover.py:142` 的 `_resume_phase_for_next_nodes` /
`_start_resume_task`、`_runner.py:455` 的 `get_progress`）、**24 个测试文件**（~125 处 patch /
import 重接线，含 `test_hydration.py` 的 `_DEAD_STATE_MODULES`）、2 处陈旧注释
（`state/artifacts.py`、`frontend/.../types.ts`）、2 份文档的 **14 个 `file:line` 锚点**
（`docs/execution-plane.md` 9 处 + 缺席表 5 行新增 + `docs/tool-runtime.md` 2 处）。

### ★ 更正一处本片自己写下的记法：层名不是从既有门禁继承的

设计阶段一度把六个层名归因于「既有门禁里已经写着的五个名字」。**这是错的，已核实并撤回**：

```
git grep -n '_wf_application\|_wf_runtime\|_wf_artifacts\|_wf_actions\|_wf_models' ec64fa86
→ 零命中
```

真实来源是两条：五个角色名（api / application / runtime / artifacts / actions）
**来自票面 S4 行本身**；`models` 是**本片加的第六层**，理由是结构性的而非口味 ——
handler 的签名注解与实现的注解都要模型，模型放 `application` 就 `api ↔ application` **成环**，
而模型是「类型不依赖行为」的天然叶子。（`from __future__ import annotations` 让注解在运行时
是字符串，所以这个环只由 pydantic 的**真求值**造成 —— 它会真炸，不是隐患。）

顺带一提，`actions` 也**不是**口味分类：它是 `docs/execution-plane.md` §7 登记的两条
**不持租约写入者**（`_run_retry` / `_run_publish_retry`）。把它们单放一层，是把「唯二绕过统一
执行入口的路径」从一条注释变成**一个目录事实**。

### 做了什么

1. **先立边界，再挪代码。** 源文件里**每个符号都是顶层定义**，所以可以**逐行原样切片、零缩进变化** ——
   这既是「纯搬移」成立的前提，也是它能被机器检查的原因。
2. **端点一分为二**：装饰器 + 签名 + docstring 逐字留在 api 层的薄 handler 上，函数体原样搬进
   `_wf_application` / `_wf_actions`；handler 只有一条 `return await _wf_<layer>.<同名>(...)`。
   同名是设计 —— 签名与 docstring 因此可以直接逐字段比对。
3. **零外部调用者的私有符号**（`_extract_ripple` / `_failed_node` 等）跟着唯一的调用者走，
   不新建「工具层」。
4. **四个改名导入不再复制**：`from backend.db.workflows import get_workflow as db_get` 这类
   别名随代码去了调用点所在的层，api 层不再持有它们。

### 判据（票面 S4 行）如何被满足

**① 行数口径可复核** —— 7 个巨型端点的实测行数（AST `end_lineno - lineno + 1`）：

| 端点 | 旧 | 新 |
|---|---|---|
| `resume_workflow` | 327 | 5 |
| `get_workflow_status` | 247 | 5 |
| `retry_publish` | 179 | 14（其中 10 行是 docstring） |
| `recover_workflow` | 159 | 14 |
| `retry_ripple_analysis` | 153 | 5 |
| `start_workflow` | 145 | 5 |
| `stream_workflow_progress` | 142 | 13 |

合计 **1352 行 = 3001 行的 45.1%**，全部降到**百行以内**；`workflow.py` 现在最大的函数是
**14 行的 `workflow_account_totals`**。
★ 票面写的是「1397 of 2999 = 47%」，与实测差 **45 行** —— 差在「函数行数」是否把装饰器与
函数之间的空行算进去。本片一律以 AST 为准，实测数记在这里。

**② `/status` 响应形状与拆分前逐字段相同** —— 用**同一个探针 + 同一份 fixture** 在 `ec64fa86`
的 `git worktree` 与分层后的树上各跑一次，**`diff` 为空**（envelope 5 键 + 41 个顶层字段的完整
嵌套形状：2 层深度 + 列表元素形状）。探针留在仓里（`test_workflow_layering.py::_status_shape`），
结果冻成 `_STATUS_SHAPE` 常量。在拆分前的树上跑时**只做了一处替换**：patch 目标后缀
`_wf_application` → `workflow`（那一版只有一个模块）—— 探针、fixture、断言全部逐字相同。
值的另一半早已被 `test_legacy_read_faces.py` 逐字段钉住（legacy fixture 的每个大字段 byte-equal）；
本片钉的是**形状**，正是票面的措辞。

### ★ 本片最大的一处风险，与它的守卫

搬走 3000 行会留下约 125 处 `patch("backend.api.routes.workflow.X")`。
**`patch` 按「被 patch 的模块的命名空间」解析** ⇒ 目标必须落在**真正读 X 的那一层**。
搬走读点而把同名属性留在原处 = `patch` **成功且什么都不影响** —— 静默失效，测试照绿。

- 重接线按**调用点**挑层（application → actions → runtime → artifacts → models 的优先序），
  而不是按符号的定义位置；
- 逐个用例判定「这条测试的哪条代码路径在读它」：`db_update` 被 application 与 runtime
  **同时**读 ⇒ `test_workflow_stale.py` 指 runtime、`test_publish_retry.py` 指 actions；
  `_start_resume_task` 被 runtime 的 `_resume_past_evaluator_pause` 与 application 的
  `resume_workflow` 端点体**同时**读 ⇒ 为 legacy 路径单独留 `_START_RESUME_LEGACY`，
  两条路径各自可定位；
- 新增 `test_the_api_layer_does_not_re_export_the_implementation_symbols`：**api 层一旦重新
  导出实现符号，上述老 patch 目标会「复活」成静默空转** ⇒ 把这份**缺席**断言下来
  （只排除 handler 与实现**同名**的那些 —— 那是设计，不是泄漏）。

### 门禁与自检

四道门禁全绿：`ruff check` 通过 · `ruff format --check` **538 files**（S3b 的 532 + 6 = 5 个新层
文件 + 1 个新测试）· `mypy backend` **216 source files**（211 + 5，测试不在 mypy 范围）· 基线对比
`drift within threshold` · 工具运行时门禁 OK。**全量 `pytest` 3572 passed / 3 skipped**
（S3b 的 3566 + 6 = 新门禁的 6 条用例，数字恒等）。前端 `npm run type-check` 通过。

新门禁 `tests/unit/api/test_workflow_layering.py` 的 6 条：**形状快照** + 5 条边界 ——
路由清单（handler 名 + 方法 + 路径，**源码装饰器与 FastAPI 实际注册两侧都比**，只比路径会漏掉
「两个 handler 互换装饰器」）、每条 handler 恰好一条 forward、handler 与实现签名/docstring 的
AST 等同、模块 docstring 里发布的层表与实际文件一一对应、api 层不重新导出实现符号。

### 突变自检

17 条突变 · **17 击杀 / 0 存活 / 0 bad-id / 0 error / restore=OK**（每条先跑 step 0：未改动树上
所有击杀者必须为绿；锚点前置检查 17 条各**唯一**）。

覆盖：handler 多一条语句 / forward 指向另一个名字 / forward 伸进更低的层 / handler 签名漂移 /
handler docstring 漂移 / **实现侧 docstring 漂移**（反向）/ 删掉层表的一行 / 删装饰器 / 改路径 /
两个 handler 互换装饰器 / 加一条表外路由 / `/status` 多一个字段 / `/status` 改字段类型 /
api 层重新导出实现符号 / 文档锚点漂一行 / 缺席锚点点到「有该 token 的那一行」/
从 `start_lease` 缺席表里删掉新增的一行。

首轮 **16/17**，唯一存活的 **M17 是覆盖缺口、不是等价突变**：缺席表的行数下限还停在 `>= 3`，
而本片把它从 **3 行扩到 8 行**（`start_lease` 从「这个文件里没有」改成「这六个文件里都没有」），
于是删掉其中任一新行**没人发现**。修法是**补下限而不是补测试**（`>= 8`，与锚点表的 `>= 43`
同一纪律：**下限就是文档实际发布的条数**），并在注释里注明是被突变找到的。这条缺口是本片自己
制造的 —— 表格长了下限没跟着长，是「加行」这个动作的固定副作用。

★ 「纯搬移」这个主张要**分两半**说：
- 前半（一次性、机器可证）：搬走的每个符号在两侧 `ast.dump` 等同（**55 个符号 + 18 个 handler
  签名**；端点比对剥掉 `decorator_list`，因为装饰器**按设计**留在 handler 上）。这一步的脚本
  **没有留在仓里** —— 它钉的是「搬移那一刻」的等价，留成长期门禁会变成钉住死字节；
- 后半（永久）：`/status` 形状快照 + 全量 3572 用例。

所以「纯搬移」不是一句自述，而是**一次性的结构证明 + 永久的行为证据**。

### S4 明确未做

- **`_run_graph_and_persist` 的 12 个调用点各自的 `input_data` 构造**原样（S3b 已登记的同一件事）。
- **`review.py` / `optimization.py` / `blogger.py` 未分层** —— 它们也调 `_run_graph_and_persist`，
  但不在本片判据里。
- **api 层的行为一个字没改**：没有加中间件、没有加日志、没有统一的异常包装。
- **`workflow.py` 不保留任何向后兼容的再导出**（有意，理由见上）。因此 `backend/api/routes/__init__.py`
  的 `workflow_router` 惰性入口是这一决定唯一下游影响面，实测未动。
- `docs/planning.md` 未写（S5）。
