# Free Creation post-publish feedback loop（自由创作发布效果回流）

## Goal

让自由创作（Free Creation）发布后的真实表现数据回流系统：快照落库、内容历史回填、轻量洞察沉淀，并在 TUI 与 GUI 双端呈现，闭合「创作 → 评估 → 发布 → 表现 → 再创作」循环。

## Research summary（现状调研 2026-08-24）

固定工作流发布后由 analyst 节点完成四类回流：

1. LLM 洞察/策略建议 → `store_insight` / `store_strategy_note`（`backend/agents/analyst.py:142-154`）
2. ContentHistory 记录回填真实互动指标（views/likes/collects/comments/shares/engagement_rate，`analyst.py:156-183`）
3. 评估样本 engagement 回灌 + maybe_evolve（thread-bound，`analyst.py:185-213`）
4. Creative memory 校准（`build_calibration_payload` → `schedule_calibration`，依赖 style_id/play_id/material_ids）

自由创作模式现状：

- `/free/publish` 复用 `run_publish`：成功后草稿记录 `published/post_id/post_url`，ContentHistory 记录了 title/topic 等 —— 但 `_build_publish_state` 不携带 style_id/play_id，历史记录的校准链字段恒为空。
- `/free/analytics/{draft_id}` 实时 CDP 拉取互动数据，**不落库**：草稿记录不变、ContentHistory 不回填、无洞察写入、无任何记忆沉淀。
- 前端 TUI `/analytics <id>` 仅渲染当次实时数据；`/draft <id>` 详情无表现数据；GUI History 自由草稿 Tab 无互动列。
- 评估样本收集 `_collect_sample` 在无 thread 时跳过 → 自由模式 RQGM 评估不入训练样本（本次不改）。

## Gaps

- **G1 快照不落库**：每次 `/analytics` 都要 CDP 在线重拉；浏览器关掉后 TUI/GUI 无法看到任何历史表现。
- **G2 内容历史缺指标**：自由帖子的 ContentHistory 记录永远没有 views/likes 等字段，与固定工作流行为不一致。
- **G3 无洞察沉淀**：自由模式表现数据从不进入 memory insights，后续创作的 recall 无法利用。
- **G4 双端无呈现**：TUI 草稿详情、`/drafts` 列表、GUI History 卡片都看不到已发布笔记的表现。

## Requirements

### Backend (`backend/api/routes/free.py`)

- `/free/analytics/{draft_id}` 成功拉取后将快照持久化到草稿记录：
  - `last_analytics = { views, likes, collects, comments, shares, engagement_rate, post_id, fetched_at }`
  - 刷新草稿 `updated_at`。
- 回填 ContentHistory：按 post_id 定位记录，写入互动指标并计算 engagement_rate（复用 analyst 的 aget→mutate→aput 模式；记录缺失时跳过，不报错）。
- 沉淀确定性洞察（不走 LLM）：基于互动率阈值生成 1 条简短 insight 写入 insights namespace，metadata 带 `{source: "free_analytics", post_id, draft_id}`；无 views 时跳过。
- Creative memory 校准**不做**：自由草稿无 style_id/play_id/material_ids，payload 全空只会空转；在代码注释与本 PRD 记录该边界，待草稿携带风格元数据后再接入。
- `list_drafts` 摘要与 `get_draft` 详情透出 `last_analytics`（列表仅摘要字段，详情全量）。

### Frontend — AgentTUI

- `FreeDraftRecord` 类型增加 `last_analytics?`。
- `/analytics <id>` 渲染追加「快照已保存」提示行（含保存时间）。
- `/draft <id>` 已发布草稿详情卡片内追加一行最新表现摘要（views/likes/collects + 采集时间）；无快照时保持现状提示。

### Frontend — History 自由草稿 Tab

- 已发布且带 `last_analytics` 的卡片显示紧凑互动徽标（views · likes · collects），附 tooltip 或次要文案显示采集时间；无快照维持现状。
- 双语 locale 键同步（en / zh-CN）。

## Acceptance criteria

1. `/free/analytics` 成功后草稿含 `last_analytics`，再次调用覆盖为最新快照；mock 发布（post_id 以 mock_ 开头）与未发布草稿仍 400 且不写快照。
2. ContentHistory 中存在该 post_id 记录时，指标被回填且 engagement_rate 正确计算；记录缺失时静默跳过。
3. 互动率 ≥ 阈值时 insights namespace 新增一条 source=free_analytics 的洞察；store 为 None 或 views=0 时不写入也不报错。
4. list/get 接口返回 `last_analytics`；TUI 与 History 面板正确渲染新字段，双语键齐全。
5. 后端 focused tests（free analytics/list/detail）+ 前端 focused tests（api 类型、TUI 渲染、History 面板）通过；type-check、i18n:check、build 通过。
6. README 如涉及用户可见行为变化则双语同步（预计仅在 Free Creation path 小节补一句）。

## Out of scope

- 评估样本 thread-less 收集与 backfill_engagement 改造（涉及 evaluator_config DB schema，另立任务）。
- Creative memory 校准接入（需先给自由草稿引入 style/play 元数据）。
- 定时自动刷新快照（scheduler 类工作）。
- LLM 版 analyst 深度分析用于自由模式。
