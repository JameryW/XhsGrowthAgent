# Engagement snapshot trend series（互动快照趋势序列）

## Goal

每次 `/free/analytics` 采集目前覆盖上一份快照，创作者看不到笔记互动随时间的走势。保留最近 N 次采集形成序列，双端呈现"较上次"变化——把单点数据升级为轨迹数据。

## Requirements

### Backend — `backend/api/routes/free.py`

1. `get_analytics` 持久化时：
   - `last_analytics` 语义不变（始终最新一次）；
   - 同时追加到 `draft["analytics_snapshots"]` 数组并**封顶 10 条**（超出丢弃最旧）；
   - 刷新 updated_at 的行为不变。
2. `list_drafts` 摘要新增可选 `engagement_trend` 字段：
   - 形状 `{views: int, delta_views: int, captured_at: str} | None`；
   - 仅当 snapshots ≥ 2 时给出：views=最新，delta_views=最新-前一次；
   - < 2 条或字段缺失 → None。服务端计算保持列表 payload 精简。
3. `get_draft` 返回完整记录 → 自动含 analytics_snapshots（无需改动）。

### Frontend

4. `api/free.ts`：`FreeDraftTrend { views, delta_views, captured_at }`；summary 加
   `engagement_trend?`；`FreeDraftRecord` 本地接口（AgentTUI）加
   `analytics_snapshots?: FreeDraftAnalytics[]`。
5. AgentTUI `/draft` 详情：已有快照行基础上，当草稿 snapshots ≥ 2 时追加走势行
   （views 较上次 ±N，正绿负红）；i18n 键双语。
6. History 面板：卡片徽标区在 engagement_trend 存在时显示带方向的变化量
   （▲/▼ + 数值），无则维持现状；i18n 键双语。

### README + spec

7. README 双语 Free Creation path 小节补一句趋势追踪说明。
8. spec free-creation.md：analytics 行为补序列语义（cap 10、trend 计算规则）。

## Acceptance criteria

1. 连续采集 11 次 → snapshots 恰好 10 条且最旧被丢；last_analytics 始终等于最新。
2. list 摘要 trend 字段按规则出现/缺席；delta 计算正确。
3. TUI 详情 ≥2 条快照显示走势行；GUI 卡片有 trend 徽标；均双语。
4. 后端 focused 测试绿 + ruff 干净；前端 focused 测试 + type-check + i18n + build 绿。
5. spec 与实现一致。

## Out of scope

- 定时自动采集（仍为手动 /analytics 触发）。
- 走势图表渲染（文本增量即可）。
- 非 views 维度的趋势展示。
