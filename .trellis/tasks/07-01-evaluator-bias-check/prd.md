# evaluator bias_check 语义自洽修复

## Goal

修复评估器 `bias_check` 维度在 prompt 定义与代码假设之间的语义矛盾，使对抗偏倚校准方向正确（论文 arxiv 2606.26294 RQGM 的核心维度）。当前 epoch 演化方向反了——面板越宽松反而被演化得更宽松，形成正反馈恶化。

## What I already know

* 评估器骨架完整：6 维 judge 面板 + DB 权重 + 训练样本回流（analyst backfill_engagement）+ 在线训练（train_weights）+ prompt epoch 协同演化（next_severity/avg_bias_score/create_epoch）。
* **矛盾点已验证**（3 处）：
  * prompt (evaluator.yaml:14-15) 定义 `bias_check.score` = "严苛性校准建议分，**越高越无需调整**"。
  * `_compute_overall` (evaluator.py:251)：`score < 60` → 下调 overall（巧合对：低分=需调整=偏倚）。
  * `next_severity` (evaluator_config.py:597-599)：`avg ≥ 75` → "panel lenient" → tighten；`avg ≤ 45` → "panel harsh" → relax。**按 prompt 语义，高分=无需调整=面板已够严应保持/relax，代码却 tighten；低分=需大幅调整=面板偏宽松应 tighten，代码却 relax。方向反了。**
* epoch 演化是正反馈恶化：面板宽松→bias_check 低分→代码判"过严"→relax→更宽松。
* 现有训练样本数据假设：bias_check.score 语义未在样本里被显式标注，迁移风险低。

## Assumptions (temporary)

* 三处代码假设（"高分=偏倚少/面板严，低分=偏倚多/面板宽松"）是正确意图，prompt 措辞是误写。
* 修法是统一语义，不是改算法。

## Open Questions

*（已全部收敛 — 默认采用推荐方案推进）*

## Requirements

* `bias_check` 维度拆为两个字段语义：
  - `score`：保留 prompt 原意"严苛性校准建议分"（越高越无需调整）。
  - 新增 `bias_severity`（0-100）：检测到的偏倚严重度，越高越糟。驱动 overall 下调 + epoch 演化（tenden tighten）。
* epoch 演化方向正确：`avg bias_severity` 高 → 面板宽松 → tighten；低 → 面板严 → relax。
* 向后兼容：旧样本无 `bias_severity` 时，回退 `bias_severity = 100 - score` 反推（校准建议分高=偏倚少）。

## Decision (ADR-lite)

**Context**: prompt 定义 bias_check.score 为"校准建议分（越高越无需调整）"，但代码三处假设相反，导致 epoch 演化方向反、正反馈恶化。
**Decision**: Approach C — 不动 6 维结构，给 bias_check 的 DimensionScore 加可选字段 `bias_severity`（偏倚严重度）。`score` 保留原语义，`bias_severity` 驱动 overall 下调 + epoch 演化。旧样本回退用 `100 - score` 反推，不写迁移脚本。
**Consequences**: 雷达图不变、向后兼容旧样本；需同步前端类型 + omp TS 类型；反推有近似误差但保证演化信号连续。

## Acceptance Criteria

* [ ] prompt yaml 输出结构含 bias_check 的 `bias_severity` 字段，语义说明清晰。
* [ ] `_compute_overall` 用 `bias_severity`（高→下调），不再误用 `score`。
* [ ] `avg_bias_score` 改读 `bias_severity`；旧样本无字段时 `100 - score` 反推。
* [ ] `next_severity` band 方向正确：高 severity → tighten，低 → relax。
* [ ] DimensionScore schema（backend state + frontend + omp TS）加可选 `bias_severity`。
* [ ] 测试：新样本 bias_severity 驱动 overall 下调 + epoch tighten；旧样本反推回退路径。
* [ ] 现有 evaluator 测试不破（test_evaluator.py / test_evaluator_config.py）。
* [ ] ruff/mypy 绿。

## Acceptance Criteria (evolving)

* [ ] 有测试覆盖：高分 bias_check 不触发 overall 下调 / 触发 epoch relax；低分触发 overall 下调 / 触发 epoch tighten。
* [ ] 现有 evaluator 测试不破（test_evaluator.py）。
* [ ] ruff/mypy 绿。

## Definition of Done (team quality bar)

* Tests added/updated (unit/integration where appropriate)
* Lint / typecheck / CI green
* Docs/notes updated if behavior changes (prompt yaml 注释 + database-guidelines 如涉及)

## Out of Scope (explicit)

* 不改 train_weights 的 OLS 算法（只动 bias_check 语义相关）。
* 不改 6 维权重默认值。
* 不重写 prompt 整体结构，仅修 bias_check 段语义。

## Technical Notes

* 涉及文件：`backend/config/prompts/evaluator.yaml`、`backend/agents/evaluator.py`、`backend/db/evaluator_config.py`（next_severity/avg_bias_score 注释与 band 方向）。
* epoch 演化信号 `avg_bias_score` 读的是 dimensions 里的 bias_check.score，迁移时需同步。
