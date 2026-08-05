# creator_stats 同步周期改为一天一次

## 背景
当前 `creator_stats` 调度器基线间隔 36h（`CreatorStatsSettings.sync_interval_hours=36.0`），实际经三角分布 0.65-1.75× 约束在 23.4h-63h 间随机。用户要求缩短为「一天一次」。

## 需求
1. 不同步正文 —— 现状已如此（公开页正文爬取永久禁用，`client.py:615`），无需改动。
2. 同步周期改为一天一次：基线 24h，**保留反风控随机分布**（三角分布 0.65-1.75× → 实际 15.6h-42h 间随机），不破坏 active_window / skip_day / 三角分布等反风控机制。

## 方案
单点改动：`backend/config/settings.py:134` `sync_interval_hours: float = 36.0` → `24.0`。

调度器逻辑（`app.py:401 _creator_stats_scheduler`）不动，三角分布、活跃窗口、skip_day、连续失败退避、周封顶等反风控策略全部保留。

## 验收
- `/api/system/health` 返回 `interval_hours: 24.0`
- 调度器正常启动，next_run_at 落在合理范围
- 无回归：反风控状态表、success_history 逻辑不变
- `pytest tests/unit/services/creator_stats/` 全绿

## 非目标
- 不改反风控调度策略
- 不启用正文同步
- 不改 cooldown（`CREATOR_STATS_SYNC_COOLDOWN_MINUTES` 默认 45min）—— 24h 基线下 cooldown 永不触发
