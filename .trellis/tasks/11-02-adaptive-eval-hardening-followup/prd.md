# fix(eval): 单一预算常量 + 未列出 JSON 严格化 + 无盐提示 + 路线图同步（票 5cl）

> 验证轮顺手修的三处小问题 + 一处文档同步。都不是新功能，都是"两处真相"或"检查太窄"
> 这类会随时间长歪的地方。

## 1. 交付

| 位置 | 变化 |
|---|---|
| `scripts/eval/plan_l3.py` | 删掉自带的 `APPROVED_MAX_CALLS = 199`，改为 `from judge import APPROVED_MAX_CALLS`（同目录、sys.path 已设）——预算上限只剩一个来源，裁判与计划的 199 不会漂移 |
| `scripts/eval/run_gate.py` | 未列出文件检查从 `fixture-*.json` 扩到目录内所有 `*.json`（`fixture_rogue.json` 这类下划线变体、手工拷贝的 `fixture 1.json` 都会红）；无盐语料的 detail 始终标注 `pseudonyms unsalted (sha256)` |
| `docs/agent-os-upgrade-2026q4.md` | 路线图 10 行补齐 5cd–5ck 与 E4 状态；结论段从"E1–E3 与变体示例"改为"E1–E3、变体示例与 E4 裁判/预算护栏/计划门闸全部落地，独立审查问题已修；live 仍 external-only" |
| 测试 | gate：未列出 JSON 用下划线变体钉住；无盐提示断言；plan_l3 测试不受影响（常量来源变化对行为无影响） |

## 2. 为什么

- **单一来源**：`judge.py` 与 `plan_l3.py` 各写一个 199，改一处忘另一处就会让"授权上限"
  和"执行护栏"不一致；审查已指出这类"两处真相"是风险的温床。
- **检查范围**：`fixture-*.json` 的 glob 漏掉 `fixture_rogue.json`；语料目录里的任何
  未登记 JSON 都是"未计入证据"，应一律红。
- **无盐可见**：加盐是可选的（部署侧密钥），但不加盐是一个真实弱点，gate 每次都应把它
  写在结果里，而不是只在抽取时打印一次警告。

## 3. 验证

- `test_eval_gate.py`：25 passed（含下划线变体红、无盐提示）
- `test_eval_plan_l3.py`：13 passed
- `tests/unit/scripts`：177 passed
- docs/claim 门禁、全量 pytest、CI 见 journal

## 4. 不做什么

- 不把"无盐"升级成阻断（本地语料可接受，部署侧应设密钥；文档与 runbook 已建议）；
- 不改 gate 的 report/block 默认姿态。
