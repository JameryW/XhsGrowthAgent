# 计划（Planning）

> P2c 的交付面。它回答一个问题：**一次 run 打算做什么，这份「打算」由谁陈述，以及在什么证据下才允许它不再是一张模板。**
>
> 本文件发布的每个数字都由 `tests/unit/scripts/test_planning_claims.py` 从代码**重算** —— 与 `docs/execution-plane.md` 的 `file:line` 锚点不同，这里钉的是**事实**而不是**位置**：节点数变了、模式数变了、计划的读者出现了，测试就红。为什么换一种钉法，见 §5。

## 0. 结论：S5 是文档，按证据

票面「待决」第 3 条把它写成一次裁定 —— 如果 S1–S4 暴露出「确实需要非模板图」的证据，S5 就不再是文档，而是那条路径本身（P2b 的 S4 就是那种形状）。**没有暴露。四条：**

| # | 证据 | 为什么它反驳「现在需要非模板图」 |
| --- | --- | --- |
| A | **零真实样本。** `.xhs/checkpoints.sqlite` 的 `checkpoints` 与 `writes` 两张表各 **0 行**；`.xhs/history/` 的 173 个文件里 **172 个是 21 字节**的测试残留，唯一一个 115 字节的是 5 键存根（`phase=scouting`、`current_agent=trend_scout`，没有 goal、没有 niche、没有终态）。复现：`find .xhs/history -type f -printf '%s\n' \| sort -n \| uniq -c` | 「计划与实际不符」这件事在样本里**一次都没发生过**，因为没有实际 |
| B | **两张模板只差两个节点**（§1.3）：trend 22 / brief 24，对称差恰好 `{brief_analyzer, brief_gate}`，且 trend 的计划是 brief 的**真子集** | 「模板」不是两次剪枝，是**同一张图的两个入口**。模板今天的剪枝幅度是 **0–2 个节点**（共 24）⇒「用动态规划省节点」在本仓**没有存量可省** |
| C | **S1–S4 登记的每一处缺口都是「声明不完整」，不是「声明形状错」**（§4 逐条） | 缺一个键、少一条排除、一个没人调用的 router、一条被票面裁走的正交轴 —— 全部是在模板**上**补，不是在模板**外**另起一套 |
| D | **计划今天没有任何生产读者**（§1.5）：`backend/**/*.py` 里 import `backend.graph.plan` 的 **0 个** | 就算今天能生成一张非模板图，也没有任何东西会读它 —— **第一个消费者不存在** |

四条合起来是同一句话：**今天缺的不是生成器，是「一次 run 的计划」这条陈述本身**（S1 的定性）。它现在有了一半 —— 按**模式**可陈述；另一半（按 **run** 可陈述）是开闸的前置条件，在 §2.4。

## 1. 今天的一张「计划」是什么

（下文所有数字实测于 2026-09-17，`e0928e66` = P2c-S4 合并后的 main。）

### 1.1 两个对象

**`Goal` —— 一次 run 的意图**（`backend/state/goal.py` 的 `Goal`）：模式（`mode`）、目标（`topic` / `niche` / `niche_resolution` / `brief`）、开关（`dry_run` / `auto_publish`）、身份与时刻（`account_id` / `thread_id` / `created_at`）。11 个字段。

- 两个属性是**推导**的，不是字段：`start_phase`（= 该模式的 `initial_phase`，客户端**不可指定** —— S3b 移除了 `WorkflowStartRequest.phase`，因为实测它对图完全无效）、`waits_for_brief_upload`。
- **`compile_initial_state()` 是全仓唯一**把一次 run 变成起始 state 的地方（claim `goal_initial_state_keys`）。它之前是路由里的一个字面量。
- **`Goal` 不写进 state** ⇒ 没有任何 checkpoint schema 变化，存量线程不必重写（P1a 红线）。
- **边界**：`execution_mode` 是 `str`，**不是** `ExecutionMode` —— 见 §3 第 2 件。
- **今天只有一个端点用它编译**（`POST /start`）；另外 11 个 `_run_graph_and_persist` 调用点各自构造 `input_data`（§1.5）。

**`Plan` —— 一个模式下这次 run 可能访问的节点**（`backend/graph/plan.py` 的 `Plan`）：`entry` + `steps`，每个 `PlanStep` 带 `preceded_by` / `followed_by`。`export_plan(mode)` 只读地从 `build_graph()` 导出；模板声明了图里没有的东西时 `raise PlanExportError`，**不产出一份悄悄丢掉解析不了那条边的计划**。

- ★ **`Plan` 不陈述顺序。** `steps` 按节点名排序（claim `plan_steps_are_sorted_by_node_name`）。顺序在**图**里，不在计划里 ⇒「先做 A 后做 B」这种要求今天**无法被计划表达**（§2.2 的 E3）。
- ★ **`Plan` 是只读投影**：没有任何生产代码 import 它（claim `production_importers_of_the_plan`）。
- **`Plan` 不是执行指令**：它不含能力、预算、租约与人工闸门 —— 那些分别在 P1c 的 `ToolSpec`、P2b 的租约、P2a 的 `DecisionRequest` 里。本文件只谈「打算做什么」。

### 1.2 它不是什么（三个容易撞名的东西）

- **不是 `WorkflowPhase.PLANNING`**：那个相位今天的语义是「进入 `content_strategist`」。两个词撞车，本文件说的「计划」与它不是一回事。
- **不是 `TaskType`**：那个名字已被「模型路由键」占用（`backend/config/models.py`）；评审里六个核心对象中的 `Task` **尚不存在**。
- **不是 P1c 的 `ToolSpec` 能力粒度**：本片的步对齐**节点**。票面「待决」第 1 条已裁：先按节点做（可导出即可验证），能力粒度留到「由 Goal 编译」真要做的时候再定。

### 1.3 实测的数字

<!-- claim-table:begin -->

| 主张 | 发布的值 | 复核方式 |
| --- | --- | --- |
| `graph_nodes` | `24` | `len(graph_nodes())` |
| `graph_direct_edges` | `7` | `len(build_graph().edges)` |
| `graph_conditional_edges` | `18` | `len(CONDITIONAL_EDGES)` |
| `reachable_from_root` | `24` | `len(reachable_nodes("orchestrator"))` |
| `reachable_from_trend_entry` | `22` | `len(reachable_nodes("trend_scout"))` |
| `reachable_from_brief_entry` | `22` | `len(reachable_nodes("brief_analyzer"))` |
| `entry_reachability_is_mode_blind` | `true` | 上面两个集合**相等** |
| `trend_plan_nodes` | `22` | `len(export_plan("trend").nodes)` |
| `brief_plan_nodes` | `24` | `len(export_plan("brief").nodes)` |
| `plan_symmetric_difference` | `brief_analyzer, brief_gate` | 两个计划节点集的对称差 |
| `trend_plan_is_a_subset_of_brief_plan` | `true` | `set(trend) <= set(brief)` |
| `plan_steps_are_sorted_by_node_name` | `true` | `Plan.steps` 是按节点名排序的 ⇒ **计划不陈述顺序** |
| `trend_exclusions` | `5` | `len(PLAN_TEMPLATES[TREND].excludes)` |
| `brief_exclusions` | `6` | `len(PLAN_TEMPLATES[BRIEF].excludes)` |
| `workflow_modes` | `brief, trend` | `sorted(WorkflowMode)` |
| `plan_templates` | `brief, trend` | `sorted(PLAN_TEMPLATES)` |
| `goal_initial_state_keys` | `24` | `len(Goal(...).compile_initial_state())` |

<!-- claim-table:end -->

### 1.4 为什么模板是「声明」，而不是从图导出

**图是 mode-blind 的**：从 `orchestrator`（真正的种子，`build_graph()` 的 `add_edge(START, "orchestrator")`）起 **24/24** 节点可达；从两个模式的**入口**起各 **22**，而且两个集合**完全相同**（掉出去的是 `orchestrator` 与 `analyst` —— 回到根的唯一入边来自 `analyst` 自己，与模式无关）。

⇒ 拓扑**不可能**告诉你要走哪个模式。模式归属只能**声明**；而把 24 个节点的归属手写一遍，是一份**没有任何东西能佐证**的声明。所以 `ModeTemplate` 缩到三件：

- `entry` —— 一次新 run 进入的节点；
- `destinations` —— 这个模式下入口路由器会给出的**全部**答案（各模式的并集必须**恰好等于**入口边的答案集，双向都比）；
- `excludes` —— 图里有、这个模式走不到、且**注明是哪个 router 决定的**的 hop。`decided_by` 与图里注册在那个 source 上的 router 比对，所以一次排除**不能记在一个与它无关的 router 头上**。

于是「两张模板」的真实形状是：**同一张图 + 一处入口 + 11 条走不到的 hop**（trend 5 条 / brief 6 条）。

### 1.5 今天还不存在的读者

<!-- claim-table:begin -->

| 主张 | 发布的值 | 复核方式 |
| --- | --- | --- |
| `production_importers_of_the_plan` | `0` | AST：`backend/**/*.py` 里 `import backend.graph.plan` 的文件数 |
| `workflow_mode_reads_total` | `2` | AST：state 键的读取点，**两种形状都算**（`state.get("workflow_mode")` 与 `state["workflow_mode"]`） |
| `workflow_mode_reads_outside_the_registry` | `0` | 上面那 2 处的文件不是 `backend/state/modes.py` 的个数 |
| `run_graph_and_persist_call_sites` | `12` | AST：`_runner._run_graph_and_persist(...)` 的调用点 |
| `routers_without_an_edge` | `should_brief_or_optimize, should_optimize` | `wiring.py` 的 `ROUTERS_WITHOUT_AN_EDGE` |
| `plan_registry_complaints_is_empty` | `true` | `plan_registry_complaints() == {}` |

<!-- claim-table:end -->

`workflow_mode_reads_total` 之所以**两种形状都算**，是因为票面 S3a 的判据是 `grep -rn 'get("workflow_mode"' backend/` —— 那个形状只覆盖 `.get(...)`，**看不见下标读取**。本文件把它补全：今天全仓的读取点恰好两处，两种形状合计仍是 **2**，仍**都在注册表内**。

（扫描必须**不把写入算进来**：`backend/api/routes/_wf_application.py` 有一处 `update_fields["workflow_mode"] = stored_mode(values)`，那是往 **DB 行**里写字段名，不是读 state —— 而且它读的 `stored_mode` 正是注册表的两个读者之一。同族的陷阱：路径比较要用 `Path` 而不是字符串包含，Windows 上 `backend\state\modes.py` 不含 `state/modes.py`。）

## 2. 动态规划的开闸条件

### 2.1 闸门问的是哪一个问题

> 一次 run 需要的计划，**是否与它模式的模板不同**。

只有当「**同一个 mode、不同的 goal、需要不同的计划**」真的发生时，模板才不够。今天 `export_plan(mode)` 只吃 **`mode` 一个参数**（claim `trend_plan_nodes` / `brief_plan_nodes` 是它的全部输出面），所以这句话在当前代码里**恒为假**：同一个 mode 永远得到同一份计划。闸门要等的，就是让这句话**第一次为真的那个样本**。

### 2.2 算证据的：三条，且只有三条

计划的词汇表只有三样 —— **节点 / hop / 顺序** —— 所以「模板服务不了这个 goal」只能以这三种形状出现：

| # | 形状 | 具体是什么 | 今天 |
| --- | --- | --- | --- |
| **E1a** | 缺节点（图里**有**，该模式到不了） | goal 要求一个该模式计划里没有、但图里存在的节点 | 只有一处：trend 到不了 `brief_analyzer` / `brief_gate`（claim `plan_symmetric_difference`）⇒ 这是**模式选错了**，不是规划不够。解是换模式，或给这个模式补一条边 —— 两者都在现有机制内 |
| **E1b** | 缺节点（图里**根本没有**） | goal 要求一个图里不存在的节点 | **0 例**。这才是模板**吸不住**的东西。注意它同时意味着**加节点加边**，而本片的目的正是「停止新增 `workflow_mode` + router + edge」⇒ E1b 一旦成立，**本片的目标本身要被重新裁定** —— 那是父任务的事，不是 S5 能决定的 |
| **E2** | 缺 hop | goal 需要一条它的模式**明确排除**的 hop（`ExcludedHop`） | **0 例**。今天有 11 条排除，**每条都注明是哪个 router 决定的** ⇒ 提 E2 时必须**指名那个 router**。一个不指名 router 的「我需要 A 到 B」是希望，不是证据 |
| **E3** | 缺顺序 | goal 要求一个**顺序**，而计划根本不陈述顺序（§1.1） | **0 例**。这是唯一一种**今天完全无法表达**的要求，也是最容易被误报成「任务复杂」的一种 ⇒ 它同时证明了：**要开闸，得先给 `Plan` 加顺序** |

### 2.3 不算证据的四条

- **「任务复杂」。** 计划的词汇表是节点 / hop / 顺序；「复杂」不是其中任何一个。一个**翻译不成这三样**的要求，**也不能被一张生成出来的图满足** —— 生成器不会凭空获得表达它的能力。
- **剪枝 / 省节点。** 实测 trend 22 / brief 24，两个模式都几乎是整张图（24 节点）。模板今天的剪枝幅度是 **0–2 个节点** ⇒「动态规划更省」在这里**没有存量可省**。
- **想加第三个模式。** 实测成本：一行 `ModeSpec` + 一行 `ModeTemplate`，**零个节点、零条边**（图是 mode-blind 的，§1.4）—— 只要它不要求图里没有的东西。⇒ 那是**现有机制**，必须先走它、并走不通（E1b），才是证据。
- **测试里出现的新形状。** 只有**真实 run** 算数。测试 fixture 是人写的：它能证明「这个形状**可以**被构造」，不能证明「这个形状**被**需要」。

### 2.4 开闸之前必须先有的三件东西

否则生成出来的是一张**没有契约**的图：

1. **计划要能按 run 陈述，而不只按 mode。** 今天 `export_plan(mode)`；`Goal` 不进 state，另有 11 个 `_run_graph_and_persist` 调用点各自构造 `input_data`（claim `run_graph_and_persist_call_sites`）⇒ **一次 run 的计划今天读不出来**，而「由 Goal 编译」的第一条要求就是它读得出来。
2. **要被一个能说「它错了」的检查器接住。** 今天的 `plan_registry_complaints()` 比对的是**两份声明**（模板 ↔ 图、模式注册表 ↔ 模板）—— 两份**互相独立**的声明，是它能发现东西的**唯一**理由。一份**生成出来的**计划没有第二份声明可比 ⇒ 它需要的判据形态不同：**可达性 + `TAKEOVER_HAZARDS` + 人工闸门**。这条判据今天**不存在**。
3. **人工闸门要能被计划表达。** 进 `publisher` 的**唯一**入边来自 `publish_gate`，而 `publish_gate` 是 `NEEDS_HUMAN`（`TAKEOVER_HAZARDS`；由 `test_the_only_way_into_the_publisher_is_a_gate` 从 `build_graph()` 的边把这条**前提本身**钉住）。一条能绕过它的生成路径不是「更动态」，是**红线**。

### 2.5 闸门长什么样

闸门**不是一个「允许生成」的开关**，**是一个能复现 E1/E2/E3 之一的用例**：

> 一条真实 goal（或它的脱敏转录）＋ 它需要的节点 / hop / 顺序 ＋ 一行「为什么现有模板服务不了它」。

没有这个用例，任何生成器都是在猜 —— 而猜错的失败模式今天**不可测**（§2.4 第 2 件）：一张语法合法、语义荒谬的图，没有任何东西能说它错。

## 3. 本片明确不做（三件）

票面「拒绝」节的三条。逐条给「它为什么是一个**决定**，而不是一个 TODO」：

1. **不做自由的图生成**（LLM 按 Goal 现编一张图）。今天没有一份 goal 能给出 E1b/E2/E3 中的任何一条（§2.2），而生成本身会引入一个**不可测**的失败模式（§2.5）。本片的产出是让这条路**可开闸**，不是先建生成器。
2. **不动 `ExecutionMode`（`single` / `continuous`）的语义。** 它与「计划」**正交**，混在一起会让两件事互相污染。
   ★ 这条轴上长着与 S3a 之前的 `workflow_mode` **一模一样**的病：请求模型是裸 `str`、路由处有 `"single"` 字面量兜底、`ExecutionMode` 枚举在边界不生效、而 `tests/unit/state/test_execution_mode.py` 的头两条断言（`ExecutionMode.SINGLE == "single"`）因 `StrEnum` 而**恒真、零信息量**。
   **票面在这里已经裁过界** ⇒ 登记不改（§4）。将来若要收，照 S3a 的**两读者形状**即可 —— 边界严格 422、state 侧 total + 具名 warning 兜底 —— **不需要新设计**。
3. **不合并 `WorkflowPhase` 的两份定义**（`backend/state/enums.py` 的 `StrEnum` 与 `backend/api/generated/models.py` 的 `Enum`，今天 **13/13 逐字相同**）。它是**重复**而不是**漂移** ⇒ 潜伏的漂移面，不是当前缺陷；而 `api/generated/**` 是生成物，动它属于生成物边界之外的事。**登记为潜伏的漂移面**，不改。

## 4. 登记未修

| # | 登记的事 | 位置 | 本片为什么不修 |
| --- | --- | --- | --- |
| 1 | `should_brief_or_optimize` **没有任何调用者** | `backend/graph/routers.py`；登记在 `backend/graph/wiring.py` 的 `ROUTERS_WITHOUT_AN_EDGE` | 删公开代码是另一个决定。登记时配了**反向断言**：它一旦被接上，`tests/unit/graph/test_wiring_registry.py` 当场红，强制来删这条豁免 |
| 2 | trend 模式 `phase=creating` **静默落到 `trend_scout`** | `backend/state/modes.py` 的 `ModeSpec.route` 兜底 | 给它选一个目的地是另一次**行为**裁定（今天只把这个行为钉成测试） |
| 3 | 11 个 `_run_graph_and_persist` 调用点的 `input_data` 构造**原样** | `blogger.py` 1 · `optimization.py` 2 · `review.py` 2 · `_wf_application.py` 6 · `_wf_runtime.py` 1 | `Goal` 让它们**可以**被收，但那是另一片；而它同时是 §2.4 的前置第 1 件 |
| 4 | `_run_retry` **不注册进 `_background_tasks`**（连带不持租约） | `backend/api/routes/_wf_actions.py`，对比同文件里 publish-retry 那一处 | P2b 的 `docs/execution-plane.md` §7 已登记；票面红线「不顺手做第四件事」 |
| 5 | `workflow_mode` 的 DB 列默认值与备选值 | `backend/db/workflows.py` 的 `TEXT NOT NULL DEFAULT 'trend'` | SQL 无法 import 注册表 —— **唯一结构性的字面量重复**，已在代码里注明（S3a） |
| 6 | `WorkflowPhase` 的两份定义 | 见 §3 第 3 件 | 生成物边界之外 |
| 7 | `execution_mode` 轴 | 见 §3 第 2 件 | 票面已裁界 |

**本片唯一改动的一行生产注释。** `backend/graph/plan.py` 的注释曾指向 `wiring.UNWIRED_ROUTERS`，而真实符号是 `ROUTERS_WITHOUT_AN_EDGE` —— 这是 S2 给它改名时留下的。已改。列出来的理由是它是「腐烂是静默的」的**又一个实例**：**一个指向不存在符号的注释不会报错，读它的人只会以为自己找错了地方。**（这正是 `docs/execution-plane.md` §8 立锚点门禁的同一条理由。）

## 5. 这份文档怎么防止腐烂

本文件的数字不靠人复查。它们被**成对的 HTML 注释标记**括起来（下称**主张块**），`tests/unit/scripts/test_planning_claims.py` 会：

1. 抽出每个主张块里的 `主张 ↔ 值`，断言**每个主张都在测试的复核表里** —— 想加一行主张，必须先写它怎么被重算；
2. 反向断言**每个复核者都在文档里** —— 删掉一行主张不会在测试里留下一个孤儿检查；
3. 用**代码重算**每一个值并比对。

**为什么是「重算事实」，而不是 `docs/execution-plane.md` 那样的 `file:line` 锚点。** 两篇文档要防的腐烂不同：

- 执行平面那篇发布的是**位置**（「这个 `create_task` 在哪一行」）—— 位置会漂，所以它需要锚点；
- 这一篇发布的是**事实**（「图有多少节点」「两个模式的计划差几个」「计划今天有几个读者」）—— 事实不漂，事实会**被改**。按位置钉事实会得到一张「行号挪了就红、而数字错了不红」的网；**按值钉才钉在要害上**。

这也解释了本文件**不发布任何 `file:line`**：它引用的是**符号**（`export_plan`、`ModeSpec`、`ROUTERS_WITHOUT_AN_EDGE`…）。符号也会改名 —— 但改名是**可见的**（import 失败、`ruff`、`mypy`），而数字变了是**静默的**。两者各由合适的手段钉住。

一句话：**这份文档把「什么时候该做动态规划」从一个形容词变成了一个用例**（§2.5）。
