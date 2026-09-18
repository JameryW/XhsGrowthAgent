# Checkpoint 体积基准报告 — 母婴长任务（P1a 前后对比）

对应 prd"体积基准"条目与 info.md 验收："checkpoint 单 superstep 序列化体积显著下降
（基准：母婴长任务前后对比脚本）"。脚本：同目录 `checkpoint-size-bench.py`，确定性可复跑。

## 方法与口径

- **序列化口径**：`JsonPlusSerializer().dumps_typed(values)` 的字节数（langgraph 1.2.10 /
  langgraph-checkpoint 4.1.1，msgpack）。这是 InMemorySaver / AsyncSqliteSaver（dev）/
  AsyncPostgresSaver（prod）写 checkpoint 时对 channel_values 走的同一代码路径
  （builder 从不传 `serde=`，见 `persistence-inventory.md`）。
- **任务形态**：trend 模式母婴长任务 15 个 superstep（建线程 → 趋势侦察 → 选题 → 文案 →
  视觉 → 人审门 → 发布 → 数据 → ripple 分析 → 博主调研 → 笔记抓取 → 草稿 → 版本+优化
  → 爆款收集 → 互动），与真实节点写入顺序一致。合成数据为确定性母婴中文内容
  （正文 ~600 字、5 条博主笔记、3 版本、10 爆款等），体量对标真实 XHS 帖子。
- **两种形态、同源业务数据**：
  - *pre-P1a*：全部业务体 inline；遥测 `performance_log` inline 且每个 superstep 整表
    重序列化（S2 迁移动机）；死键 `messages`/`content_history` 按当时代码实况只带创建时的
    空列表。
  - *post-P1a*：可 ref 字段用生产写接缝函数（`backend.state.artifacts.make_ref`）换成真实
    ArtifactRef；`versions_meta`/`blogger_notes_meta`/`trend_summary` meta 保留；遥测外置
    Event store（S2）；死键已删（S1）。
- LangGraph checkpoint 每 superstep 全量快照、无修剪无 TTL（`persistence-inventory.md`），
  因此**累计字节数（各 superstep 之和）即 checkpoint 存储的真实累积量（写放大）**。

## 结果

| # | node (write) | pre bytes | post bytes | 下降 | note |
|---|---|---:|---:|---:|---|
| 0 | create_thread | 462 | 418 | 10% | inline both shapes |
| 1 | trend_scout | 4047 | 668 | 83% | ref: trend_data |
| 2 | content_strategist | 4648 | 1128 | 76% | inline both shapes |
| 3 | copywriter | 6204 | 1329 | 79% | ref: copy_content |
| 4 | visual_designer | 6947 | 1527 | 78% | ref: visual_plan |
| 5 | review_gate | 7195 | 1641 | 77% | inline both shapes |
| 6 | publisher | 7537 | 1851 | 75% | inline both shapes |
| 7 | analyst | 7906 | 2043 | 74% | ref: analytics |
| 8 | ripple_analyzer | 9839 | 2455 | 75% | ref: ripple_pmf,ripple_prediction |
| 9 | blogger_research | 10883 | 3360 | 69% | inline both shapes |
| 10 | blogger_notes_fetch | 12866 | 3636 | 72% | ref: blogger_notes |
| 11 | draft_generator | 13998 | 3840 | 73% | ref: draft_content |
| 12 | version_writer | 17806 | 4628 | 74% | ref: content_versions,optimization_analysis |
| 13 | viral_collector | 23176 | 4826 | 79% | ref: viral_posts |
| 14 | engagement_runner | 23908 | 5418 | 77% | inline both shapes |

- **最终 superstep：23,908 B → 5,418 B（-77.3%）**
- **累计写放大（整任务 checkpoint 累积）：157,422 B → 38,768 B（-75.4%）**
- **Artifact Store 侧：20,516 B**（canonical JSON 口径 = `ref.size` 语义；每个 body 只在
  写入时落 store 一次，此后不再进入任何 checkpoint 序列化）
- **净持久化字节（checkpoint 累积 + store）：157,422 B → 59,284 B（-62.3%）**

### 最终 superstep 字节构成分解

| 构成 | pre | post |
|---|---:|---:|
| 可 ref 业务 bodies（11 个大字段） | 19,267 B（80.6%） | → refs 共 2,259 B（11 个 ArtifactRef） |
| 遥测 performance_log（14 条目） | 1,917 B（8.0%） | 0（S2 已外置 Event store） |
| meta（versions/blogger_notes/trend） | — | 462 B |
| 控制标量 + 不可 ref 小字段 | 2,699 B（11.3%） | 2,699 B（不变，理论下限） |
| 死键 messages/content_history | **28 B（0.1%）** | 已删 |

## 结论

1. **info.md 验收达成**：单 superstep 序列化体积 -77.3%，整任务写放大 -75.4%，显著下降。
2. 下降的两个真实来源：**大字段 out-of-line 化**（19.3 KB bodies → 2.3 KB refs）与
   **遥测外置**（1.9 KB → 0）。二者都在 superstep 轴上复利：inline 形态下 body 一经写入
   便随每个后续 checkpoint 重复序列化（如 trend_data 在 14 个后续 superstep 里各带一份）；
   refs 形态下 body 只写 store 一次。
3. **死键不是字节来源**：`messages`/`content_history` 在 pre-P1a 从未被写入过（仅线程创建
   时的 `[]`，28 B；业务内容一直在 Memory Store 命名空间）。S1 的价值是消除
   `add_messages` 无界累积的**风险**（schema 卫生），本报告如实测示，不将其计为收益。
4. post 形态的 5.4 KB 中 2.7 KB 是不可再降的底座（控制标量 + 未纳入 ref 化的小字段：
   content_plan/publish_result/human_feedback/blogger_candidates/selected_blogger/
   engagement_actions）；refs 本身 ~205 B/个（含 64 位 hex hash + 时间戳），是 O(1) 常量。
5. 任务越长、优化/互动轮次越多，差距越大：pre 的 body 项与遥测项都随任务时长线性放大且
   逐 superstep 重复支付，post 恒定在底座 + refs 量级。

## 边界与限制

- 数据为确定性合成内容（prd 允许"可脚本化"口径），未跑真实 LLM 节点；大小对标真实
  业务字段结构（substates.py TypedDict 逐字段构造）。
- store 侧 20.5 KB 按 canonical JSON 计（= `ref.size`/`content_hash` 语义）；BaseStore
  实际落盘走同样的 msgpack serde，会略小——不影响结论量级。
- pre 形态按 pre-S2 代码实况计入 inline 遥测；真实长任务中人审门（review_gate）会额外
  产生 pause/resume checkpoint，两边同增，比值不变。
- 人审门之后才写的大字段（笔记/版本/爆款）使两条曲线在中后段拉开——与真实任务一致。
