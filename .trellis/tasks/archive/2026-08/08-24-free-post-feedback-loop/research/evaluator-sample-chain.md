# Research: Free 模式接入评估器在线进化（RQGM 样本链）

日期：2026-08-24 · 状态：下一增量候选（本轮 08-24-free-post-feedback-loop 的后续）

## 现状

自由模式的 RQGM 评估（`POST /free/evaluate` → `EvaluatorAgent.execute`）**从不产生训练样本**：

- 固定工作流的样本收集在 `backend/agents/nodes/evaluator.py::_collect_sample`，
  `thread_id = state.get("session_id")` 为空时直接 return（free 无 thread）。
- free 路线不经过该节点包装器，直接调用 agent，因此连跳过逻辑都不存在——
  就是单纯没有收集。
- 弱标签回灌 `backfill_engagement(thread_id, engagement)` 按
  "latest-by-thread" UPDATE（`backend/db/evaluator_config.py:454-477`）。
- 在线进化 `maybe_evolve(account_id)` 已是账号作用域，MIN_TRAIN_SAMPLES=10，
  engagement→rate 用 `(likes+collects+comments+shares)/views`（小数口径，
  `evaluator_config.py:504-517`），与 ContentHistory 回填口径一致。

## 关键发现：不需要改表

```sql
CREATE TABLE IF NOT EXISTS evaluator_samples (
    ...
    thread_id TEXT NOT NULL,   -- 只是 TEXT！无外键、无格式约束
```

用合成键 **`free:{draft_id}`** 即可让 free 评估进入同一条样本链：
insert_sample / backfill_engagement / maybe_evolve 全部原样复用。

## 设计草图（下个任务）

1. `free.py::evaluate_draft`：评估成功且 **非 degraded** 时，
   `insert_sample(EvaluatorSample(
       account_id, thread_id=f"free:{draft_id}",
       dimensions=evaluation_result.dimensions, overall_score, decision,
       label_source="evaluator",
       content_snapshot={title/body/hashtags/niche/content_angle/target_audience}))`
   - 前置条件：`is_pool_ready()`（Postgres 可用）；非阻塞 try/except +
     logger.warning —— 与 analyst 的回灌守卫一致。
   - degraded（LLM 超时假 100/approved）绝不能入样本（会污染训练集）。
2. `get_analytics`（依赖本轮已落库的快照）：成功拉取互动后追加
   `backfill_engagement(f"free:{draft_id}", {views/likes/collects/comments/shares})`
   ——弱标签自动挂到该草稿的最新评估样本上。
   - 注意传给 backfill 的 dict 是原始计数（它自己算 rate），不要传百分比。
3. 重复 /edit + 再 /evaluate 会插多条样本：与固定工作流修订行为一致
   （backfill 取 latest-by-thread），可接受；导出训练集时全部在册。

## 风险 / 边界

- SQLite/memory 后端无 pool → is_pool_ready() False → 静默跳过（与现状等价）。
- 样本量冷启动：free 单账号到 10 条才触发拟合，短期无效果属预期。
- spec 同步点：`.trellis/spec/backend/free-creation.md`（evaluate 契约 +
  Draft Status Metadata）与 `.trellis/spec/backend/workflow-state.md` 若有
  RQGM 章节需同步。

## 结论

小改动、零迁移、全复用。等本轮快照落库合入后即可立项实施。
