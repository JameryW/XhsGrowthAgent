# feat(eval): 变体示例证明 `--variant` 注入链路 + P3 文档进度同步（票 5cg）

> E3 交付了 `--variant module:factory` 的注入路径，但此前没有任何真实变体可加载，
> 这条链路只有单测里的内联类能证明。本票补一个**只改一个决策**的示例变体，并用它把
> 注入 → 快照 → diff 全链路跑通；同时把架构文档里"路线图 10 未启动"的旧状态改掉。

## 1. 交付

| 文件 | 作用 |
|---|---|
| `scripts/eval/variants/route_lighter.py` | 示例变体：`content_analysis` 从 MiMo 路由切到较轻的 `deepseek-v4-flash`（与 POLISH/MOCK_GEN 同类）；**不被生产代码导入**，所以不可能改默认 |
| `tests/unit/scripts/test_eval_gate.py` | +2 用例：真实模块加载后 diff 只含 `models`；CLI `--variant` 注入并输出 `decisions changed: models` |
| `docs/adaptive-harness-eval-plan.md` | 头状态改为 E1/E2/E3 已交付；新增 §6.8（变体示例用法 + E4 三个待拍板项） |
| `docs/agent-os-upgrade-2026q4.md` | §9 路线图 10 从「依赖/未启动」改为「进行中」，列出 5cd/5ce/5cf/5cg 与 E4 阻塞；结论段同步 |

## 2. 验证

```
python scripts/eval/run_gate.py --skip-benchmarks \
    --variant scripts.eval.variants.route_lighter:make_policy
→ [PASS] variant: ...; decisions changed: models
  mode=gate red=False  exit 0
```
diff 只含 `models` 一类，钉住 E3「只报告变化、不把差异当红」的语义。

- `tests/unit/scripts/test_eval_gate.py`：15 passed
- docs/claim 门禁与全量 pytest 见 notes

## 3. 不做什么

- 不接线生产默认（问题 5 未拍板）；不实现 E4 的 live 执行（缺账号/预算/judge 拍板）；
- 不把示例变体包装成"推荐配置"，它只是链路演示。
