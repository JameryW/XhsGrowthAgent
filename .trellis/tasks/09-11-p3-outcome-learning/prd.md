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
| **S1** | **让现状可见 + 止血** | 把「闭环从未启动」变成**仓内会红的判据**；处置 `analyst.py` 那段恒空的回填（它是今天最大的误导源：读起来像在工作） | 小 |
| **S2** | **link 结果从投影变成事实** | 把 `analytics.py` 里请求内现算的匹配逻辑提到一个**可复用、可测试、可重算**的位置；给 `evaluator_samples` 加 `platform_post_id`（**nullable**，存量行仍可读） | 小 |
| **S3** | **闭合那条边** | `creator-stats/sync` 成功后，用 link 结果把 `creator_note_stats` 的真实指标回填进 `evaluator_samples.engagement`（写 `label_source="engagement"`）；此时 `maybe_evolve` 才第一次可达 | 中 |
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
