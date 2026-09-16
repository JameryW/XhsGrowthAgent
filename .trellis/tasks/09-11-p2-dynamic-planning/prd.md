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
| 11 | **「Goal」今天不是对象，而是「哪个端点 + 往 state 里塞了什么」** | 12 个 `_run_graph_and_persist` 调用点分布在 5 个文件（`workflow.py` 7 · `review.py:204`/`:385` · `optimization.py:93`/`:157` · `blogger.py:118`）；`/start` 的 `initial_state` 是字面量 **26 个键**（`workflow.py:712-740`），模式差异是一句 `if req.workflow_mode == "brief":`（`:742`）改 `phase` 并决定正文内联还是进 Artifact Store（`:744-760`） | 输入端没有 Goal，只有"端点 + 字典字面量" |
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
| **S1** | **Plan 的只读导出**：`Plan` / `PlanStep` 对象 + **穷举模板注册表**（`WorkflowMode` → 节点序列 / 依赖），由一个**只读**函数从 `build_graph()` 的边导出并与注册表**双向比对**。执行路径**零改动**（没有执行代码读它）。判据 = 结构比对门禁，照 `test_conditional_edge_wiring.py` 的手法 | 低 |
| **S2** | **边来自 Plan**：`build_graph()` 的 18 条 `add_conditional_edges` 改由注册表/Plan 生成，**逐边等价**；靠现有结构门禁 + `test_routers.py` 钉住。入口路由（事实 4）是这一步的正题：目的地从"读不出的 `str`"变成"可读出的声明" | 中 |
| **S3** | **Goal 是一等输入**：`/start` 的 26 键字面量 + `if workflow_mode == "brief"` 特例 → `Goal` → 编译；**11 个模式读取点收敛到一处**（事实 3），未知模式**拒绝**而不是静默按 trend | 中-高 |
| **S4** | **`workflow.py` 分层**：7 个巨型端点（47% 行）按 api / application / runtime / artifacts / actions 拆；先立边界再挪代码，**纯搬移**、无行为变更 | 中 |
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
- **不动 `ExecutionMode`（single/continuous）的语义**（事实 7 的第二条轴）：它与本片的"计划"正交，混在一起会让两件事互相污染。
- **不合并 `WorkflowPhase` 的两份定义**（事实 9）：它们今天逐字一致、没有行为分歧，而动 `api/generated/**` 属于生成物边界之外的事。**登记为潜伏的漂移面**，不改。

## 验收

- 每片**独立 PR**，独立通过四道门禁（`ruff check` / `ruff format --check` / `mypy backend` / 基线对比 + 工具运行时门禁）与 `tests/unit` + `tests/integration`。
- **S1 的判据是双向结构比对**：注册表 ↔ `build_graph()` 的边，两个方向都比（注册表声明的每个节点必须在图里、图里每条边必须在注册表里有归属）；并且要有一条**非平凡用例**证明这个检查器不是空转（复现一次历史形状的缺陷）。
- **S2 的判据是等价性**：改写后的图与改写前**逐边相同**（同一个 `builder.branches` 内省），且 `test_conditional_edge_wiring.py` 的豁免清单**缩小或不变**（事实 4 修好后 `_NON_LITERAL_ROUTERS` 应当只剩空集）。
- **S3 的判据是收敛**：新增一个模式**只改一处**（注册表），`grep -rn 'get("workflow_mode"' backend/` 的命中数从 11 降到 1–2。
- **S4 的判据是行数口径可复核**：`workflow.py` 的 7 个巨型端点消失或降到百行以内，且 `/status` 的响应形状与拆分前逐字段相同。

## 待决（需要裁定，先登记不擅自动手）

1. **Plan 的粒度**：`PlanStep` 应该对齐**节点**（`trend_scout`、`content_strategist`…）还是对齐**能力**（P1c 的 ToolSpec capability）？前者与今天的 `builder.branches` 一一对应、S1 可零风险导出；后者才通向"由 Goal 编译"，但会引入第二套命名。S1 先按**节点**做（可导出即可验证），把能力粒度留到 S3 再定。
2. **未知 Goal / 未知模式的行为**：今天静默按 `trend`（事实 3、5）。改成拒绝会**改变行为**（新 4xx 路径），需要一次明确的裁定；本片默认在 S3 里按"拒绝 + 具名错误"处理。
3. **S5 是否应该是文档**：如果 S1–S4 暴露出"确实需要非模板图"的证据，S5 就不再是文档，而是那条路径本身（P2b 的 S4 就是这种形状）。**按证据走，不按计划走。**
