# free-draft-evaluate-tui-command

## Goal

free mode TUI 有 `/drafts` `/draft` `/edit` `/delete` `/analytics`，唯独 `/evaluate` 缺失——重评草稿只能 via agent 对话调 `xhs_free_evaluate`。#229 的 `/draft <id>` revise hint 已指向"重新 /evaluate"，但命令不存在，闭环断裂。加 `/evaluate <id>` TUI 命令，boxed 渲染 evaluation_result（score/decision/dimensions/revision_hints/bias），后端 `POST /free/evaluate` 已存在（回写 last_evaluation）。

## What I already know

- `backend/api/routes/free.py:193` `POST /free/evaluate`（FreeDraftRef: account_id+draft_id）→ `{draft_id, account_id, evaluation_result: {overall_score, decision, revision_hints, dimensions?, bias_warning?}}`。回写 `last_evaluation` triple + updated_at。
- `frontend/src/views/AgentTUI.vue` SLASH_COMMANDS（203）无 `/evaluate`；dispatch（836+）无 case；无 handleEvaluate。
- `/analytics` handler（boxed 渲染模板）：`handleAnalytics` GET `/free/analytics/{id}` → boxed table。
- `/draft <id>` detail（1214+）渲染 last_evaluation triple（score/decision + revision_hints • 列表）+ #229 revise hint 指向 `/evaluate`。
- agent 路径 `colorizeResultLine`（781）是文本流着色器（#215），不直接复用——TUI `/evaluate` 拿 JSON 自建渲染。
- i18n 模式：label 用 `t('tui.xxx')`，中英双 locale。evaluate 相关已有 `draftDetailEvalLabel`/`draftDetailHintsLabel`（详情用）。
- EvaluatorAgent 6 维 judge 面板（[[evaluator-agent-rqgm-integration]]），dimensions 结构：`[{dimension, score, is_blocking, rationale?}]`。

## Requirements

- TUI `/evaluate <id>` 命令：free mode 下 POST `/free/evaluate`，boxed 渲染 evaluation_result。
- 缺 `<id>` → 红字 usage 提示。
- 非 free mode → `freeWorkflowOpDisabled`（与其他 free 命令一致）。
- 400（draft 不存在等）→ 红字 route error message。
- 渲染：boxed title + draft_id + Overall score（青）+ Decision（approved绿/needs_revision黄/rejected红）+ dimensions 列表（dimension: score [BLOCKING]）+ bias_warning（品红，有则显）+ revision_hints（• 列表，有则显）+ 成功提示"已回写，/drafts 列表将显示新评估"。
- SLASH_COMMANDS 加 `/evaluate`（tab 补全）。
- `/help` agent + command mode free block 加 `/evaluate <id>` 行。
- first-entry banner（onMounted）freeCmd 列表加 `/evaluate` 行。
- i18n 中英双 locale 新增 key（evaluateTitle/usage/draftIdLabel/overallLabel/decisionLabel/dimensionsLabel/biasLabel/writtenBack 等）。
- spec 同步：free-creation.md Scope/Trigger 命令列表 + handleDraft detail revise hint 子节（#229 指向的 `/evaluate` 现已存在，去掉 deferral 语气）+ 新 `/evaluate <id>` 行为契约子节。

## Acceptance Criteria

- [ ] `/evaluate <id>` free mode → boxed evaluation_result 渲染
- [ ] `/evaluate`（无 id）→ 红字 usage
- [ ] 非 free mode → freeWorkflowOpDisabled
- [ ] 400 → 红字 route error
- [ ] Overall score 青色；decision 按值着色
- [ ] dimensions 列表渲染（score 青，[BLOCKING] 标记）
- [ ] bias_warning 有则品红显示
- [ ] revision_hints 有则 • 列表
- [ ] 成功后提示已回写 last_evaluation
- [ ] SLASH_COMMANDS + /help（agent+command free block）+ first-entry banner 含 /evaluate
- [ ] 中英 i18n key 齐
- [ ] vue-tsc typecheck 绿

## Definition of Done

- TUI handleEvaluate + dispatch + SLASH_COMMANDS + help + banner + i18n 中英
- spec 同步
- vue-tsc 绿（前端 gate，build 留 CI）

## Technical Approach

`handleEvaluate(draftId)` 照 `handleAnalytics` 模板：
```js
const resp = await client.post(`/free/evaluate`, { account_id: accountId, draft_id: draftId })
const data = resp as unknown as { draft_id, account_id, evaluation_result: {...} }
const ev = data.evaluation_result || {}
// boxed: title + draft_id + Overall + Decision + dimensions + bias + hints + writtenBack
```
decision 着色复用 handleDraft detail 的映射（approved绿/needs_revision黄/rejected红）。
dimensions: `ev.dimensions?.forEach(d => writeLine dimension:score [BLOCKING])`。
SLASH_COMMANDS 加 `'/evaluate'`（保持字母序，在 /edit 后或 /drafts 前——按现有乱序，加 /edit 后）。

dispatch（processSlashCommand + processCommandMode 双 dispatch，如 /edit）：`case '/evaluate': handleEvaluate(parts.slice(1).join(' ').trim())`。

## Out of Scope

- `/publish` TUI 命令——publish 涉及真实 CDP/XHS 发布，free mode 设计 agent 驱动发布，TUI 直发风险高，保持 agent-only。
- evaluate 参数（niche/angle 覆盖）——POST /free/evaluate 只吃 draft_id，草稿已存 niche/angle。
- 评估历史——单次最新，YAGNI。
- 一键应用 revision_hints——hints 自然语言，YAGNI。

## Technical Notes

- `backend/api/routes/free.py:193` evaluate_draft（已存在，无后端改动）
- `frontend/src/views/AgentTUI.vue`：SLASH_COMMANDS（203）、dispatch（860-925 区）、handleAnalytics（模板）、handleDraft detail（1214+ decision 着色映射）、showHelp（1358+）、first-entry banner（1605+）
- `frontend/src/locales/zh-CN.json` + `en.json`
- `.trellis/spec/backend/free-creation.md`：Scope/Trigger 命令列表（13 行）、handleDraft detail revise hint、新 `/evaluate <id>` 行为契约
- vue-tsc gate [[vite-build-oom-low-ram-box]]
- 从 main 新建分支 [[separate-pr-per-feature]]
