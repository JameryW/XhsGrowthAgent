# 历史笔记 RQGM 评估支持 — 调研结论

## 现状链路

### RQGM evaluator（单篇内容评估，EvaluationView 详情）
- 入口：`POST /evaluation/run/{thread_id}`（backend/api/routes/evaluation.py:run_evaluation）
- 从 checkpoint state 读 `copy_content` + `visual_plan` + `content_plan`
- 调 `EvaluatorAgent.execute(state, store)`（backend/agents/evaluator.py:112）
- 输出 `EvaluationResult`：overall_score / dimensions(10维) / decision / revision_hints / bias_warning / summary
- 10 维：copywriting/visual/compliance/reach/audience/ai_taste/image_quality/commercial_tone/altruism/bias_check
- prompt：`backend/config/prompts/evaluator.yaml`，纯文本 user_template
- 模型：`astron-code-latest`（讯飞 XUNFEI provider），**纯文本，无多模态**

### 历史笔记（CreatorNoteQualityPanel，单篇历史笔记）
- 入口：`GET /analytics/creator-stats/{account_id}/notes/{note_id}/quality`（analytics.py:682）
- 调 `analyze_note_quality(note, account_id, locale)`（services/creator_stats/quality.py）
- 输出 `CreatorQualityReport`：overall_score / grade / confidence / scope / dimensions[].evidence / recommendations
- **不是 RQGM，是确定性互动信号分析器**（views/likes/engagement 等）
- note 字段（db/creator_stats.py NoteStats）：note_id/title/body_text/tags/cover_url/content_type/views/likes/comments/collects/shares/engagement_rate/published_at + view_sources/audience_profile/audience_trend（detail enrichment）

## B 方案要做什么

evaluator 只吃 copy_content/visual_plan/content_plan。历史笔记要喂进去，需：
1. note → state 映射
2. evaluator 支持图片输入（B 核心）

### 映射
- copy_content: selected_title=title, body_text=body_text, hashtags=tags, cta="", tone=""
- content_plan: selected_topic/content_angle/target_audience="" (历史无), content_type=note.content_type
- visual_plan: **cover_url=note.cover_url**（新增字段！）, image_count, image_prompts=[], layout_style="", color_palette=[]

### 图片输入支持（B 核心，关键约束）
- 当前模型 astron-code-latest 是讯飞，**非多模态**
- user_template 视觉段是 `封面 prompt：{cover_prompt}` 文本
- 所以"图片输入"实际只能做到：**把 cover_url 告诉 LLM（文本形式）**，或下载图转 base64 喂多模态模型
- 真多模态需换模型 → 改 router EVALUATION task 路由 → 影响所有评估调用，风险大

## 关键决策点（待 brainstorm）
1. 图片"输入"到什么程度？
   - (a) 仅文本告知有图 + cover_url（最小，不换模型）→ image_quality/visual 维度仍是参考分
   - (b) 真多模态：换 EVALUATION 路由到多模态模型 + base64 喂图（改动大，影响 workflow 评估）
2. 新端点放哪？
   - `/evaluation/note/{account_id}/{note_id}` vs 复用 analytics 下 `/quality-rqgm`
3. 前端 CreatorNoteQualityPanel：保留旧 quality analyzer 还是替换成 RQGM？还是双展示？
