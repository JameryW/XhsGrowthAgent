# 结果学习（Outcome Learning）

> P3 的交付面。它回答三个问题：**评估者的「好」与平台的「真」各是什么**、**平台的真实数字在什么条件下才允许写进样本**、**攒够了之后在什么条件下才允许动权重** —— 以及**本片刻意不做的事**。
>
> 本文件发布的每个数字都由 `tests/unit/scripts/test_outcome_learning_claims.py` 从代码**重算**。与 `docs/execution-plane.md` 的 `file:line` 锚点不同，这里钉的是**事实**而不是**位置**：键集变了、写入者多了一个、阈值挪了、窗口换了列，测试就红。**本文件因此不发布行号** —— 符号改名是可见的（import 失败、`ruff`、`mypy` 都会报），数字变了才是静默的。与 `docs/planning.md` 同一条纪律。

## 0. 结论：这个闭环在 P3-S3 之前从未启动过

P3 开工时的形状是「**结构完整、测试全绿、从未启动过一次**」：表在、`label_source` 声明了三个取值、`maybe_evolve` 有完整的重拟合与推 epoch 逻辑、`MIN_EVOLVE_SAMPLES` 有值、`PromptEpoch` 有生命周期 —— 而**唯一**能写 `evaluator_samples.engagement` 的 `backfill_engagement` 只被 `analyst` 调用，`analyst` 又是从发布当刻的 `publish_result` 里取指标，而那个 payload 只带身份与状态（`publisher.py` 里查五个指标键，零命中）。

后果可以写成算术，不必用形容词：`engagement` 恒 NULL ⇒ `count_labeled_since` 恒 **0** < `MIN_EVOLVE_SAMPLES` ⇒ `maybe_evolve` 永远走 `below threshold` ⇒ 权重从不重拟合、`PromptEpoch` 从不推进。

**S3 接上了这条边，而接的位置与票面写的不同**：票面说「用 **link 结果**回填」，实测 sync 侧**根本没有 link 结果的消费者**（link 结果是 `analyst` 的读侧投影）；缺口是**缺一个生产者**。生产者的落点是唯一的 —— 三个 sync 入口都落到 `import_bundle`，而 `persist_bundle` 的唯一调用者也是它。

## 1. 两条学习信号

### 1.1 offline quality —— 评估者自己的判断

`evaluator_samples` 的一行由 `evaluator` 节点在**评估时刻**写入：九个维度的打分 + 一个 `bias_check`。「offline quality」= **这些维度的加权和**，权重是 `DEFAULT_DIMENSION_WEIGHTS`。

它是**判断**，不是事实 —— 没有任何平台返回过它。

### 1.2 online reward —— 平台返回的数字

平台事实在 `creator_note_stats`（由 `creator-stats/sync` 从创作者中心导入）。它带五个指标，以及由它们导出的 `engagement_rate`。

> `views` 是分母，其余四个是分子。这不是随手选的，而是**契约与公式共用一份声明**的后果 —— 见 §2.1。

### 1.3 弱标签是两者的桥

「弱标签」= **把平台的真实数字贴在评估者判断过的那一行样本上**。它「弱」在：它不是「这次判断对不对」的标签，只是「这次判断指向的那条笔记，后来在平台上跑出了什么」。

<!-- claim-table:begin -->
| claim_id | value | 复核方式 |
| --- | --- | --- |
| `weak_label_metric_keys` | `collects, comments, likes, shares, views` | `WEAK_LABEL_METRIC_KEYS` 排序后 join |
| `weak_label_key_count` | `5` | `len(WEAK_LABEL_METRIC_KEYS)` |
| `offline_quality_dimensions` | `ai_taste, altruism, audience, commercial_tone, compliance, copywriting, image_quality, reach, visual` | `WEIGHTED_DIMENSIONS` 排序后 join |
| `offline_quality_dimension_count` | `9` | `len(WEIGHTED_DIMENSIONS)` |
| `offline_quality_weights_sum_to_one` | `true` | `abs(sum(DEFAULT_DIMENSION_WEIGHTS.values()) - 1.0) < 1e-9` |
| `online_reward_source_exposes_every_contract_key` | `true` | `set(WEAK_LABEL_METRIC_KEYS) <= NoteStats 的字段名集合` |
| `engagement_label_source` | `engagement` | `ENGAGEMENT_LABEL_SOURCE` |
| `evaluator_label_source_writers` | `evaluator` | AST 扫 `backend/` 里 `label_source=<字面量>` 的**关键字实参**取值集合 |
<!-- claim-table:end -->

★ **最后一行只覆盖 insert 路径。** `label_source` 今天有两种写法：insert 路径传关键字实参（`"evaluator"`），attach 路径把值写进**共享 SQL 子句**（`ENGAGEMENT_LABEL_SOURCE`）。一次性的全文扫描**必然漏掉一半** —— 这是 P3-S3 突变自检抓到过的失效形态，所以两者各有一行主张，而不是合成一行。

## 2. 弱标签的写入条件

### 2.1 两个写入者，一个共享子句

「写什么」只有一份声明：`_ATTACH_WEAK_LABEL_SQL`（`engagement = %s, label_source = '...'`）。两个写入者**只在「选哪些行」上不同**：

| 写入者 | 选行方式 | 谁调用 |
| --- | --- | --- |
| `backfill_engagement` | 按 `thread_id` 取该线程**最近一行**样本 | `analyst` 节点、free 模式的 analytics 路由 |
| `backfill_engagement_for_posts` | 按 `platform_post_id` 取**所有**匹配行，一个事务，返回**行数和** | `creator-stats` 导入（唯一知道真实数字的生产者） |

⇒ 两个写入者的存在本身就是「**能供上键的生产者是谁**」这个问题的答案：只有导入侧知道真实计数。

### 2.2 唯一收口

导入侧不是「在某个路由里顺手写一下」，而是接在 `import_bundle` 的**唯一出口**、`persist_bundle`**之后**。这不是审美选择：三个 sync 入口（payload / creator-center / account-stats）**都**落到 `import_bundle`，而 `persist_bundle` 的调用者只有它 —— 接在这里就是全覆盖，接在别处必漏。

放在 `persist` 之后是为了「**已持久化的笔记不会因为标签写不进去而失败**」，反过来也不让一次失败的持久化留下标签。

### 2.3 连接键的归一发生在生产侧

`note_id → platform_post_id` 的归一（`normalize_platform_post_id`）在**生产侧**做，不在比较侧做：规则只有一个所有者，而「什么算一个显式平台身份」这件事在 S2 已经收敛过一次。

### 2.4 写入条件是「每次 sync 回填一次」

`backfill_engagement_for_posts` 的 `WHERE` **只有** `platform_post_id = %s` —— 它**不**跳过已经带上标签的行。而 `creator_note_stats` 是 upsert（笔记会持续跑量，`synced_at` 会推进），所以同一条笔记的指标每被同步一次，就会把它贴过的样本**再写一遍**。

第一版按「sync 后回填一次」实现；**增量重算 / 只回填未标签行留给证据**（§4 给出为什么这个口径在今天恰好是安全的）。

<!-- claim-table:begin -->
| claim_id | value | 复核方式 |
| --- | --- | --- |
| `attach_writers` | `backfill_engagement, backfill_engagement_for_posts` | AST：源码里出现 `_ATTACH_WEAK_LABEL_SQL` 的函数名集合 |
| `import_bundle_call_sites` | `3` | AST 数 `await import_bundle(...)` 的调用点 |
| `attach_calls_in_import_bundle` | `1` | AST 数 `import_bundle` 函数体内对 `_attach_real_weak_labels` 的调用 |
| `attach_normalizes_on_the_producer_side` | `true` | `_attach_real_weak_labels` 体内出现 `normalize_platform_post_id(note.note_id)` |
| `attach_asks_the_shared_selector` | `true` | 同一函数体内出现 `build_weak_label(note.to_dict())` |
| `evolution_asked_only_when_rows_updated` | `true` | 同一函数体内出现 `if updated`（0 行被更新时**不问**阈值） |
| `attach_selector_does_not_skip_labeled_rows` | `true` | `_sql_omits(...)`：`backfill_engagement_for_posts` 体内**不**出现 `engagement IS NULL` |
<!-- claim-table:end -->

## 3. 开闸条件

`maybe_evolve` 一次只在两个条件同时成立时才真正动权重：

1. **攒够新标签**：`count_labeled_since(epoch.created_at, account_id) >= MIN_EVOLVE_SAMPLES`；
2. **不在演进中**：该账号不在进程内的重入守卫集合里。

满足之后它做两件事，**两件都做完才算 `evolved`**：重拟合权重（`train_weights(apply=True)`），以及**只在 bias 均值越出带时才**推进 `PromptEpoch`。bias 在带内时 epoch 保持不动、只重拟合权重 —— 这是「演进」与「换提示词」两件事被分开的地方。

### 3.1 四种出口

`maybe_evolve` 的返回值永远是一个带 `action` 的报告，取值恰好四种：

- `skip` + `reason="already-evolving"` —— 重入守卫命中；
- `skip` + `reason="below threshold (n<10)"` —— 新标签不够；
- `evolved` —— 重拟合已应用（epoch 是否推进记在 `report["epoch"]`）；
- `error` + `reason=<异常>` —— 任何失败都被吞掉并记为 error。

★ **`skip` 是一个正常的返回，不是一个异常路径。** 「从未启动」的旧状态在日志里长得和 `skip` 一模一样（都是 `below threshold`）—— 这就是为什么 S1 要求判据必须能区分「从未启动」与「跑过但是 0」。

### 3.2 窗口是**样本的创建时间**

`count_labeled_since` 的筛选条件是 `engagement IS NOT NULL AND created_at > <epoch.created_at>`。它数的是**样本**，窗口是**样本被创建**的时刻 —— 不是标签到达的时刻。

<!-- claim-table:begin -->
| claim_id | value | 复核方式 |
| --- | --- | --- |
| `min_evolve_samples` | `10` | `MIN_EVOLVE_SAMPLES` |
| `evolution_outcomes` | `error, evolved, skip` | AST：`maybe_evolve` 体内 `action` 的**两种**形状（字典字面量与下标赋值）全部取值 |
| `maybe_evolve_has_a_reentry_guard` | `true` | 源码出现 `if account_id in _EVOLVING` |
| `count_window_is_the_samples_creation_time` | `true` | `count_labeled_since` 的 SQL 含 `engagement IS NOT NULL AND created_at > %s` |
| `count_ignores_when_the_label_arrived` | `true` | `_sql_omits(...)`：同一 SQL **不**含 `label_source`（窗口与「标签何时到达」无关） |
<!-- claim-table:end -->

## 4. ★ 一处已知的错配（写入条件 × 计数窗口）—— 裁定与理由

§2.4 与 §3.2 合起来产生一个错配：

> **写入条件**是「每次 sync 都回填一次」（不区分新旧行），而**计数窗口**是「样本创建时间」。⇒ 一条**今天被贴上标签的老样本**（epoch 之前被评估、epoch 之后才被回填）**会把标签写进去，却不推高计数**。

### 裁定：**今天不改口径**，并给出理由与取证方式

三个候选处置：**(a)** 把窗口换成「标签到达时间」（需要一个新的时间列）；**(b)** 把写入条件换成「只回填 epoch 之后创建的样本」；**(c)** 登记不改、等证据。

**取 (c)，理由是 (a) 会让口径从「保守」变成「激进」：**

- 今天这个错配的方向是**偏保守** —— 它只会让演进**更晚发生**，不会让它在样本不足时发生。既然 `MIN_EVOLVE_SAMPLES` 的意义就是「攒够信号再动权重」，**少算**比**多算**安全。
- 而 (a) 会引入一个**新**的风险，且这个风险今天已经有物证：`creator_note_stats` 是 upsert，同一行笔记会被**反复**回填（§2.4）。若窗口改成「标签到达时间」，那么**同一条笔记的每一次指标更新都算一次新标签** ⇒ 计数会因**重复回填**而虚高 ⇒ 可能用**尚未成熟**的样本池去重拟合权重。**这正是错的样本池比晚的样本池更贵的地方**：晚只是延迟，错会污染权重。
- (b) 会缩小写入面（epoch 之前的样本永远得不到标签），代价是**丢掉历史行**：那些行曾经是判断，只是判断得早 —— 在没有「重算历史样本」的需求之前，主动丢掉它们没有收益。

⇒ **(a) 需要先有「标签到达」这个事件本身可区分**（而不只是「行上又写了一次」）。**取证方式**：若要重开这条，先证明「同一行被重复回填是可识别的」—— 例如记录回填次数或标签版本，再用它区分「新标签」与「重复写入」。在那之前，窗口保持**样本创建时间**，且这个口径由 `count_ignores_when_the_label_arrived` 显式钉住（它会红，如果有人悄悄改了筛选条件）。

## 5. 明确不做

写下来不是为了免责，是因为**每一条都有一条具体的、可能会导致返工的证据缺口**。

| 不做 | 为什么（证据缺口） |
| --- | --- |
| **不做自由的图 / 策略生成**。只在既有的拟合与演进机制上接通数据，不引入新的优化器。 | 今天没有任何调用点会因为「策略不自由」而失败；缺的是数据到达，不是搜索空间（S3 实测）。 |
| **不把 `creator_agent` 的 `LearningSignal` 并入 engagement 闭环**。 | 两条路径的**驱动源不同**：人工 `UserFeedback` vs 平台弱标签。而且 `LearningSignal` 有 `pending_creator_review` 状态（**要人审**），weights 拟合是**自动**的 ⇒ 合并会改变人工闸门的语义。需要先有「两条路径对同一 run 给出冲突结论」的实例。 |
| **不做 Memory Fabric 的写侧统一**。读侧的统一已经在。 | 今天**没有消费方**同时读两边；避免无消费方的提前抽象。 |
| **不合并 `creator_note_stats` 与 `content_history`**。 | 前者是平台事实、后者是 run 内的记录，合并属于展示层决策，且两份记录的**键不同源**（一个按 note_id，一个按 run）。 |
| **不做真实平台的指标重抓**。`creator-stats/sync` 的抓取契约不动。 | 抓取侧的缺口是另一条链路（CDP 客户端），本片只消费它的产出。 |
| **不动 `free` 路径的无门 backfill**（每次 `get_analytics` 都往 `free:{draft_id}` 写一次）。 | 这是**写入条件**问题（与 §2.4 同族），不是数据通路问题；它今天**能工作**，改了它要动一个不在本片契约内的调用点。 |
| **不做增量重算**：不因「同一条笔记指标变了」而重算历史样本。 | 见 §4 —— 需要先能区分「新标签」与「重复写入」。 |
| **不恢复 `analyst` 的自动边**（`publisher → analyst`）。 | `analyst` 的三件事里，指标那两件因数据源缺键而恒空；接回自动边只会让它们在每个 run 上各做一次**恒空动作**。它的手动入口仍然有效，且与 `creator-stats/sync` 互补（前者产 LLM 洞察、后者导入平台事实）。 |

## 6. 本文件如何被钉住

`tests/unit/scripts/test_outcome_learning_claims.py` 有四条闭环检查，缺一条这张表就会退化成注释：

1. **每个已发布的主张都能重算出发布的值** —— 代码改了而文档没改，就红；
2. **每个已发布的主张都有复核者** —— 想加一行，必须先写清它怎么被重算；
3. **每个复核者都在文档里** —— 删一行会留下**孤儿复核者**，当场红（所以不需要行数下限）；
4. **标记配平** —— 丢一个 `claim-table` 标记会让整块行从上面三条里消失。

**断言「某物不存在」的主张自带不了阳性对照**：把扫描器掏成 `return False`（或让它返回空串）它照样绿。所以这类主张统一走 `_sql_omits` 这个**带方向的名字**—— id、发布的值、扫描方向三者指向一致 —— 并带一条**指向「有该物」的 fixture** 的对照，在那里同一个 helper 必须答 `False`：见该测试文件末尾的对照。

**改这张表的方式**：先在代码里改，再让测试告诉你哪个数字变了，最后才改文档。反过来（先改文档）会让测试红在一个你**以为**已经改好的地方。
