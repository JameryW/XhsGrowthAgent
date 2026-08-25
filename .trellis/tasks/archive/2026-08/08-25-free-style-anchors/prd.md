# Free drafts anchor creative memory calibration（自由草稿锚定创作记忆）

## Goal

给自由草稿引入可选的 style_id / play_id 元数据，让智能体能把"这次创作用了哪个风格/打法"锚定回草稿；发布后表现数据到手时触发 creative memory 校准——补齐 08-24 任务记录在案的最后一个回流缺口（当时因草稿无风格 ID 而明确不做）。

## Research（2026-08-25 现状核对）

- `create_draft` 已召回 Style DNA / Conversion Plays / Materials 并通过
  `build_creative_context` 返回给智能体（free.py:276-288）。
- **缺口 A**：`build_creative_context` 只渲染 tone/visual/互动率，不暴露记录 ID
  （creative.py:611-664）→ 智能体无从回填锚点。
- **缺口 B**：`FreeDraft` 模型没有 style_id/play_id 字段；`_build_publish_state`
  不映射 → run_publish 的 ContentHistory 记录里校准链字段恒为空
  （publisher.py:336-349 已读取 visual_plan.style_id / content_plan.play_id）。
- **缺口 C**：`get_analytics` 拿到互动数据后不构建 CalibrationPayload。
- analyst 的校准模式：`actual_save_rate = collects/views`；
  `build_calibration_payload(state, rate, save_rate)` 从 content_plan.play_id /
  visual_plan.style_id / copy_content 提取并内部判 play_success(≥3%)；
  `schedule_calibration(store, payload)` fire-and-forget。

## Requirements

### Backend — `backend/api/routes/free.py`

1. `FreeDraft` + `FreeDraftUpdate`：新增可选 `style_id: str = ""`、
   `play_id: str = ""`（空=未锚定，向后兼容）。
2. `_build_publish_state`：draft.style_id → `visual_plan["style_id"]`、
   draft.play_id → `content_plan["play_id"]` —— run_publish 的 ContentHistory
   记录自动携带校准链字段（复用现有读取逻辑，不改 publisher）。
3. `get_analytics`：快照落库后，若草稿带 style_id 或 play_id 且 views > 0：
   - 用 `_build_publish_state(draft)` 加 `publish_result.post_id` 合成 state，
     `build_calibration_payload(state, _engagement_fraction(snapshot), save_rate)`
     （save_rate = collects/views，views>0 才算）；
   - `schedule_calibration(store, payload)` fire-and-forget；
   - try/except + logger.warning 非阻塞；无 ID 或无浏览时不调用。
4. omp_bridge：`xhs_free_draft_create` 参数 schema 增加 style_id/play_id 描述
   （注明"基于召回的风格/打法创作时回传其 id，用于效果校准"）；usage 文本
   （~line 1002）同步提及可选参数。

### Backend — `backend/memory/creative.py`

5. `build_creative_context`：风格行与打法行各暴露记录 id（如
   `id=s_xxx` / `id=p_xxx`），使锚定成为可能。共享面（trend/brief）只增不破。

### Spec

`.trellis/spec/backend/free-creation.md`：FreeDraft 字段表 + create/publish/
analytics 行为更新 + 校准触发条件；omp-integration.md 如列有工具 schema 亦同步。

## Acceptance criteria

1. create/PATCH 均可持久化 style_id/play_id（缺省为空串，旧草稿不受影响）。
2. 发布路径传给 run_publish 的 state 含映射后的 style_id/play_id。
3. analytics：有锚点 + views>0 → schedule_calibration 收到含正确
   style_id/play_id/post_id/rates 的 payload；无锚点或 views=0 → 不触发。
4. build_creative_context 输出包含召回记录的 id。
5. 后端 focused 测试（free routes + creative context）全绿、ruff 干净；
   omp_bridge 测试保持绿。
6. spec 更新与实现一致。

## Out of scope

- 强制锚定（ID 缺失时静默降级，不阻断创作流）。
- 素材（material_ids）锚定：素材由文案内联使用，无独立载体，暂不做。
- 前端展示锚点信息（GUI History 卡片本轮不加）。
- maybe_evolve 触发时机改造（维持既有边界）。
