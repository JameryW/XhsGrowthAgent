# P1a 勘察 A：XHSGrowthState 字段消费者地图与重量分析

（2026-09-13 Explore 子代理产出，基于合并 P0 后的 main。Writers 在 backend/agents/*.py；nodes 为薄封装并同步发 realtime 事件；前端主要经 stores/workflow.ts 的 /status 载荷 + 域 store 消费。）

## /status 与 /history 放大现状

- `WorkflowStatusResponse`（workflow.py:528-588）每次轮询回显 16 个重字段的**原始正文**：trend_data, content_plan, copy_content, draft_content, optimization_analysis, content_versions, visual_plan, publish_result, analytics, ripple_prediction/pmf/comparison, brief_content, shooting_plan, blogger_candidates, blogger_notes（构造于 workflow.py:980-1004）。
- `/history` 经 `_snapshot_to_checkpoint`（workflow.py:1131-1154）对每个 checkpoint 回显同一集合。
- `performance_log` → 变换为 `agent_timeline`（workflow.py:950-965），非原文。
- **不回显**：messages、content_history、viral_posts、user_viral_links、evaluation_result（后两者走 realtime 事件 + /evaluation；Review.vue:649,712）。

## 字段表（Diff 1=易迁移 → 5=必须留守/扇出广）

| Field | Writers | Router 读 | 其他 agent 读 | /status 回显 | FE 读者 | 重量来源 | Diff |
|---|---|---|---|---|---|---|---|
| trend_data | trend_scout | `should_plan`(routers.py:77) | content_strategist, blogger_scout | 是 | workflow.ts:297, Dashboard/Timeline | topics+竞品帖列表 | **3** |
| content_plan | content_strategist | — | copywriter, viral_matcher, shooting_planner, choice_gate | 是 | review.ts:64 等 | LLM 文本，小 | **3**(多消费者) |
| copy_content | copywriter；revise_content:33 清；choice_gate:45 覆盖 | — | review_gate, evaluator, publisher | 是 | review.ts:65 | 全文 body_text | **2** |
| visual_plan | visual_designer；revise:34；choice_gate:111 | — | review_gate, evaluator, publisher | 是 | Dashboard:255, Review:833 | prompts+image_paths | **2** |
| viral_posts (append) | viral_matcher:113 | — | content_analyzer:29, shooting_planner:32 | 否(realtime) | optimization.ts:178 | N 帖全文 body+image_urls | **1** |
| user_viral_links | optimization.py:61(API) | — | viral_matcher:41 | 否 | — | list[str] 小 | **1** |
| content_versions (replace) | version_generator, copywriter；choice_gate 清 | **3 个路由读其长度**(routers.py:291,324,423) | choice_gate | 是 | Dashboard:253 等 | A/B/C×全文 | **4** |
| blogger_candidates (replace) | blogger_scout | blogger_gate_router | blogger_gate | 是 | BloggerSelectionPanel | 小 profile | **2** |
| blogger_notes (replace) | blogger_gate:99 | routers.py:371 读真值 | copywriter | 是 | Dashboard/OptimizationPanel | 每帖 body | **3** |
| brief_content (merge) | brief_analyzer, brief_gate:59, API | — | **5 个 agent** | 是 | Dashboard:645-694 | **raw_text=整份 brief/PDF 提取全文** | **4** |
| shooting_plan (merge) | shooting_planner | — | — | 是 | ContentCards:56, 导出路由 | 模板文案 | **1** |
| draft_content | draft_gate, choice_gate:53/90, API | — | content_analyzer, version_generator | 是 | optimization.ts:47 | 用户全文 | **2** |
| optimization_analysis | content_analyzer | — | version_generator | 是 | OptimizationPanel | gaps/suggestions | **1** |
| analytics | analyst:115 | — | orchestrator:21 | 是 | workflow.ts:194 | 小快照 | **2** |
| **messages** | **无人写**（仅 init []：workflow.py:697, cli:87） | 从不 | 从不 | 否 | 否 | — | **1(死)** |
| **content_history(state)** | **无人写**（仅 init []：workflow.py:706, cli:96）；真身在 Store content_history_ns | 从不 | 从不 | 否 | 否 | — | **1(死)** |
| performance_log (append) | base.py:375/400, blogger_gate:103 | 从不 | _base.py:179 聚合 | →agent_timeline | timeline | **每 superstep 单调增长** | **1** |
| ripple_prediction/pmf | strategist, ripple_finalize:80, late_recheck:89 | ripple gates | 3 个 agent 进 prompt | 是 | RipplePanel | 嵌套向量 | **3** |
| ripple_comparison | analyst | — | — | 是 | RipplePanel | 小 | **1** |
| evaluation_result | evaluator node:63 | **evaluator_outcome/requires_human**(routers.py:182,224) | revise_content:24 | 否 | Review.vue | 9 维+rationales | **5(留守)** |
| publish_result | publisher 多处 | — | analyst:78 | 是 | Dashboard:269 等 | 小 | **3** |

## 结论

- **一跳即焚的 artifact-ref 首选**：viral_posts、user_viral_links、shooting_plan、optimization_analysis、ripple_comparison、analytics、visual_plan/copy_content（下游终末）、performance_log（→Event Store）、**messages + state content_history 直接移除**。
- **必须留守或需 ref 解析层**：evaluation_result（gate 契约）、content_versions/blogger_notes/trend_data（路由读长度/真值——需 RuntimeState 侧暴露 count/flag + body 外置）、brief_content（5 agent 扇出 + Dashboard）、publish_result、ripple_prediction/pmf。
- reducer 注意：append_list 的 viral_posts/performance_log/content_history/engagement_actions/ripple_job_ids 永不收缩 → checkpoint 复合膨胀；replace 系的（content_versions 等）有界。
