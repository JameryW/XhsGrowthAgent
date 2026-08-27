# Display creative memory anchors on drafts（草稿锚点展示）

## Goal

锚定功能（style/play/material）已全链路打通，但对人类用户完全不可见——只有 agent
知道草稿基于哪些记忆创作。本轮把锚点信息呈现到 TUI 详情卡与 GUI 历史卡片，让创作者
理解"这条笔记为什么这样写"以及校准发生在哪里。

## Requirements

### Backend — `backend/api/routes/free.py`

1. `list_drafts` 摘要新增 `style_id: str`、`play_id: str`、`material_ids: list[str]`
   （直接来自记录，空值照旧；payload 增量极小——短 id 字符串）。
2. `get_draft` 返回完整记录已含字段，无需改动。

### Frontend

3. `api/free.ts`：summary 加三字段类型。
4. AgentTUI `/draft` 详情：存在任一锚点时渲染锚点行
   `锚定：风格 {id} · 打法 {id} · 素材 ×N`（缺失项跳过；i18n 组装，客户端 join）。
5. History GUI 卡片：评估徽标区附近显示锚定徽标（计数 + tooltip 列出 id），仅当有
   锚点时出现。
6. i18n 双语新键（tui 4 个 + history 1 个）。

### spec

7. free-creation.md list_drafts surface 行补三字段。

## Acceptance criteria

1. 摘要含三字段且无锚点草稿为空串/空数组。
2. TUI 详情有锚点显示行、无锚点不显示；素材只显示数量。
3. GUI 徽标仅在有锚点时出现。
4. 后端 focused + ruff 绿；前端 test/type-check/i18n/build 绿。

## Out of scope

- 定时自动采集（留档）。
- 锚点可编辑 UI（PATCH API 已支持，GUI 表单暂不做）。
