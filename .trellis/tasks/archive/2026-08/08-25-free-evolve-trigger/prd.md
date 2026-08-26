# Free analytics triggers evaluator evolution（自由模式触发评估器进化）

## Goal

`/free/analytics` 成功回灌弱标签后 fire-and-forget 触发 `maybe_evolve(account_id)`——自由模式的样本积累到阈值（MIN_TRAIN_SAMPLES=10）即可自主拟合权重/推进 prompt epoch，不再依赖"恰好有一次工作流 analyst 运行"。移除 08-25-free-evaluator-samples PRD 记录的边界。

## Research

- 固定工作流模式：analyst 在 backfill_engagement 成功后
  `asyncio.create_task(_safe_evolve(account_id))`（analyst.py:211），_safe_evolve
  吞掉一切异常；maybe_evolve 内部按账号重入守卫（re-entry-guarded）。
- free 路径现状：get_analytics 已回灌弱标签（33742760 引入）但不触发 evolve；
  样本只积累、不拟合。
- maybe_evolve 位于 `backend.db.evaluator_config`（line 955），签名
  `async def maybe_evolve(account_id: str | None) -> dict[str, Any]`。

## Requirements

1. `backend/api/routes/free.py`：
   - 新增模块级 `_safe_free_evolve(account_id)`：镜像 analyst._safe_evolve，
     try/except 全吞 + logger.debug。
   - 新增薄封装 `_schedule_free_evolve(account_id)`：
     `asyncio.create_task(_safe_free_evolve(account_id), name=f"free_evolve_{account_id}")`
     ——为可测试性留的接缝（测试 patch 此函数）。
   - `get_analytics` 中，backfill_engagement 调用成功后（pool 就绪分支内、
     await 正常返回即视为成功）调用 `_schedule_free_evolve(account_id)`。
2. spec：free-creation.md 的 evaluate_draft 样本链 bullet 更新——移除
  "maybe_evolve 不从 free 路由触发" 的边界描述，改为 analytics 回灌成功后
  即调度 evolve。

## Acceptance criteria

1. backfill 成功 → _schedule_free_evolve 恰好以 account_id 调用一次。
2. pool 未就绪 / backfill 抛错 → 不调度。
3. 未发布 / mock post / 拉取失败路径不受影响（400 照旧，无调度）。
4. focused 测试绿 + ruff 干净；omp_bridge 套件保持绿。

## Out of scope

- GUI 锚点展示、material_ids 锚定、定时快照刷新（各自仍记录在案）。
