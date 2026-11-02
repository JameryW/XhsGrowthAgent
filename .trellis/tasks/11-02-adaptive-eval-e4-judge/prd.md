# feat(eval): E4 质量裁判（LLM-as-judge）+ 199 调用预算护栏（票 5ch）

> 用户 2026-11-02 拍板三件事：**允许 LLM-as-judge**、**每轮 <200 次模型调用**、
> L3 用**测试账号**。本票落地裁判与预算护栏——E4 中唯一能离线验证的部分；
> live 端到端执行仍 external-only（需平台凭据与账号窗口）。

## 1. 交付

| 组件 | 行为 |
|---|---|
| `JudgeScores` | 五维 0-10 整数（copywriting/visual/compliance/reach/audience，沿用 evaluator 词汇）+ `rationale` + `bias_warning`；`overall` = 均值 |
| `build_judge_prompt` | 确定性 system+human 消息：只输出 JSON、禁止复述原文；携带 niche/title/body/visual_summary |
| `parse_judge_output` | 容忍 ```json 围栏与前后散文；缺维度/超范围/非 JSON → `JudgeOutputError`（带预览） |
| `JudgeBudget` | 默认 `max_calls=199`（"<200" 直译）；`consume()` **先扣费后调用**；超限抛 `JudgeBudgetExceededError` |
| `judge_content(model, ...)` | 一次判定一次调用；坏输出也计入该次调用（账目不乐观） |

## 2. 为什么先扣费

若先调用再记账，模型超时/进程崩溃会让"已用次数"少记一次，下一次重跑就可能突破 200 的
授权额度。测试钉住：预算耗尽时**模型一次都不会被调用**（`model.calls == 0`）。

## 3. 验证

- `tests/unit/scripts/test_eval_judge.py`：**11 passed**（假模型、无网络、无 key）：
  提示词确定性、围栏/散文解析、缺维度拒绝、超范围拒绝、非 JSON 拒绝、199 上限、
  预算耗尽不调用模型、坏输出仍扣费；
- docs/claim 门禁与全量 pytest 见 notes；
- ruff 绿。

## 4. 明确 external-only（不伪造）

- 真实 workflow 的 live 调用、测试账号登录态/凭据、平台验收窗口；
- `judge_content` 接受任意 chat model，部署侧传入 `get_model(TaskType.EVALUATION)` 即可；
- 本票不接线生产、不改默认路由、不写任何凭据。

## 5. 不做什么

- 不做 live L3 编排（缺平台凭据）；不做双盲人工复核流程（用户选择允许 LLM judge）；
- 不改 E3 门禁默认强度。
