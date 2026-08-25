# Free-mode RQGM samples feed evaluator evolution（自由创作评估接入在线进化）

## Goal

让自由创作模式的 RQGM 评估进入既有评估器训练样本链，并在发布表现数据到手后回灌弱标签——复用固定工作流的 insert_sample / backfill_engagement / maybe_evolve 全链路，零 schema 迁移。

## Research（继承自 08-24-free-post-feedback-loop/research/evaluator-sample-chain.md）

- 固定工作流样本收集在 `backend/agents/nodes/evaluator.py::_collect_sample`：无 thread 直接跳过；free 路线不经过该节点 → 完全没有样本。
- `evaluator_samples.thread_id` 只是 TEXT 列 → 合成键 **`free:{draft_id}`** 即可入链。
- `backfill_engagement(thread_id, engagement)` 按 latest-by-thread UPDATE。
- `maybe_evolve(account_id)` 已账号作用域（MIN_TRAIN_SAMPLES=10）。
- 弱标签 rate 口径 = (likes+collects+comments+shares)/views 小数，与 ContentHistory 一致。

## Requirements

### Backend — `backend/api/routes/free.py`（唯一后端改动文件）

1. `evaluate_draft`：评估完成后、返回前，镜像 `_collect_sample` 的守卫与形状插入样本：
   - 跳过条件（任一）：`status ∈ {degraded, failed, running, unavailable}`；`degraded` 标志为真（LLM 超时假 100/approved）；`overall_score` 为 None。**degraded 绝不入样本**。
   - `is_pool_ready()` 为假 → 静默跳过（SQLite/memory 后端）。
   - `thread_id = f"free:{draft_id}"`，`label_source="evaluator"`，
     dimensions/overall_score/decision 取自 evaluation_result；
   - content_snapshot 为 free 形状：title、body[:2000]、hashtags + niche /
     content_angle / target_audience（评估上下文是有效训练输入）；
   - 整体 try/except 非阻塞（logger.debug），失败绝不影响 evaluate 响应。
2. `get_analytics`：成功拉取并落快照后，best-effort 回灌弱标签：
   - `is_pool_ready()` 守卫；`backfill_engagement(f"free:{draft_id}", {views, likes, collects, comments, shares})`（原始计数 dict，rate 由其内部计算）；
   - try/except + logger.warning，不影响 analytics 响应。

### Spec

`.trellis/spec/backend/free-creation.md`：
- `/evaluate` 契约行补样本写入说明（合成键、跳过条件）；
- `/analytics` 行与 Write-back behavior 补 backfill_engagement 回灌；
- 记录与固定工作流 `_collect_sample` 的镜像关系。

## Acceptance criteria

1. 非 degraded 评估且 pool 就绪 → 插入一条 thread_id=`free:{draft_id}` 的样本，字段与快照断言正确。
2. degraded / score None / status 不可消费 → 不插入。
3. pool 未就绪 → 不插入且无异常外泄。
4. `/free/analytics` 成功 → 以 `free:{draft_id}` 调用 backfill_engagement 且传原始计数；pool 未就绪或调用抛错 → 响应仍 200。
5. focused 后端测试全绿 + ruff 干净；前端无改动（本轮纯后端），现有前端门不受影响。
6. spec 更新与实现一致。

## Out of scope

- maybe_evolve 触发时机改造（沿用 analyst 模式即可——free 路径暂不触发 evolve；样本积累到阈值后由下一次工作流 analyst 触发拟合。记录该边界）。
- 前端展示样本状态。
- 历史存量草稿的补采样。
