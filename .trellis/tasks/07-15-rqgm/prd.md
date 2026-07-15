# 历史笔记 RQGM 评估支持（含图片输入预留）

## 背景与动机

质量评估页两处"单篇"展示不一致：
- **单篇内容评估**（EvaluationView 详情）：走 RQGM `EvaluatorAgent`，10 维 judge 面板 + 雷达图 + decision/hints
- **单篇历史笔记**（CreatorNoteQualityPanel）：走 `analyze_note_quality` 确定性互动信号分析器，grade/confidence/evidence/recommendations，无雷达图

两者数据源不同、维度体系不同、UI 不同。用户要求历史笔记也支持 RQGM 评估，且 evaluator 加图片输入支持。

## 核心决策（已 brainstorm 确认）

1. **图片输入：先文本、预留多模态**
   - evaluator 加 `image_urls` 字段到 visual_plan，prompt 加"封面/图片 URL"槽位
   - 当前模型 `astron-code-latest`（讯飞）纯文本，URL 以文本形式告知 LLM
   - 多模态能力就绪时（换模型/支持 vision），改 `ainvoke` 消息构造为图+文，字段已就位
   - 不换路由模型，不影响现有 workflow 发布前评估

2. **端点：独立 `POST /evaluation/note`**（仿 free.py `/evaluate` 范式）
   - body: `{ account_id, note_id }`
   - 后端：读 `NoteStats` → 构造 `eval_state`（仿 `_build_eval_state`）→ 调 `EvaluatorAgent.execute` → 返回 `EvaluationResult`
   - 不写 checkpoint（note 无 thread，同 free 模式）
   - 与 `/run/{thread_id}` 并存，不污染 checkpoint 路由

3. **旧 analyzer：并排嵌入保留**
   - `CreatorNoteQualityPanel` 保留现有互动信号 quality analyzer
   - RQGM 评估结果作为补充 section 嵌入同一面板（复用 EvaluationView 的展示块：总分+decision+雷达图+维度+hints）

## note → eval_state 映射

```
account_id   ← note.account_id
niche        ← account niche（从 account 配置取，缺省 "母婴"）
copy_content:
  selected_title ← note.title
  body_text      ← note.body_text
  hashtags       ← note.tags
  cta            ← ""（历史笔记无 CTA）
  tone           ← ""
content_plan:
  selected_topic  ← ""
  content_angle   ← ""
  target_audience ← ""
  content_type    ← note.content_type or "note"
visual_plan:
  image_urls    ← [note.cover_url] if cover_url else []   # 新字段
  cover_prompt  ← ""（历史无生成 prompt）
  image_count   ← 1 if cover_url else 0
  image_prompts ← []
  layout_style  ← ""
  color_palette ← []
```

缺口：content_plan 三个字段空、visual_plan 无 prompt/layout。evaluator prompt 会以"无内容"处理这些段，LLM 自行判断。summary 里可标注"历史笔记缺生成侧元数据，visual/image_quality 维度为参考分"——但这是 LLM 行为，不强约束。

## 实现清单

### 后端
- `backend/agents/evaluator.py`：`execute` 读 `visual_plan.image_urls`，传入 prompt（新槽位 `{image_urls}`）
- `backend/config/prompts/evaluator.yaml`：user_template 视觉段加 `图片URL：{image_urls}`
- `backend/api/routes/evaluation.py`：
  - 新增 `POST /note`：读 note → 构造 eval_state（新增 `_build_note_eval_state`，仿 free.py `_build_eval_state`）→ 调 `_evaluator`
  - 复用现有 `_evaluator` 实例与 `EvaluatorAgent`
- 测试：`tests/unit/api/test_evaluation_note.py`（note→state 映射 + 端点契约，mock evaluator）

### 前端
- `frontend/src/api/evaluation.ts`：加 `evaluateNote(accountId, noteId)` → `POST /evaluation/note`
- `frontend/src/components/settings/CreatorNoteQualityPanel.vue`：
  - 现有 analyzer quality section 保留
  - 新增 RQGM evaluation section（复用 EvaluationView 的展示块结构：总分+decision+雷达+维度+hints）
  - 触发：选中 note 时同时拉 quality analyzer + RQGM 评估（或按需触发按钮，避免每次选中都跑 LLM）
- `EvaluationRadar` 组件直接复用
- 测试：`frontend/tests/components/CreatorNoteQualityPanel.spec.ts` 扩展

### 触发时机决策点（待实现时定）
RQGM 评估跑 LLM，有延迟/成本。选中即跑 vs 按钮触发。倾向：选中 note 后显示"RQGM 评估"按钮，点击才跑，避免列表切换时连跑 LLM。

## 非目标
- 不换 evaluator 模型为多模态（预留，不在本 PR）
- 不删旧 quality analyzer（并排保留）
- 不给历史笔记建 thread / 走完整 workflow
- 不改 `/evaluation/run/{thread_id}` 现有逻辑

## 风险
- astron 纯文本，image_urls 只能文本告知，visual/image_quality 维度仍偏参考分——接受
- note 无 niche 字段，需从 account 配置读；缺省 "母婴" 可能影响 audience 维度——接受
- 前端每次选中跑 LLM 有延迟——用按钮触发缓解
