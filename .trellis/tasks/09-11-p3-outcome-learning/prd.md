# P3 Outcome Learning 闭环 — 规划

> 本票在规划轮开始前**没有 prd.md**：`.trellis/tasks/09-11-p3-outcome-learning/` 下只有 Trellis 自动生成的 `task.json`（`subtasks: []`、`relatedFiles: []`）与两份**未删的模板示例行** `check.jsonl` / `implement.jsonl`。父任务 `09-11-runtime-upgrade` 对 P3 的全部内容只有一句话（`../09-11-runtime-upgrade/prd.md:37-38`）。
>
> 所以本文档的第一件事不是分解工作，而是**把「是谁缺了什么」量出来** —— 因为父任务那句描述里的四件事实测有**三件已经存在**，而真正缺的东西**不在那句话里**。

## Background

父任务对 P3 的全部描述（逐字）：

> **P3 `09-11-p3-outcome-learning` — Outcome Learning 闭环（依赖 P2a/P2c）**
> 区分 offline quality（LLM Judge）与 online reward（impression/click/save/comment/follow/conversion）；串起 Context+Decision+Content+Execution+Outcome → LearningSignal → CreatorModel Revision → 下一轮决策；统一 Memory 与 Creator Model 两套 personalization stack 为 Memory Fabric。

上游研究给出的定性是两句（`../09-11-runtime-upgrade/research/architecture-review-2026-09-11.md`）：

- §二十五：评估体系要从「Judge Score」升级成 Outcome Learning —— 区分 offline Quality 与 online Outcome，最后学习 `Context + Decision + Content + Execution + Outcome` → Policy Improvement。
- §二十六：**现在最大的重复设计** = Memory System 与 Creator Model System 越来越像**两套 personalization stack**，建议统一成 Memory Fabric。

本规划轮不采信这两句结论，逐条对当前 main（`ea8729a8`，即 P2c 收官后的树）核实。

## 一、实测：闭环的每一段都已经存在

| 段 | 实现位置 | 状态 |
|---|---|---|
| **offline quality**（LLM Judge） | `backend/agents/nodes/evaluator.py`（`_persist_sample` → `insert_sample`） | ✅ 在生产图上，自动跑 |
| **样本表** | `evaluator_samples`（`backend/db/evaluator_config.py:117-130`） | ✅ 列含 `account_id` / `thread_id` / `dimensions` / `overall_score` / `decision` / `label_source` / `engagement` JSONB / `content_snapshot` JSONB |
| **online reward（真实指标）** | `creator_note_stats`（`backend/db/creator_stats.py:70-91`） | ✅ 列含 `views` / `likes` / `comments` / `collects` / `shares` / `engagement_rate`，主键 `(account_id, note_id)`；由 `backend/services/creator_stats/`（**6225 行**，含 1576 行 CDP client）从创作者中心抓 |
| **弱标签拟合** | `fit_weights` / `train_weights` / `_tune_thresholds`（`db/evaluator_config.py:531/666/624`） | ✅ 从 engagement 弱标签拟合维度权重与 pass/reject 阈值 |
| **自动演进（epoch）** | `maybe_evolve` / `PromptEpoch` / `next_severity`（`db/evaluator_config.py:955/744/717`） | ✅ 有 re-entry guard、有 `_EVOLVING` 并发保护、有事件发射 |
| **run → 笔记的身份桥** | `_with_publish_link_metadata`（`agents/publisher.py:344-367`）产出 `workflow_thread_id` + `platform_post_id` + `link_status` | ✅ 两个键都已存在 |
| **linker（把 run 与导入笔记匹配起来）** | `analytics.py:692、781-925`，写 `link_status ∈ {linked, unmatched, ambiguous}` | ✅ **已实现且已测试**（`tests/unit/api/test_analytics_identity.py`） |
| **两条 stack 之间的读缝** | `memory/creator_agent_observations.py:111` 的 `CreativeMemoryObservationSource` 实现 `creator_agent/observations.py:16` 的 `CreatorContentObservationSource` Protocol | ✅ 已存在（§二十六 说「要统一」，读侧**已经统一了**） |
| **decision 侧的学习信号** | `_new_learning_signal(decision, feedback)`（`db/creator_agent.py:366`）→ `creator_agent_learning_signals` 表 → `ModelRevision` | ✅ 有完整生命周期（`pending_creator_review` / `approved` / `dismissed`） |

> **⇒ 父任务描述的四件事里，「区分 offline quality 与 online reward」的**存储**、「串起 … → LearningSignal → CreatorModel Revision」的**对象**、「统一两套 stack」的**读缝**，三件都已存在。本项目纪律里管这叫「声明 ≠ 执行」的反面 —— 这里连声明都已经是实现了。**
>
> **所以本片没有任何一段需要新建。** 下面两节说明**真正断在哪**。

## 二、实测：两条连接是断的

### 断点 1 —— 弱标签的投喂路径事实上不存在

`evaluator_samples.engagement` 的**唯一常规投喂者**是 `agents/analyst.py`：

```python
# backend/agents/analyst.py:271-280
engagement = cast("dict[str, Any]", {
    k: publish_result.get(k, 0)
    for k in ("views", "likes", "collects", "comments", "shares")
    if k in publish_result                      # ← 这五个键一个都不存在
})
if engagement:                                  # ← 恒为 False
    await backfill_engagement(thread_id, engagement)
```

三条互相独立的证据说明这段**从未执行过**：

**证据 1a — `publisher.py` 从不往 `publish_result` 写指标。**
`grep -n '"views"\|"likes"\|"collects"\|"comments"\|"shares"\|"impressions"' backend/agents/publisher.py` → **零命中**。
唯一的真实发布返回（`agents/publisher.py:818`）只回 `publish_result`（经 `_with_publish_link_metadata` 加了 `workflow_thread_id` / `platform_post_id` / `link_status`）。整个文件对 `publish_result` 的 12 处赋值**全部**是 `error` / `error_type` / `recovery` / `result_known` / `note` / `publish_id` —— 全是错误与恢复元数据，**一个指标都没有**（`grep -rn 'publish_result\[' backend/ --include="*.py"`）。

**证据 1b — 自动边被摘掉了，但手动入口是完整的（★ 本节在 S1 开工首日被自我更正，理由见第九节）。**
`backend/graph/builder.py:183-187`：

```python
# ── 发布后直接结束（analyst 改为手动触发）──
builder.add_edge("publisher", END)

# analyst is kept as a node but no longer auto-triggered after publish.
# It can be reached by resuming the workflow with phase=analyzing.
```

`analyst` 是 `backfill_engagement` 的两个调用点之一（另一个是 `routes/free.py:1068` 的 free 模式草稿路径，它同样被 `if engagement:` 门控）。

**自动边确实没有了，但手动通路是完整的**：`state/modes.py:162-199` 两张 phase 表**都**写着 `WorkflowPhase.ANALYZING: "analyst"`；`api/routes/_wf_application.py:1818` 是「**手动触发 analyst 节点（发布后手动运行 Ripple 分析）**」的端点，实现为 `aupdate_state({"phase": ANALYZING, "error": None}, as_node="publisher")` + `_start_resume_task(..., input_data=Command(goto=["analyst"]))`（`:1857-1868`），并带 `assert_thread_owned` 鉴权与 `has_analytics` 幂等门（`:1837-1854`）。

⇒ **断点的性质不是「没人跑」，而是「跑了也拿不到」** —— `publish_result` 里根本没有那五个键（证据 1a），手动触发 analyst 读到的仍是同一份发布当刻的 dict。

**证据 1c — 那个枚举值从未被写过。**
`label_source: str  # "evaluator" | "engagement" | "human_review"`（`db/evaluator_config.py:347`）声明了三个值；实际写入只有两处，都是 `"evaluator"`（`agents/nodes/evaluator.py:149`、`routes/free.py:884`）。
`grep -rn 'label_source="engagement"\|label_source="human_review"' backend/ --include="*.py" | wc -l` → **0**。

### 断点 2 —— 真数据到学习层的那条边不存在

真实的 online reward 是有的，而且质量不低：`creator_note_stats` 由 CDP 抓创作者中心写入，**已经自己算了 `engagement_rate`**（`db/creator_stats.py:85`），公式与 `evaluator_config._engagement_rate()`（`db/evaluator_config.py:504-517`）**逐项相同**（`(likes+collects+comments+shares)/views`）。

但这条真数据**只流向展示层**：

- `grep -n "evaluator_config\|backfill_engagement\|evaluator_samples\|insert_sample" backend/api/routes/analytics.py` → **零命中（exit 1）**。
- linker 的产出 `link_status = "linked"` 只出现在**请求内现算的投影**里（`analytics.py:692、781-925` 构造 `workflow_rows` 与 `imported_note` 两个列表后合并），**不落库**、也没有任何下游学习组件读它。
- `evaluator_samples` **没有 `platform_post_id` 列**（表定义见 `db/evaluator_config.py:117-130`），而 `backfill_engagement(thread_id, engagement)` 吃的又是 `thread_id`。⇒ 即便想回填，**学习侧也拿不到指向笔记的键**。

### 断点的后果（可断言）

`count_labeled_since`（`db/evaluator_config.py:905`）统计的是 `engagement IS NOT NULL` 的样本数。既然 `engagement` 从未被写入 ⇒ 恒为 **0** < `MIN_EVOLVE_SAMPLES` ⇒ `maybe_evolve`（`:976-977`）**永远**走 `below threshold` 分支 ⇒ `train_weights` 从不 refit、`PromptEpoch` 从不 advance。

> **⇒ 一句话：整套 Outcome Learning 闭环结构完整、测试全绿、从未启动过一次。**
>
> 这是「**声明 ≠ 执行**」家族最纯的一例：`db/evaluator_config.py:4` 的模块 docstring 写着 "can be tuned per-account and eventually trained from real engagement feedback"、`agents/analyst.py:263` 写着 "weak label for grader finetuning"、`agents/publisher.py:349-352` 写着 "analytics can only collapse an imported note after an explicit id match" —— **三段声明，零个真实数据点。**

## 三、重新定性

> **P3 缺的不是「Outcome Learning 闭环」，是闭环里两条已经被设计出来的连接：**
>
> 1. **`publish_result` 不带指标，而唯一会读它的回填者（`analyst`）读的就是它** ⇒ 弱标签的投喂**在数据上不可能成功**。这一点与「有没有人触发 analyst」无关：analyst 的手动通路是完整的（`_wf_application.py:1818`），但手动跑它读到的仍是同一份发布当刻的 dict，五个指标键一个都不在。（★ 原稿把这条写成「调用者被摘掉 ⇒ 路径不存在」，S1 开工首日实测更正，见第九节。）
> 2. **真实指标在 `creator_note_stats`，linker 也已经能用显式 id 匹配证明「这次 run 产生了哪条笔记」，但这个证明是纯读投影、不落库、无下游** ⇒ 真数据到学习层的边不存在。
>
> 与 P2c 的形状同源：P2c 的结论是「**缺的不是 Planner，是「计划」这个对象**」；P3 的结论是「**缺的不是闭环，是那两条边**」。

这条定性直接影响切片粒度：**不需要新模块、不需要新 Agent、不需要跨模块重构** —— 两片各自只需要「让一条已有的连线真的通电」。

## 四、切片计划

依赖顺序：S1 → S2 → S3 → S4。每片**独立 PR**、独立通过 `tests/unit` + `tests/integration`。

| 片 | 名称 | 内容 | 规模 |
|---|---|---|---|
| **S1** ✅ | **让现状可见 + 止血** | 把「闭环从未启动」变成**仓内会红的判据**；处置 `analyst.py` 那段恒空的回填（它是今天最大的误导源：读起来像在工作） | 已交付 · `5e7b43b5` |
| **S2** ✅ | **link 结果从投影变成事实** | 身份规则收敛成一处 + 匹配逻辑提成**纯函数**；`evaluator_samples.platform_post_id`（**nullable**）配一个**真写入者** —— 判据与两条被推翻的预设见第十一 / 十二节 | 已交付 · `c27b2f1e` |
| **S3** ✅ | **闭合那条边** | `creator-stats/sync` 成功后把 `creator_note_stats` 的真实指标回填进 `evaluator_samples.engagement`（写 `label_source="engagement"`），此时 `maybe_evolve` 才第一次可达 —— **票面的「用 link 结果」与「`label_source` 是新增语义」两句都被实测推翻**（缺口是缺一个生产者），见第十三节 | 已交付 · `24453cf9` |
| **S4** | **契约与开闸条件** | `docs/outcome-learning.md`：offline quality 与 online reward 的定义、弱标签的**写入条件**、`maybe_evolve` 的**开闸条件**、以及本片明确不做的事 | 小 |

> **S1 的判据必须能区分「从未启动」与「跑过但是 0」** —— 这两件事今天在所有真实数据上都同形（与 P2c-S5 那条「**值为 0 的主张自带不了阳性对照**」同族）。S1 的门禁要**指向有该东西的地方**（例如构造一个带 `engagement` 的样本行、断言 `label_source` 取到 `"engagement"`、断言 `maybe_evolve` 走到 `evolved` 而不是 `below threshold`），否则它会是一条永远绿的网。

## 五、红线

1. **`/status` 保全文响应**（P1a 的承诺，本片不得回退）。
2. **新 run 新 schema、存量 checkpoint 不重写** —— `evaluator_samples` 加列用 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`（沿用 `content_snapshot` 的既有做法，见 `db/evaluator_config.py:135-136`），**必须 nullable**。
3. **等价改写要改形不删** —— 处置 `analyst.py` 那段回填时，宁可留一条显式的「已停用 + 理由」而不是静默删除。
4. **不新增 LLM Agent** —— 本片全部是 deterministic 连线与持久化，不加任何 Agent。
5. **不改 `WorkflowStatus` 枚举**。
6. **不顺手做第四件事**。
7. **`maybe_evolve` 仍然是 fire-and-forget、仍然不阻塞发布路径** —— 它今天的所有「不阻塞」保证（re-entry guard、`_EVOLVING`、吞异常）在 S3 之后仍须成立。

## 六、明确不做

- **不做自由的图/策略生成** —— 本片只在既有的拟合与演进机制上接通数据，不引入新的优化器。
- **不动 `creator_agent` 的 `LearningSignal` 驱动源**（今天由人工 `UserFeedback` 驱动，见 `db/creator_agent.py:366`）。它与 engagement 弱标签是**两条不同的学习路径**，把两者合并需要独立证据（见第七节）。
- **不做 `Memory Fabric` 的写侧统一** —— 读缝已经存在（`memory/creator_agent_observations.py:111`），写侧是否真的需要合并**今天没有消费方**；按「避免无消费方的提前抽象」纪律不做。
- **不合并 `creator_note_stats` 与 `content_history` 这两份内容记录** —— 前者是平台事实、后者是 run 内记录，合并属于展示层决策。
- **不做真实平台的指标重抓**（`creator-stats/sync` 的抓取契约不动）。

## 七、待决（**按证据走，不按计划走**）

1. **父任务 §二十六「统一两套 personalization stack 为 Memory Fabric」是否该做？**
   实测：**读侧已经统一了**（`CreativeMemoryObservationSource` 实现 Protocol、`advisor.py:177` 通过 Protocol 接收）。今天没有证据说明写侧分离造成了具体故障。
   ⇒ **裁定：S1–S4 不做写侧合并。** 若 S3 落地后暴露「同一份偏好被两处独立维护」的具体分歧，再开票。**取证方式**：看 `CreativeMemory` 与 `CreatorModel` 是否对同一事实给出不同答案（今天没有任何调用点会同时读两边）。
2. **decision 侧的学习路径（`LearningSignal` ← `UserFeedback`）是否该并入 engagement 闭环？**
   实测：两条路径的**驱动源不同**（人工反馈 vs 弱标签），`LearningSignal` 有 `pending_creator_review` 状态（**要人审**）而 weights 拟合是**自动**的。合并会改变人工闸门的语义。
   ⇒ **裁定：不并。** 需要先有「两条路径对同一 run 给出冲突结论」的实例。
3. **`evaluator_samples` 是否该由 `creator_note_stats` 反向驱动（即指标变了就重算样本）？**
   实测：`creator_note_stats` 有 `synced_at`、`upsert_note_stats` 是 upsert (`db/creator_stats.py:494`)，所以同一 `note_id` 的指标会**多次更新**（笔记会持续跑量）。
   ⇒ **待 S3 定形后再判**：S3 的第一版按「sync 后回填一次」实现，不做增量重算；重算与否取决于 S3 暴露的重复回填代价。
4. ~~**`analyst` 节点既然发布后不再自动触发，它今天还有生产用途吗？**~~ **★ 已裁定 —— S1 开工首日实测推翻了本条的前提。**
   实测：analyst **可达**。自动边没了（`builder.py:184` `publisher → END`），但入口在 phase 表里（`modes.py:170/188` 的 `ANALYZING: "analyst"`），且有一个完整的手动端点（`_wf_application.py:1818`，鉴权 + `has_analytics` 幂等门 + `Command(goto=["analyst"])`）。所以「不可达」是错的，本条改问一个更准的问题：**它手动跑起来之后，那三件事有几件真能产出？**
   逐条实测：① 写 `content_history` 指标 —— 取自 `publish_result`（发布当刻，无指标）⇒ **产出恒 0**；② 回填弱标签 —— 同上，且 `if engagement:`（`analyst.py:279`）恒假 ⇒ **不发生**；③ 存 insights / `ripple_comparison` —— 由 LLM 输出与 `ripple_prediction` 比对得出，**不依赖 `publish_result` 的指标** ⇒ **这条有效**。
   ⇒ **裁定：不恢复自动触发**（接回 `publisher → analyst` 只会让 ①② 在每个 run 上各做一次恒空动作）；**S1 只登记 ①② 的缺口并让它们可断言**，真指标的回填归 S3。`analyst` 的手动入口与 `creator-stats/sync` 是两件互补的事（前者产 LLM 洞察、后者导入平台事实），**都不删**。

## 八、本规划轮的交付

- 本文档（`prd.md`）—— 首个规划产物。
- `task.json` 回填 `branch` / `subtasks` / `relatedFiles`。
- `check.jsonl` / `implement.jsonl` **保持原样**（仍只有 `_example` 行）—— 实测 P2b / P2c 至今也是如此，**不填 jsonl 是本仓惯例**；账本只回填 `task.json` 的 `branch` / `relatedFiles` / `notes`。（原稿说会填，与惯例不符，一并更正。）
- 不单独开 PR（随 S1 的 PR 一起进，沿用 P2c 的做法）。

## 九、★ 规划轮的自我更正（S1 开工首日实测）

规划轮的结论里有一条**站不住**，开工第一天就被实测撞破。如实记在这里，而不是悄悄改掉 —— 因为「这条为什么错」本身对后续几片有用。

| | 规划轮写的 | 实测 | 错在哪 |
|---|---|---|---|
| **证据 1b** | 「唯一的调用者已经在图上被摘掉了」⇒「主管线里 `backfill_engagement` 没有消费者路径」 | `modes.py:162-199` 两张 phase 表都有 `ANALYZING: "analyst"`；`_wf_application.py:1818` 是完整的手动触发端点（`assert_thread_owned` + `has_analytics` 幂等门 + `Command(goto=["analyst"])`） | **把「自动边被摘」读成了「节点不可达」**。更刺眼的是：`builder.py:187` 那行注释**紧接着就写了** `It can be reached by resuming the workflow with phase=analyzing.` —— 我只读了上半句 |
| **待决 4** | 「`analyst` 已不可达 ⇒ 它那三件事静默不发生」 | 三件事里 ①② 因数据源缺键而恒 0 / 不发生，③ insights **有效** | **把「数据不可能成功」误述成了「代码不可达」** —— 两者对 S1 该做什么的影响完全相反 |

**教训（与「认声明是否真有执行」同族 —— 只是这次的「声明」是我自己写下的注释）**：

- **一条注释里有转折时，转折之后那半句往往才是约束。** 遇到「X 不再自动发生」这类注释，要读到句号之后。
- **「没有自动路径」不等于「没有路径」。** 判可达性要看**入口的集合**：`grep` phase 表/映射表的**全部值**（`ANALYZING` 就藏在那里），再找有没有显式的 `Command(goto=[...])`，而不是只检查某一条边还在不在。
- **诚实呈现**：这条更正让断点的形状从「调度层缺一条边」变成「**数据层缺一个键**」—— 后者更小、更可测，也才真正解释了为什么 `label_source="engagement"` 至今零写入：**不是没人跑，是跑也写不进去。**

## 十、S1 交付（`feat/p3-s1-outcome-label-seam` / `5e7b43b5`）

**一句话**：把「弱标签的投喂在数据上不可能成功」从一句发现变成**仓内会红的判据**，把 `analyst.py` 那段读起来像工作的恒空回填改成说真话，并把五个指标键从散落各处收敛到一处。

### 改了什么

| 文件 | 改动 |
|---|---|
| `backend/db/evaluator_config.py` | 新增唯一契约 `WEAK_LABEL_METRIC_KEYS: Final[tuple[str, ...]]` 与选择器 `build_weak_label(payload)`；`_engagement_rate` 的五个 `.get()` 字面量**保持不动**，由新测试钉住它与常量一致 |
| `backend/agents/analyst.py` | 调用点改读契约（**零行为变化**，仍 `if engagement:`）；那条误导性注释改成陈述实测 |
| `tests/unit/db/test_weak_label_contract.py`（新） | 8 条断言，见下 |

合计 3 files changed, 426 insertions(+), 12 deletions(-)。

**「零行为变化」的口径**：改前是 `{k: publish_result.get(k, 0) for k in (五键字面量) if k in publish_result}`；改后 `build_weak_label(publish_result)` 返回 `{k: payload[k] for k in WEAK_LABEL_METRIC_KEYS if k in payload}`。键集合与取值**逐字等价** —— `if k in payload` 已经保证 `payload[k]` 存在，所以原来的 `get(k, 0)` 默认值分支**永远走不到**；`payload` 为 falsy 时两边都是 `{}`。⇒ 这不是「我判断它等价」，是可逐字对照的同一件事。

### 判据（8 条，每条都带对照）

| # | 断言 | 钉住的东西 |
|---|---|---|
| 1 | `WEAK_LABEL_METRIC_KEYS` == `_engagement_rate` 实际读的键（AST 取源码，不 import 私有名） | 契约与公式不能各自漂移 |
| 2 | `build_weak_label` 全量原样返回、部分只留有的、`None`/`{}` 返回空 | 选择语义本身 |
| 3 | `analyst` 是 `build_weak_label` 在 `backend/` 里的**唯一调用者** | 本片要建的那条缝（按「调用」钉，不按「没有字面量」钉 —— 后者对一个什么都不问的调用者也成立） |
| 4 | **登记的缺口**：`publish_result` 能携带的键 ∩ 契约 = ∅，且契约 − 该集合 = 全部五个 | 「闭环从未启动」的根因 |
| 5 | 生产侧**非空性对照**：`post_id`/`post_url`/`status`/`publish_id` 必须在扫描结果里；真实 `_with_publish_link_metadata({}, {})` 必须返回三个身份键 | 让第 4 条不是「扫描器返回空集」的假绿 |
| 6 | 生产者扫描器阳性对照：合成 fixture 覆盖扫描器声称支持的**每一种**形态 | 形态覆盖是真的（漏一种 = 假缺口） |
| 7 | 公式扫描器阳性对照：同名函数读**另一组键**（`impressions`/`saves`） | 第 1 条不是自证 |
| 8 | `label_source` 的唯一写入者是 `"evaluator"` + 阳性对照 | 缺口的可观测后果（AST 取关键字实参 ⇒ `evaluator_config` 里那句命名 `label_source="engagement"` 的**注释不能满足扫描**） |

第 4/5/6 条的扫描口径：`publish_result` 能携带的键 = 源码里四种形态的并集 —— ① `publish_result = {...}`（含注解赋值）；② 挂在 `"publish_result"` 键下的字典（赋值或内联返回）；③ 传给 `_with_publish_link_metadata(...)` 的字典字面量（该函数按定义收的就是 publish result）；④ `publish_result["..."] = ...` 下标写。今天扫出 **15 个键**（`ab_variant` / `account_id` / `error` / `error_type` / `link_status` / `note` / `platform_post_id` / `post_id` / `post_url` / `publish_id` / `published_at` / `recovery` / `result_known` / `status` / `workflow_thread_id`）——**一个指标键都没有**。

### ★ 诚实呈现：S1 **没有**做的事

1. **第 4 条写的是一句「不可能」，其值今天为 0** ⇒ 它自带不了阳性对照：**把扫描器掏成 `return set()` 它照样绿**。这不是推测 —— 突变自检 M06 就是这条，唯一会红的是第 5 条的非空性对照。所以第 5/6/7/8 条是第 1/4 条的**必要条件**，不是修饰。
2. **第四节那句「例如构造一个带 `engagement` 的样本行、断言 `maybe_evolve` 走到 `evolved`」没有在 S1 落地。** 理由不是嫌麻烦：今天**构造不出这样的行** —— 唯一能写 `evaluator_samples.engagement` 的 `backfill_engagement` 只被那条恒假的 `if` 调用，要构造就得先有指标，而那正是 S3。⇒ **登记为 S3 的入口条件**：S3 的 PR 必须带「有 `engagement` 的样本行 → `count_labeled_since` ≥ `MIN_EVOLVE_SAMPLES` → `maybe_evolve` 返回 `evolved`」这一条，否则 S3 会重演同一种「结构完整、从未启动」。
3. **第四节说的「断言 `label_source` 取到 `"engagement"`」在 S1 只钉了一半**：今天「没有写入者」这半钉死了（第 8 条），「写入者出现时写的确实是 `engagement`」那一半归 S3。
4. **`analyst` 的自动边没有恢复**（第七节待决 4 的裁定）：接回 `publisher → analyst` 只会让 `content_history` 与弱标签回填在每个 run 上各做一次恒空动作。

### 门禁

`ruff check .` **All checks passed!**（540 files）· `ruff format --check .` **540 files already formatted** · `mypy backend --python-version 3.12` **Success: no issues found in 216 source files** · `context_compiler_baseline.py --compare --drift-pct 5` **drift within threshold** · `tool_runtime_gate.py` **P1c-S5 tool runtime: OK** · 全量 `pytest -q` **3586 passed / 3 skipped**（本片 +8）。

### 突变自检

**11 条突变 11/11 杀死**、`restore=OK`（step 0 先用未突变树确认每个 killer 都是绿的）：

- **生产侧 6 条**：publisher 开始写指标键（M01，钉第 4 条）· 契约删掉一个键而公式仍读它（M02）· 选择器改成返回整个 payload（M03）· 选择器掏空（M04）· 公式读一个没声明的键（M05）· `label_source` 出现第二个写入者（M09）。
- **检查器侧 3 条**（第 4/5/8 条自带不了对照的那一半）：生产者扫描器掏空（M06）· 扫描器悄悄丢掉它声称支持的某个形态（M07）· 标签写入者扫描器掏空（M08）。
- **缝 1 条**：`analyst` 回到重复五个字面量（M10）。
- **「根参数」1 条**：扫描器忽略被指向的目录、永远读真实文件（M11）—— 只有阳性对照会红，真实文件仍能重算。

### 回给 S2/S3 的一条线索（S1 顺带实测）

`publish_result` **在 checkpoint 里带着 `platform_post_id`**（`_with_publish_link_metadata` 加的三个身份键之一，且有 `state/hydration.py` 的持久化路径）。所以「真数据到不了学习层」缺的那把键，**在 workflow state 这一侧其实已经存在** —— 断点 2 的「没有可连的键」只成立于 `evaluator_samples` 那一侧（它没有 `platform_post_id` 列，而 `backfill_engagement(thread_id, …)` 吃 `thread_id`）。⇒ S2/S3 有两条候选路径：**(a)** 给 `evaluator_samples` 加 `platform_post_id`；**(b)** 只靠 `thread_id` 从 checkpoint 取 `platform_post_id` 再连 `creator_note_stats`。**S2 侦察时先比较这两条，不要默认 (a)。**

## 十一、S2 侦察（两条预设被推翻）

S2 票面（第 119 行）自带两句预设，开工侦察实测**一句不成立、一句要改口径**。先把它们记在这里，再写 S2 实际的形状。

| # | 票面写的 | 实测 | 判定 |
|---|---|---|---|
| **1** | 「给 `evaluator_samples` 加 `platform_post_id`」是闭合断点 ② 的**必要条件** | 加列**不是**连接的必要条件：`backfill_engagement`（`db/evaluator_config.py:455-478`）的 WHERE **只有** `thread_id`；而 `analyst.py:135` 的 `thread_id = state.get("session_id")`、`publisher._with_publish_link_metadata`（`agents/publisher.py:354-361`）写的 `workflow_thread_id` 是**同一个值**、`analytics._extract_post_data`（`api/routes/analytics.py:585-590`）读的也是 `publish["workflow_thread_id"] or session_id or thread_id` ⇒ **三处是同一个键** | 加列的价值**不是**「让真数据连得上」（那个今天就连得上），而是让**反向查询** `note_id → 样本` 变成一次索引命中。票面把它写成了前者，是对收益的高估 |
| **2** | 「linker 的 `link_status="linked"` 只在请求内投影、从不落库 ⇒ 真数据到不了学习层」 | **free 路径早就落库了**：`api/routes/free.py:1060-1072` 的 `get_analytics` 在真抓到平台指标之后，`is_pool_ready()` 门内**无 `link_status` 条件地**调 `backfill_engagement(f"free:{draft_id}", engagement)` 并 `_schedule_free_evolve` ⇒ 弱标签**确实进过 `evaluator_samples.engagement`** | 缺口不是「没有任何一条路落库」，而是「**workflow 路径**没有一条**确定**的真指标产出来源」（free 靠真抓、workflow 靠读发布当刻的 dict） |

⇒ **S2 的实际形状是三件事，不是两件**：

1. **身份规则单一所有者。** `analytics._normalize_platform_post_id`（`:552-562`）与 `publisher.py:356` 的 `"" if raw_post_id.startswith("mock_") else raw_post_id` 是**同一条规则的两份写法**（后者少了 `workflow:` 前缀那一半）。今天读侧每次比较都 normalize，所以两份写法**碰巧**同键；但「什么算一个显式平台身份」这件事有两个所有者，是下一片（S3 要按 note_id 连库）最先踩的地方。
2. **匹配逻辑从请求内提出来。** `_merge_imported_posts`（`:823-924`）今天**就地修改入参行**（`workflow[key] = ...` / `workflow["link_status"] = "linked"`）。★ 诚实口径：它**今天恰好是可重算的** —— 决定只依赖 `platform_post_id`，被改的那些字段都不是决定的输入，所以同一批行跑两次结论相同。⇒ 提取的价值不是「修一个 bug」，而是把这个性质从**巧合**变成**结构**：纯函数形式下「可重算」是构造出来的，且能被独立断言，而不是靠「今天的字段集合恰好不参与决定」。
3. **★ 加列 + 一个真写入者。** 只加列不写，就是本票存在的那个毛病的第三次重演（「结构完整、从未启动」）。写入时机实测是唯一的：`publisher` 出口同时握着 `session_id` 与 `platform_post_id`，且 `evaluator_gate → publish_gate → publisher`（`graph/wiring.py:280-298`）⇒ **样本先落库、publish 之后才有真 id** —— 顺序正好，无需补任何调度。

### 判据（每条都带对照）

| # | 断言 | 钉住的东西 |
|---|---|---|
| 1 | `normalize_platform_post_id` 的语义表：`mock_*` / `workflow:*` / 空 → `""`；URL → 末段；裸 id 原样 | 规则的**内容**（换家不改语义） |
| 2 | `resolve_platform_links` 的表驱动决定：1↔1 → `linked`；重复声明 → 两侧 `ambiguous`；0 匹配 → imported `unmatched`；无 id 的 imported 落 `unmatched` | 匹配的**四种出口**都在表里 |
| 3 | **纯性**：同一输入调两次结果相等，且入参未被修改 | 「可重算」是结构而非巧合（第 2 件事的正面） |
| 4 | **单一所有者**：`backend/` 内 `normalize_platform_post_id` 只有一个定义；`analytics.py` 里不再有 `startswith("mock_")` 字面量；且 `_merge_imported_posts` 真的走了新函数（按调用钉） | 第 1 件事不是「搬了个副本」 |
| 5 | **列存在且 nullable**：DDL 里 `platform_post_id` 可空、`ensure_tables` 里有那条 `ADD COLUMN IF NOT EXISTS`；存量行（`platform_post_id IS NULL`）仍能被读出来 | 红线 2（新 run 新 schema、存量可读） |
| 6 | **写入者是活的**：`record_publish_identity` 的唯一调用点在 publisher 出口；且**非空平台 id 才写**、无样本时返回 0 而不抛 | 第 3 件事：列不是摆设 |
| 7 | 阳性对照：把「唯一调用点」扫描器指向一个不含调用者的目录 | 第 6 条不是「扫描器返回空」 |
| 8 | 阳性对照：normalize 扫描器指向一个自带重复定义的 fixture | 第 4 条不是自证 |

### 明确不做

- **不改 publisher 写侧那条规则**（`publisher.py:356` 保留原字面量）—— 改它会动发布契约（`tests/unit/agents/test_publish_contract_equivalence.py` 钉着 publish result 的键），而读侧单一 normalize 已经保证**两侧比较时同键**。这个分歧被登记，不被顺手抹平。
- **不动 `get_analytics` 的无门 backfill**（今天每次调用都往 `free:{draft_id}` 写一次）—— 「写几次」是**写入条件**问题，属 S3/S4；S2 只把它登记下来。
- 不做真实平台重抓（红线：`creator-stats/sync` 的抓取契约不动）。

## 十二、S2 交付（`feat/p3-s2-link-from-projection-to-fact` / `c27b2f1e`）

**一句话**：把「什么算一个显式平台身份」与「哪条笔记属于哪次 run」从两个模块各自现算，收敛成一个纯函数；并让 publish 那一刻解析出的平台身份落到 `evaluator_samples.platform_post_id` —— link 从**请求内的投影**变成**库里的一个事实**。

### 改了什么

| 文件 | 改动 |
|---|---|
| `backend/services/publish_identity.py`（新） | `normalize_platform_post_id`（逐字从 `analytics` 移入）+ `LinkGroup` / `LinkResolution` / `resolve_platform_links`：纯函数，无 I/O、不修改入参行 |
| `backend/api/routes/analytics.py` | 删掉私有 normalizer（3 处调用改公共名）；`_merge_imported_posts` 由「请求内现算」改为「调用 resolver → 应用它给的决定」（−51/+28） |
| `backend/db/evaluator_config.py` | `platform_post_id TEXT` **双路径**落地（`CREATE TABLE` 列名 + `ADD COLUMN IF NOT EXISTS` 升级），**nullable**；新增唯一写入者 `record_publish_identity` |
| `backend/agents/nodes/publisher.py` | 在节点的唯一出口之后 best-effort 落库（`is_pool_ready()` 门 + 规范化门 + `try/except`），**+37 行纯新增**，未改任何既有分支 |
| `backend/db/__init__.py` | 新函数登记进惰性导出表 |
| `tests/unit/services/test_publish_identity.py`（新） | 26 条判据 |

### 判据（26 条，每组都带对照）

| 组 | 条数 | 断言 | 钉住的东西 |
|---|---|---|---|
| 规则语义 | 9 | 参数化表：`None` / 空 / 空白 / `mock_*` / `workflow:*` → `""`；裸 id 与两种 URL 形态 → 裸 id | 换家不改语义 |
| 匹配决定 | 6 | 1↔1 → `linked`；2 workflow 声明 → 两侧 `ambiguous`；1×2 → `ambiguous`；0×1 → `unmatched`；**0×2 → `ambiguous`**；合成 id 不算声明 | 四种出口全在表里，且歧义由**任一侧**多声明决定 |
| 顺序 | 2 | group 顺序 = imported 侧首次出现顺序；无 id 的行排在 append 末尾 | 与旧实现的输出顺序逐位一致 |
| 可重算 | 1 | 同一输入调两次结果相等、入参逐字未变、**且不是空转**（同时断言它真的判出了两条 link） | 「可重算」是结构而非巧合 |
| 单一所有者 | 2 | `normalize_platform_post_id` 在 `backend/` 只有**一处定义**（两种拼写都扫）；analytics 里不再有 `startswith("mock_")`，调用者集合恰是 {analytics, publisher 节点, owner 自己} | 第 1 件事不是搬了个副本 |
| 列 | 1 | `platform_post_id TEXT` 出现两次（CREATE + ALTER）、无 `NOT NULL`、`ensure_tables` **真的 execute** 了那条 ALTER、`insert_sample` 的 SQL 不含该列 | 红线 2 + 存量行可读 + 旧调用者不破 |
| 写入者 | 3 | UPDATE 是 latest-by-thread 且参数顺序正确；空 id 不碰 DB；**唯一调用点是 publisher 节点** | 列不是摆设 |
| 写入者行为 | 2 | 规范化后才落库（`mock_*` 与 URL 两种形态都验）、DB 抛错不冒泡到 publish | 「活的」不只靠扫描 |
| 扫描器对照 | 3 | 单一所有者扫描器指向含两种写法的 fixture → 2；调用扫描器指向空目录 → ∅；`startswith("mock_")` 的正面对照落在 publisher（写侧故意保留） | 每条「值为零」的主张自带阳性对照 |

### ★ 诚实呈现

1. **我自己写下的 `LinkGroup.status` 第一版是错的。** 「0 个 workflow 声明 + 2 个 imported 声明」在旧代码里走的是 `ambiguous` 分支（`len(candidates) > 1` 那一半），我的第一版会返回 `unmatched` —— 差别是「会不会被静默合并」。写完模块当轮就发现并改正（把条件显式化成 `one_each`），并立刻把它变成一条判据与一条突变（匹配决定组的第 5 行、M03）。这不是「重构顺带修的 bug」，是重构**引入**的 bug，所以它单独占一行。
2. **加列的收益被下调，如实写进第十一节。** 票面把它写成闭合断点的必要条件；实测不是（`backfill_engagement` 的 WHERE 只有 `thread_id`，而 `analyst` 的 `thread_id`、`publisher` 的 `workflow_thread_id`、`_extract_post_data` 读的是同一个键）。S2 给它保留的真实理由是让 S3 的**反向查询**（`note_id → 样本`）成为一次索引命中。
3. **没有做「加列 + 留一句注释说以后会有人写」那个版本** —— 那正是本票存在的毛病（结构完整、从未启动）。写入者落在 publisher 的唯一出口：它是今天唯一同时握着 `thread_id` 与 `platform_post_id` 的地方，且 `evaluator_gate → publish_gate → publisher`（`graph/wiring.py:280-298`）保证**样本先存在**。
4. **不动 publisher 写侧那条 `startswith("mock_")`**（第十一节已登记）：读侧统一 normalize 已保证两侧比较同键，改它要动发布契约（`tests/unit/agents/test_publish_contract_equivalence.py` 钉着 publish result 的键）。这个分歧被**登记**，不被顺手抹平。
5. **不动 `get_analytics` 的无门 backfill**（每次调用都往 `free:{draft_id}` 写一次）—— 它是「写几次」的**写入条件**问题，归 S3/S4。

### 门禁

`ruff check .` **All checks passed!**（542 files）· `ruff format --check .` **542 files already formatted** · `mypy backend --python-version 3.12` **Success: no issues found in 217 source files** · `context_compiler_baseline.py --compare --drift-pct 5` **drift within threshold** · `tool_runtime_gate.py` **P1c-S5 tool runtime: OK** · 全量 `pytest -q` **3612 passed / 3 skipped**（本片 +26）。

### 突变自检

**14 条突变 14/14 杀死**、`step 0 OK`、`restore=OK`（survived / badid / error / timeout 全 0）：

- **规则 2 条**：`workflow:` 前缀不再被拒（M01）· URL 不再归一成裸 id（M04）。
- **决定 3 条**：重复声明被折叠成 link（M02）· **0 workflow × 2 imported 被判成 unmatched（M03，就是上面我写错的那条）** · 解析器就地修改入参（M05）。
- **写入者 6 条**：publisher 出口的调用被摘掉（M06）· 列变 `NOT NULL`（M07）· ALTER 定义了却不再 execute（M08）· 写入者恒返回 0（M09）· 空 id 直达数据库（M10）· 存原始 id 而不规范化（M14）。
- **读侧 1 条**：`analytics` 不再把自己的行交给 resolver（M11）。
- **「根参数」2 条**：扫描器忽略被指向的目录 —— `_defined_names`（M12）与 `_call_sites`（M13）各一条，两条都只有阳性对照会红。

### 回给 S3 的一条线索

`evaluator_samples.platform_post_id` 现在会在**每次真实发布**之后被写上（dry run 与失败发布规范化后为空 ⇒ 不写；该线程没有样本则 rowcount=0）。⇒ S3 的 sync 回填不必再去 checkpoint 里重放「这个 thread 发了哪条笔记」，一条 `WHERE platform_post_id = ANY(...)` 就够。**但**要注意 `upsert_note_stats` 是 upsert、同一条笔记的指标会持续更新（第七节待决 3）：S3 的第一版按「sync 后回填一次」实现即可，增量重算留给证据。
## 十三、S3 侦察（票面口径被推翻）

票面第 120 行把 S3 写成「用 **link 结果**把真指标回填进 `evaluator_samples.engagement`（写 `label_source="engagement"`）」，
S1 又把「带 `engagement` 的样本行 → `count_labeled_since` ≥ `MIN_EVOLVE_SAMPLES` → `maybe_evolve` 返回 `evolved`」
登记为 S3 的入口条件。开工侦察实测：**缺口既不是「先有鸡还是先有蛋」，也不是「缺一把键」，是缺一个生产者。**

| # | 票面 / 登记里写的 | 实测 | 判定 |
|---|---|---|---|
| **1** | 「用 **link 结果**回填」 | link 结果（`resolve_platform_links`）是 `analyst` 的**读侧**投影：它的产出是「哪两行配对」，而 `creator-stats/sync` **从不构造 `publish_result`、也从不消费 link 结果**。sync 真正需要的是两件事 —— 一个**生产者**（谁把指标写下去）与一个**连接键**（凭什么找到那一行） | 「用 link 结果」是借来的措辞：本片没有 linker 的消费者 |
| **2** | S1 登记「今天**构造不出**这样的行」 | **登记是写实的**。`publish_result` 由**发布时刻**构造（发布步骤之后才发布 ⇒ 无指标键），且 `RECOVERY` 里没有任何节点回头重建 state | S1 的判定成立，本片不改写它 |
| **3** | 隐含前提「sync 侧没有 id ↔ 指标配对」 | **sync 侧今天就有完整配对，只是把指标丢在地上**：`api/routes/analytics.py:771-809`（`_imported_notes_as_posts`）已经从 `NoteStats` 造出 `{id, platform_post_id, likes, comments, collects, shares, views, ...}`，并且**已经在 `:785` 走 `normalize_platform_post_id` 归一** | 数据齐、键齐、规则齐 ⇒ 只差一次 UPDATE |
| **4** | 「写 `label_source="engagement"`」被写成本片的主要产出 | `label_source` 在写入前**全仓零读者**：训练池 `fetch_labeled_samples`（`evaluator_config.py:726`）按 `engagement IS NOT NULL` 筛（`:806` / `:811`），`count_labeled_since`（`:986`）同理（`:1068` / `:1074`） | 只写 `engagement` 就能让本片可观测（计数 + 演进）；`label_source="engagement"` 是**票面替下游设想的键** |
| **5** | 「`label_source` 出现第二个值」读起来像新增语义 | `label_source='evaluator'` **在数据库里本来就是假的**：`insert_sample`（`:367`）在**评估时刻**写下它，`engagement` 由**另一次 UPDATE** 补上 | 写入者改写它是**修正**，不是新增语义 |

⇒ **S3 的实际形状是两个落点，不是一个。** 两者都由实测决定，不是选择：

1. **生产者的落点是唯一的**：sync 的三个入口（`pipeline.py` 的 `sync_from_payload:571` / `sync_from_creator_center:757` / `sync_account_stats:839`）**都落到 `import_bundle`**，而 `persist_bundle`（`:448`）的**唯一调用者**也是它 ⇒ 在 `import_bundle` 里、`persist` 之后接一次，就是全覆盖；接在别的任何地方都会漏掉另外两个入口。
2. **连接键不必二选一**：S2 已经把 `platform_post_id` 写进 sample（`record_publish_identity`，publisher 节点唯一出口），所以本片在一次 join 里可以**同时**用精确的 `platform_post_id` 与兼容的 `thread_id`。选前者是因为它是同一件事的更强形态：`session_id == thread_id`（`state/goal.py:143-144`）说明三处本来就是**同一个键**，而 post id 是**发布事实本身**；且 `account_id` 两侧同源（`resolve_required_account_id`，`_wf_application.py:157`），连接不会因账户键错过。

### ★ 顺带实测：free 路径与本片不是同一件事

`api/routes/free.py:1060-1072` 的无门 backfill **今天就在写 `engagement`**（每次 `get_analytics` 都往 `free:{draft_id}` 写一次）。它不是本片要修的缺口，而是「**写几次**」的**写入条件**问题（S2 第十一节已登记）。但它决定了一件事：**「`engagement` 有写入者」在今天已经局部成立** ⇒ 本片的判据必须把「谁写的」与「写了之后学习层能不能看见」**分开**断言，否则会拿 free 的局部成立当成 workflow 路径也成立。

## 十四、S3 交付（`feat/p3-s3-sync-weak-label-backfill` / `24453cf9`）

**一句话**：把「弱标签闭环从未启动过一次」从一句登记变成**一次真的通电** —— 在 `creator-stats/sync` 的唯一收口上，让导入的真实指标落到判断过那条笔记的样本上，并让 `maybe_evolve` **第一次**返回 `evolved`。

### 改了什么

| 文件 | 改动 |
|---|---|
| `backend/db/evaluator_config.py` | 新增 `ENGAGEMENT_LABEL_SOURCE: Final[str] = "engagement"` 与**共享子句** `_ATTACH_WEAK_LABEL_SQL`（两个写入者只在「选哪些行」上不同，不在「写什么」上不同）；`backfill_engagement` 改用它（并因此**修正** provenance）；新增 `backfill_engagement_for_posts(engagement_by_post_id)` —— 按 `platform_post_id` 选行、一个事务、返回**行数和**而非 post 数 |
| `backend/services/creator_stats/pipeline.py` | `import_bundle` 的唯一出口、`persist_bundle` 之后接线 `_attach_real_weak_labels(bundle)`；生产侧归一 `note_id`（`normalize_platform_post_id` 仍是规则唯一所有者）、payload 走 `build_weak_label`（与 `analyst` 共用一个声明）；标签落地即 fire-and-forget 地调一次 `maybe_evolve` |
| `backend/db/__init__.py` | 惰性导出表登记 `backfill_engagement_for_posts` |
| `tests/unit/services/creator_stats/test_weak_label_backfill.py`（新） | 8 条，含票面指定的入口条件 |
| `tests/unit/db/test_evaluator_config.py` | +2 新、1 条加强（原来的 `label_source` 断言补上） |
| `tests/unit/db/test_weak_label_contract.py` | 改形 3 处（**不删**）：第 4 条**没有**变红（sync 不构造 publish result，见下） |
| `tests/unit/services/test_publish_identity.py` | 改形 1 处：`normalize_platform_post_id` 多了第三个读者 |

### 判据（27 条，每组都带对照）

| 组 | 条 | 断言 | 钉住的东西 |
|---|---|---|---|
| 端到端 | 8 | 见下 | 票面的入口条件 + 反向对照 |
| db 层 | 3 | 每条 post 一条语句且 `WHERE platform_post_id = %s`、共享子句含 label、参数是 `(payload, post_id)`；两次 rowcount=2 **相加为 4**；空 key / 空 payload 一条语句都不发 | 「按行数而不是按 post 数」与「一个事务」是真的 |
| 契约 | 4 | 关键字扫描仍恰好 `{"evaluator"}`（**并说明它看不见 SQL 里的写者**）、`ENGAGEMENT_LABEL_SOURCE == "engagement"`、子句必须carry 它；两个写入者的源码都必须出现 `_ATTACH_WEAK_LABEL_SQL`；`build_weak_label` 的调用者**精确**集合 = {`analyst`, `creator_stats/pipeline`} | 唯一契约没有第二个声明 |
| 身份 | 12 | 既有 S2 判据改形（期望集合扩到四项） | 第三位消费者被**报告**而非被放宽 |

★ **第 4 条（登记的缺口）没有变红，而且这是对的**：它断言的是「`publish_result` 能携带的键 ∩ 契约 = ∅」。sync 从不构造 publish result —— 它把指标直接写进匹配到的样本 —— 所以那句话**今天仍然为真**。S1 预言的「S3 让检查 4 变红」没有发生，因为 S3 从**另一端**闭合；它由本片的第 8 条替换（「`label_source` 的第三个声明值终于有写入者」）。

端到端 8 条的分工：

| # | 断言 | 对照 |
|---|---|---|
| 1 | 导入把真实指标贴到判断过该笔记的样本上，键集合 `== set(WEAK_LABEL_METRIC_KEYS)`、`label_source == "engagement"`、演进被问了一次 | 键集合绑契约而非字面量 |
| 2 | **对照**：没有任何样本判断过这条笔记 ⇒ 什么都不写、也什么都不问 | 第 1 条不是「反正都会写」 |
| 3 | URL 形态的 note_id 归一后仍命中（断言实际传下去的键 `== "note-1"`） | 归一发生在生产侧，不是比较侧 |
| 4 | **对照**：pool 不可用 ⇒ 一条语句都不发 | 第 3 条的命中不是「碰巧没库也过」 |
| 5 | attach 抛错 ⇒ 导入仍然 `account_synced is True`，且日志有 `weak-label attach skipped` | 标签是 best-effort，笔记已经持久化了 |
| 6 | ★ **入口条件**：10 行样本 → 导入前计数 `== 0` → 导入后 `== MIN_EVOLVE_SAMPLES` → `maybe_evolve` 返回 `evolved`、`train_weights` 被 `apply=True` 调过、epoch **不**被重建（bias 在带内） | 「两端都是真的」见下 |
| 7 | **对照**：同样写入路径、少一行 ⇒ `skip` / `below threshold` | 第 6 条不是「反正都会 evolved」 |
| 8 | **登记而非修复**：样本 `created_at` 早于 epoch ⇒ 标签**确实落库**但 `count_labeled_since == 0` | 窗口是**样本创建时间**（S4 的写入条件问题） |

**第 6 条的口径**（S1 明确要求这条不能 mock 计数器）：行由**被测的生产路径**写下去、由**生产的** `count_labeled_since` 数出来，假 `_Store` 真的变更行、真的按 `engagement IS NOT NULL` 计数。只有 refit 本身（`train_weights` / `avg_bias_score` / epoch）被 stub —— 它是另一件事且有它自己的测试。⇒ 它不是「带 mock 的『已应用』」。

### ★ 诚实呈现

1. **票面 S3 的两句话都被实测推翻，如实写进第十三节。** （a）「用 link 结果回填」：sync 侧没有 linker 的消费者，本片建的是一个**生产者**；（b）「写 `label_source="engagement"`」被当成主要产出：它在写入前**全仓零读者**，所以本片**可观测**的变化只有计数与演进 —— `label_source` 是「票面替下游设想的键」，不是本片能让任何行为改变的东西。
2. **★ 突变自检发现并修掉了一处真漏洞（本片最重要的一条）。** 第一版端到端 fixture 的 `_Store._attach` 从 **import** 取 `ENGAGEMENT_LABEL_SOURCE` 写进假行 —— 等于**替生产语句回答**。后果：共享子句把 label 半边整个删掉（M1）时，那条「真写入 → 真计数 → `evolved`」的链**照样全绿**，M1 只有 **3 红**、且全在 db 层与关键字断言上；标签值写错（M2）同样只有 3 红。改成**从 SQL 里解析** label（与同一个 fixture 的 `_count` 早就用 `assert "engagement IS NOT NULL" in sql` 读谓词是同一个标准）之后：**M1 → 8 红（其中 5 条来自端到端文件）、M2 → 4 红（含 1 条端到端）**。⇒ 这条漏洞的形态值得记下来：**fixture 替被测语句回答**，是「结构完整、从未启动」的第三种变体（前两种是「有列没写入者」「有分支没生产者」）。
3. **「`label_source` 现在有两种写法」这个问题没有被"补一条一致性判据"解决。** 关键字实参（insert 路径）与 SQL 子句（attach 路径）确实无法用同一次扫描覆盖；补一条「两种写法必须一致」的判据仍然只是**文本比对**。真正的修法是**让消费端不再替它回答**（第 2 条），这在结构上把「真 SQL 写什么」与「判据看到什么」变成同一个来源。所以本片**没有**新增一致性判据，而是把 `_attach` 提升到与 `_count` 同样的标准 —— 依据是**内部一致性**，不是新原则。
4. **第 7 条的「一个事务」是**唯一**由 db 层而不是端到端钉住的：假 `_Conn.transaction()` 是无操作（它不模拟回滚），所以「一个事务」只在 db 层被断言。这是**登记**下来的口径，不是漏洞 —— 假 pool 本来就不该模拟事务语义。
5. **一条声明没有判据，如实登记**：`_attach_real_weak_labels` 的注释说「放在 persist 之后，失败的 persist 不会留下标签」。这句话在「persist 抛错」的语义下**不可证** —— 无论 attach 在 persist 之前还是之后，persist 抛错都会让 attach 不执行。⇒ 它是**意图声明**，不是被测试保证的性质。
6. **不动 free 路径的无门 backfill**（第十三节）：那是写入条件问题，归 S4。本片只保证它**不会**因为这次改动而改变行为（`backfill_engagement` 的 WHERE 与参数逐字未变，只多了 SET 子句里的 label）。
7. **`upsert_note_stats` 是 upsert ⇒ 本片按「sync 后回填一次」实现**（S2 回给 S3 的线索已预告）：同一条笔记的指标持续更新时，每次 import 都会把当前值重写一次。增量重算 / 只回填未标签行留给证据。

### 门禁

`ruff check .` **All checks passed!**（543 files）· `ruff format --check .` **543 files already formatted** · `mypy backend --python-version 3.12` **Success: no issues found in 217 source files** · `context_compiler_baseline.py --compare --drift-pct 5` **drift within threshold** · `tool_runtime_gate.py` **P1c-S5 tool runtime: OK** · 全量 `pytest -q` **3623 passed / 3 skipped**（本片 +11）。

### 突变自检

**11 条突变 11/11 杀死**、`restore=OK`、`baseline=green`：

- **共享子句 / provenance 2 条**：子句丢掉 label 半边（**M1 → 8 红**）· 标签值写回 `'evaluator'`（**M2 → 4 红**）。这两条是第 2 条诚实呈现的证据。
- **选择与计数 3 条**：`WHERE` 退回 `thread_id`（M3 → 6 红）· rowcount 按 post 数而不是按行数（M4 → 2 红）· 不再共享一个事务（M5 → 1 红，唯一只由 db 层钉住的一条）。
- **声明单一 2 条**：第二个写入者自拼子句（M6 → `test_both_attach_paths_share_one_clause` 红）· 生产侧自拼五个键而不再问契约（M10 → 调用者精确集合红）。
- **询问阈值 2 条**：`if updated:` 恒真（M7 → 「无人判断」的对照红）· 恒假（M8 → 第 1 条与入口条件红）。
- **生产侧归一 1 条**：直接用 `note.note_id`（M9 → 端到端 URL 那条 + S2 契约红）。
- **接线 1 条**：把 `import_bundle` 里那次调用摘掉（M11 → 6 红）。

★ 两条突变被**额外断言了「必须被谁注意到」**（`expect_from`）：M1 与 M2 都必须有红来自**端到端文件**，否则脚本自己判 **TOO-WEAK** 并返回非零。这把第 2 条诚实呈现的修法钉在了**工具**上，而不只是钉在这一轮的一次运行上。

### 回给 S4 的一条线索

弱标签的**写入条件**现在是「每次 sync 都回填一次」，而 `count_labeled_since` 的窗口是**样本创建时间**（`:986` 的 `created_at > epoch`）—— 于是存在一个 S4 必须裁定的错配：**一条今天被标签的老样本，会把计数推高（只要它创建得够晚）或推不动（创建得早，第 8 条）**，而 refit 的样本量与「哪一批标签算数」因此取决于**样本何时被判断**而不是**标签何时到达**。§七待决 3 与本节第 8 条是同一个问题的两面。
