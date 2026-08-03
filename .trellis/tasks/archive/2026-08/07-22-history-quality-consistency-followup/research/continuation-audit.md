# 一致性续审（2026-07-22）

## 审计范围

本轮沿着 `creator_note_stats -> canonical reader -> Analytics/Evaluation`
以及 `creator_note_stats/workflow checkpoint -> Analytics dashboard` 的调用链复核。
代码图确认的主要入口为：

- `backend/db/creator_stats.py:list_note_stats_page`
- `backend/api/routes/analytics.py:_creator_snapshot_metadata`、`get_dashboard`
- `frontend/src/api/analytics.ts:getCreatorNotes`
- `frontend/src/views/Analytics.vue`、`EvaluationView.vue`

上一轮已统一账号边界、游标、来源页签、评估状态和基础 `snapshot_id`，但还有以下可复现风险。

## 发现的问题

### CC-01：Postgres 旧数据没有账户行时，跨页快照可能漂移

内存 reader 会从整个账号的 note bucket 计算 `data_as_of`；Postgres reader 在没有
`creator_account_stats` 行时只从当前页的 `selected_rows` 计算时间点。于是第一页和第二页
可能返回不同 `snapshot_id`，前端只能把正常的分页追加误判为跨批次数据。

### CC-02：时间戳不是充分的内容版本

当前快照主要由 `account_id + max(synced_at)` 组成。如果导入器或修复脚本在同一
`synced_at` 下覆盖互动指标，旧快照和新快照仍相同，cursor stale guard 无法阻止混页，
Analytics 的原始指标比对也没有稳定的服务端版本依据。

### CC-03：Analytics period/performance 响应仍混用互动率单位

canonical note endpoint 明确声明 `engagement_rate_unit=fraction`，但
`_imported_notes_as_posts` 和 workflow post adapter 为兼容旧报表把每行转换成百分比。
这让同一事实在不同 API 响应中仍有两个单位，外部消费者容易把 0.05 当成 5% 或反之。

### CC-04：快照元数据逻辑重复

Analytics、canonical reader、详情和质量报告分别计算 `data_as_of/snapshot_id`，旧数据、
空账户和 DB fallback 的行为容易继续分叉。快照应由 Creator Stats 存储层提供一个可复用的
account snapshot metadata helper；API 只负责组合响应。

## 本轮目标

1. 为每次原子 Creator Stats 导入生成并持久化不含明文业务 ID 的快照 ID；旧数据无快照时以
   稳定的 note 版本摘要兼容推导。
2. canonical reader、Analytics dashboard/report/performance、账户质量报告和单篇详情复用同一
   存储层 snapshot metadata，跨页、空账户和 Postgres fallback 行为一致。
3. Analytics 的原始帖子响应统一使用 fraction，并增加显式 `engagement_rate_unit`；百分比只在
   前端展示层格式化，报表均值也明确单位。
4. 增加同时间戳指标覆盖、无账户行 Postgres reader、跨接口单位和快照一致性回归测试。

## 非目标

- 不改变发布后表现分的权重或 RQGM 权重。
- 不把发布后表现分和 RQGM 内容评审分合并。
- 不触发页面同步，不引入新的外部服务或浏览器依赖。

## 复核结论

CC-01/02 已由存储层完整 population digest 和原子导入 `snapshot_id` 覆盖；CC-03 已在
Analytics API 边界统一为 fraction，并由前端/OMP 显式适配展示；CC-04 已收敛到
`get_creator_stats_snapshot`。剩余风险仅是无浏览器 harness 的真实双账号人工验收，属于发布前
运维验收而非本轮代码阻塞项。
