# 商单/趋势模式选博主后生成多风格笔记版本

## Goal

无论商单还是趋势模式，选完参考博主后，系统应基于 brief/plan + 参考博主笔记生成多个不同风格的笔记版本，供用户在 choice_gate 中选择风格；选完风格后，再由 version_generator 基于选中风格 + 优化分析生成 A/B/C 版本供用户二次选择。

## Requirements

1. `CopywriterAgent` 在有 `blogger_notes` 时，生成 3 个不同风格的笔记版本写入 `content_versions`
2. 风格维度基于参考博主笔记的风格特征动态定义（如：专业测评风、生活种草风、教程干货风）
3. 无 blogger_notes 时保持单版行为
4. 第一层 choice_gate：用户选风格，选中版本回写到 `copy_content` + `draft_content`
5. 第二层：version_generator 基于选中风格的 `draft_content` + `optimization_analysis` 生成 A/B/C 版本
6. 第二层 choice_gate：用户选 A/B/C 版本
7. 两种模式统一逻辑

## Acceptance Criteria

- [ ] 商单模式选完博主后，系统生成 ≥2 个不同风格的笔记版本
- [ ] 趋势模式选完博主后，系统生成 ≥2 个不同风格的笔记版本
- [ ] 第一层 choice_gate 展示风格选项，选择后回写 copy_content + draft_content
- [ ] 选风格后 version_generator 基于选中风格生成 A/B/C 版本
- [ ] 第二层 choice_gate 展示 A/B/C 版本选项
- [ ] 跳过博主选择 / 无 blogger_notes 时，不生成多版本（保持单版行为）
- [ ] 没有 blogger_notes 的趋势模式不受影响

## Definition of Done

* Tests added/updated（copywriter agent + choice_gate + version_generator + routers）
* Lint / typecheck green
* 前后端联调验证两层 choice_gate
* Deploy 验证

## Technical Approach

### 路径变化

**有博主笔记时（两种模式）**：
```
copywriter(多风格) → draft_gate → shooting_planner → content_analyzer
→ choice_gate(选风格) → version_generator(A/B/C) → choice_gate(选版本) → visual_designer
```

**无博主笔记时（两种模式）**：
```
copywriter(单版) → draft_gate → shooting_planner → content_analyzer → version_generator → [choice_gate] → visual_designer
```

### 具体改动

1. **`CopywriterAgent.execute()`**：有 `blogger_notes` 时让 LLM 一次输出 3 个风格版本写入 `content_versions`，每个版本含 version_id/title/body/hashtags/tone/style_suggestion/visual_style；无则保持单版
2. **`copywriter_node`**：将 `content_versions` 传递到 state
3. **`routers.py` 新增 `content_analyzer_router`**：替代 `content_analyzer → version_generator` 硬边——有 content_versions 且长度 > 1 → choice_gate；否则 → version_generator
4. **`builder.py`**：content_analyzer 后改为条件边
5. **`choice_gate_node`**：选中风格版本后，同时回写 `draft_content`（作为 version_generator 输入），标记 `style_selected=True`
6. **`choice_outcome` router**：改为路由到 version_generator（而非直接 visual_designer），让 version_generator 基于选中风格 + optimization_analysis 生成 A/B/C
7. **`version_generator.py`**：读取 `draft_content`（来自选中风格），生成 A/B/C 版本时以选中风格为基底
8. **`copywriter.yaml`** prompt 调整：增加多风格输出格式说明

### 不改动

- `select_version` API（复用现有 endpoint，两次 choice_gate 都用同一个 API）
- shooting_planner 逻辑
- content_analyzer 逻辑
- 前端 VersionCompare 组件（已支持多版本展示）

### 关键设计：两层 choice_gate 复用

choice_gate_node 通过 `interrupt_before` 暂停，`select_version` API 写 `selected_version` 到 state 后 ainvoke(None) 恢复。两层选择复用同一套机制：

- 第一层：content_versions 是风格版本，用户选风格，choice_gate_node 回写 copy_content + draft_content + style_selected=True
- 第二层：content_versions 被 version_generator 覆盖为 A/B/C 版本，用户选版本，choice_gate_node 回写最终 copy_content + visual_plan

version_generator 需要检测 `style_selected=True`，使用 `draft_content` 作为基底（而非旧的优化路径）。

## Decision (ADR-lite)

**Context**: 多风格版本在哪里生成？两层选择如何实现？
**Decision**: copywriter 生成风格版本，choice_gate 选风格后回写 draft_content，version_generator 基于选中风格生成 A/B/C 版本，choice_gate 再选版本。保留 shooting_planner 和 content_analyzer。
**Consequences**: choice_gate 被走两次，前端需要区分"选风格"和"选版本"（但 UI 已展示 content_versions，无需改组件逻辑）；version_generator 需适配有 draft_content 的路径

## Out of Scope

* 前端 choice_gate UI 大改（现有 VersionCompare 组件已支持）
* content_analyzer 逻辑修改
* shooting_planner 逻辑修改

## Technical Notes

* 关键文件：
  - `backend/agents/copywriter.py` — 增加多风格生成
  - `backend/agents/nodes/copywriter.py` — 传递 content_versions
  - `backend/agents/nodes/optimization/choice_gate.py` — 回写 draft_content
  - `backend/agents/nodes/optimization/version_generator.py` — 适配选中风格路径
  - `backend/graph/routers.py` — content_analyzer_router + choice_outcome 改路由
  - `backend/graph/builder.py` — content_analyzer 条件边
  - `backend/config/prompts/copywriter.yaml` — prompt 多风格格式
  - `backend/api/routes/optimization.py` — 无需修改（复用 select_version）
* blogger_notes 格式：`[{title, body, hashtags, likes, collects, comments, engagement_rate}]`
* content_versions 格式：`[{version_id, title, body, hashtags, tone, style_suggestion, visual_style, color_palette}]`
