# 第五轮历史质量数据一致性审计

## 审计范围

沿第四轮的 bundle contract 继续追踪：Creator Stats storage → Analytics/quality API →
RQGM evaluation persistence/latest restore → Pinia Analytics actions。重点检查同账号
快照身份是否贯穿创建、缓存命中、刷新恢复和账号切换。

## 发现

### A. RQGM 历史评估与 Creator Stats 使用不同 snapshot 算法

`backend/api/routes/evaluation.py` 的历史评估入口使用 `get_note_stats(account_id,
note_id)`，随后把 `note.synced_at` 传给 `build_snapshot_id`。第四轮的 Analytics 和
`/creator-stats/{account_id}/quality` 已经使用完整 bundle，并按完整 note facts 生成
包含 subject versions 的 digest。两者在同一 timestamp 下会得到不同 ID；指标覆写也会
改变 canonical digest，而旧 RQGM run 仍会返回 timestamp-only ID。

### B. 持久化 JSONB 已能承载 additive source metadata

`quality_evaluation_runs` 已持久化 `result_json`，没有必要为 snapshot 另造 migration。
将 canonical ID 写进 `result_json.source` 可以覆盖新建、cache hit、latest restore，且
老数据读取时仍可 fallback；latest 读取应以当前 bundle 做 freshness 校验并沿用现有
`mark_subject_stale` 审计机制。

### C. Analytics 独立 actions 缺少请求所有权

`fetchAllData` 已有 generation/account guard，但 `fetchReport` 和 `fetchPerformance`
在 await 后直接写入 store。它们虽不是当前 Analytics 页面主路径，却被公共 store 暴露，
账号/周期切换期间仍能把旧响应写入新页面。应复用同一请求所有权规则并为无账号场景短路。

## 方案取舍

- 不新增 `quality_evaluation_runs.snapshot_id` 列：JSONB source 已是版本化结果的一部分，
  additive、无迁移、兼容 memory/Postgres 两条路径。
- 不把 metrics-only 变化混入内容 hash：latest 先把旧结果标成 stale，保留可审计版本；
  用户显式提交 rerun 后才产生新评估。
- 不重构 `fetchAllData`：只收敛两个缺 guard 的 action，避免改变已经验证的 dashboard
  loading 语义。

## 需要验证的场景

1. 同一账号两次 bundle timestamp 相同但指标不同，评估 source snapshot 必须变化，latest
   旧 run 必须 stale。
2. cache hit 必须原样带出 canonical source snapshot。
3. 账号 A 请求延迟、切换到 B 后 A response 不得覆盖 B；无 active account 不发请求。
