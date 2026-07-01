# 创作质量评估器 agent (基于 arxiv 2606.26294)

## Goal

基于 **Red Queen Gödel Machine (RQGM, arxiv 2606.26294)** 的核心方法——agent-as-a-judge 多评审面板 + 对抗性偏倚纠偏 + 评估器与生成器协同演化——设计并实现一个可评估小红书创作结果质量的「评估器 agent」，集成到现有 LangGraph 工作流（发布前 gate）和 omp 扩展中。

## What I already know

### 论文方法（RQGM）
* **agent-as-a-judge 多评审面板**：多元 judge panel 评估创作，而非单一评分。writer 在多元面板下验收率 1.78–1.86x 提升。
* **对抗性目标纠偏**：baseline reviewer 以 1.91x 人类速率过度接受 AI 内容；RQGM 通过对抗目标发现对 AI/human 同等严苛的评审。
* **协同演化**：grader 与 writer 一起进化，grader ground-truth 准确率高 9%。
* **epoch 机制**：epoch 内评估标准固定（保自改进理论性质），epoch 边界可演化 utility。
* **verifiable metric + judge signal 互补**。

### 代码集成点（已探查）
* 工作流是 `StateGraph`，节点函数在 `backend/agents/nodes/`，agent 类在 `backend/agents/`。
* 已有 gate 节点范式：`review_gate` / `ripple_gate` / `blogger_gate` / `draft_gate` / `choice_gate` / `brief_gate`——节点函数 + `interrupt_before` + 条件路由 (`backend/graph/routers.py`)。
* `review_gate` 接在 `visual_designer` 之后、`publisher` 之前；路由 `review_outcome → publisher | revise_content | END`。
* agent 基类 `BaseAgent`（`backend/agents/base.py`）：`task_type` / `agent_name` / `prompt_file` / `execute(state, store)`；prompt 从 `backend/config/prompts/<agent>.yaml` 加载；模型经 `get_model(task_type)` 路由。
* TaskType 枚举在 `backend/config/models.py`，tool 注册在 `backend/tools/registry.py:_agent_tools`。
* state schema 在 `backend/state/schema.py`（TypedDict + reducers），phase 枚举在 `backend/state/enums.py`。
* omp 扩展在 `backend/omp/extensions/xhsagent-ext/`，把工具暴露给 omp TUI。
* node 封装范式：`NodeResult(result, agent_name).to_dict()` + `EventBusService.emit(...)`（见 `blogger_scout_node`）。

## Assumptions (temporary)

* 评估器作为发布前 gate 节点，接在 `review_gate` 通过后、`publisher` 之前（或并行）。
* MVP 先做 agent-as-a-judge 面板（多维度评分 + 综合判定），对抗偏倚检测和协同演化作为后续 epoch 演进。
* 评估维度面向小红书创作：文案质量、视觉契合、合规性、传播潜力（结合已有 Ripple 预测）。
* 评分结果写入 state（新增 `evaluation_result` 字段），低分走 revise 回路（复用 review_gate 的 revise 路径或新增）。

## Status: 实现完成（PR1+PR2+PR3 全部验证通过）

- ruff check .：All checks passed
- mypy backend：Success, no issues in 146 source files
- pytest tests/unit tests/integration：934 passed
- tsc (omp extension)：no errors

## Decisions (已确认)

* **D1 集成位置**：`review_gate`（人审）通过后、`publisher` 前新增 `evaluator_gate` 节点。人审与 AI 评估分离，两条把关互补。合格→publisher，不合格→revise_content→copywriter。
* **D2 评估维度**：5 维 judge 面板 + 对抗偏倚检测（论文完整版）。
  * 文案质量（标题/正文/标签）
  * 视觉契合（图文匹配/版式）
  * 合规安全（敏感词/平台规则）
  * 传播潜力（融合 Ripple 预测 + 热点匹配）
  * 受众匹配（niche + 记忆系统历史偏好）
  * **对抗偏倚检测 judge**：独立校准面板是否对 AI 生成内容过度宽容（论文 1.91x 纠偏），输出偏倚警示 + 严苛性调整。
* **D3 阈值与回路**：可配置阈值（默认综合分 ≥70 且无硬性合规失败 → pass）；不合格走 `revise_content`→`copywriter`，评估建议作为修订指令写入 state（`evaluation_result.revision_hints`），轻量体现论文"协同演化"。
* **D4 omp 集成**：新增 `xhs_evaluate` 工具（对指定 thread 评估当前创作）+ `evaluation_pending` 查询 + `evaluation_result` 读取，复用现有 `api_client.ts` 范式。

## Open Questions

* （无阻塞——以下由我按推荐方案定，用户可在最终确认时推翻）
  * 阈值默认值（综合分 ≥70，合规为硬否决）。
  * 评估器是否 interrupt（是：作为 gate 中断点，允许用户查看评分后决定继续/修订——与 review_gate 一致范式）。

## Requirements

* 新增 `TaskType.EVALUATION`（`backend/config/models.py`）+ 路由到 `astron-code-latest`（与现有一致）。
* 新增 `EvaluatorAgent`（`backend/agents/evaluator.py`）：6 个 judge 维度（5 维 + 偏倚检测）并行/串行评分，输出 `EvaluationResult`。
* 新增 `backend/config/prompts/evaluator.yaml`（judge 面板系统提示 + 评分 JSON schema）。
* 新增 `evaluator_node`（`backend/agents/nodes/evaluator.py`）+ `evaluator_outcome` 路由（`backend/graph/routers.py`）。
* 接入 `build_graph()`：review_gate approved → evaluator_gate → [publisher | revise_content]。
* state 新增 `evaluation_result: EvaluationResult` 字段（`backend/state/schema.py`）。
* `interrupt_before` 加入 `evaluator_gate`（与 review_gate 一致，可查看评分后决定）。
* API 路由：`GET /evaluation/pending/{thread_id}`、`GET /evaluation/result/{thread_id}`、`POST /evaluation/resume/{thread_id}`（参考 blogger/review 路由范式）。
* omp 扩展：`src/tools/evaluation_pending.ts`、`evaluation_result.ts`、`evaluation_run.ts`（或合并）+ 注册到 `src/index.ts` + `src/commands/xhs.ts`。
* 单元测试：评分逻辑、偏倚检测、路由判定、节点集成。

## Acceptance Criteria

* [ ] `EvaluatorAgent` 对 copy_content + visual_plan + content_plan 输出 6 维分数 + 综合 ContentStatus + revision_hints。
* [ ] 对抗偏倚检测 judge 能识别"对 AI 内容过度宽容"并调整评分（有测试用例）。
* [ ] 工作流经 evaluator_gate 路由：合格→publisher / 不合格→revise_content→copywriter（带 revision_hints）。
* [ ] interrupt_before 含 evaluator_gate，可在评分后恢复。
* [ ] omp `xhs_evaluate` 可对 thread 评估并返回结果。
* [ ] `ruff check` / `mypy backend` / `pytest` 绿；OpenAPI contract 同步（若加路由）。

## Definition of Done

* Tests added（unit + integration）
* ruff / mypy / pytest 绿
* CLAUDE.md 更新（新增 evaluator agent + gate 节点说明）
* Rollout：新 gate 默认可旁路降级（评估失败不阻断发布，log + 降级直通 publisher——安全网）

## Out of Scope

* 真正的协同演化（grader 权重自动训练/epoch 边界演化 utility）——MVP 用固定阈值 + revision_hints 轻量体现，后续 epoch 演进。
* 评估器自身模型微调。
* 前端评估结果可视化页面（先 API + state + omp）。
* 评估历史对比/趋势分析。

## Technical Approach

### 数据结构
```python
class EvaluationResult(TypedDict):
    overall_score: float            # 0-100 加权综合
    dimensions: list[DimensionScore]  # 6 维（含 bias_check）
    decision: ContentStatus         # approved / needs_revision / rejected
    revision_hints: list[str]       # 给 copywriter 的修订指令
    bias_warning: str | None        # 对抗偏倚检测结论
    summary: str
```

### 节点流
```
review_gate(approved) → evaluator_gate(interrupt_before)
  resume → evaluator_outcome:
    overall≥阈值 & 合规通过 → publisher
    else → revise_content(写 revision_hints) → copywriter
```

### judge 面板实现
单次 LLM 调用返回完整 6 维 JSON（避免 6 次串行调用成本；prompt 设计为面板式多维评分）。对抗偏倚检测作为独立一维，prompt 显式要求"检测是否对 AI 生成内容过度宽容"。

## Technical Notes

* 论文：https://arxiv.org/abs/2606.26294 — memory `rqgm-paper-evaluator-method`。
* gate 范式：`backend/agents/nodes/review_gate.py`（极简节点）+ `backend/graph/routers.py:review_outcome`（路由读 state）。
* interrupt_before 当前含 `review_gate, choice_gate, draft_gate`（`builder.py:392`）。
* ContentStatus 复用（`backend/state/enums.py`）。
* omp 工具范式：`src/tools/review_pending.ts` + `src/api_client.ts`。
* 路由恢复范式：`backend/api/routes/blogger.py`（`_is_at_blogger_gate` + Command resume）。
