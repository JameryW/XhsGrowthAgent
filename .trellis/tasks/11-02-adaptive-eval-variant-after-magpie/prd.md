# fix(eval): #756 后调整变体示例为逐 phase 预算（票 5cn）

> 远端 #756 把所有 LLM 调用统一到 magpie 网关（`magpie-deepseek-v4.1-flash`）并禁用
> 直连 DeepSeek。E3 的示例变体原本演示"`content_analysis` 换到更轻的直连模型"，现在
> 这个决策**不存在**了；继续保留会变成误导性样例。

## 1. 变化

| 位置 | 变化 |
|---|---|
| `scripts/eval/variants/phase_budget.py` | 新增示例变体：`publishing` 阶段 context budget = 4000，其余继承默认；`make_policy()` 供 `--variant module:factory` 使用 |
| `scripts/eval/variants/route_lighter.py` | 删除（其演示的决策已被 #756 取消） |
| `tests/unit/scripts/test_eval_gate.py` | 真实变体用例改为断言 diff 只含 `context_budgets` 且 `publishing == 4000`、baseline 为 None、`models` 相同；CLI 用例期望 `decisions changed: context_budgets` |
| `docs/adaptive-harness-eval-plan.md` §6.8 | 说明 #756 后为什么不再用换路由演示，并给出新用法与期望输出 |

## 2. 为什么用逐 phase 预算

- 路由已无第二个可选 chat 模型：默认就是 magpie 的唯一上游；
- 逐 phase 预算是 harness 真正拥有的决策，E2 的 `describe()` 已采样
  `context_budget(phase=...)`（5cm 加的 `context_budgets`），因此该变体在 diff 中恰好
  只出现 `context_budgets` 一类，正好继续证明"差异只报告、不当红"；
- 变体仍不被生产导入，零默认行为变化。

## 3. 验证

- `test_eval_gate.py` 29 passed（含真实变体加载与 CLI 注入）；
- 全量 pytest / ruff / mypy 见 journal（本轮 rebase 到 #756 之上，全量回归）。

## 4. 不做什么

- 不创建"第二个 magpie 模型"来维持旧演示（那会引入不存在的路由）；
- 不改生产路由与默认预算。
