# feat(eval): P3/E3 离线 A/B 门禁——默认只报告，`--fail-on-red` 可选（票 5cf）

> 提案 E3 要求「跑 L1/L2 + 阈值判定，接入 ci_local/CI」。但问题 5（变体能否改默认）
> 与问题 6（评测红是否阻断合并）仍未拍板，因此本票按**安全姿态**落地：默认 report-only、
> 变体只能显式注入、绝不改生产默认。拍板后改默认或改门禁强度都只是换开关。

## 1. 交付

| 文件 | 作用 |
|---|---|
| `scripts/eval/run_gate.py` | 四项离线检查 + `GateReport`（JSON 可序列化）+ CLI |
| `tests/unit/scripts/test_eval_gate.py` | 13 个用例 |
| `scripts/ci_local.py` | 新 job `eval-gate`：无 `.eval-fixtures/` 时显式 SKIP，有则运行 |
| `tests/unit/scripts/test_ci_local.py` | 补 2 个用例（SKIP / 运行） |
| `docs/adaptive-harness-eval-plan.md` §6.7 | 记录 E3 与两个未拍板问题的安全姿态 |
| `CLAUDE.md` | 开发命令加 E1/E3 两条 |

## 2. 检查与判定

| 检查 | 通过 | 红 | 跳过 |
|---|---|---|---|
| `corpus` | manifest schema 匹配、每文件 sha256 匹配、fixture 自身 `state_sha256` 重算一致 | manifest 缺失/不解析/schema 不符、文件缺失、哈希不符 | 目录不存在（提示先跑抽取器） |
| `policy` | 快照键恰为四决策、每个 TaskType 非空路由、可 JSON 序列化 | describe 抛错、键缺失、空路由、不可序列化 | — |
| `variant` | 显式注入且能产出四决策快照 | 变体坏（空路由/describe 抛错） | 未提供 `--variant` |
| `benchmarks` | F1/F2/F4 存在且全过、无任何 FAIL | 必需检查缺失或任一 FAIL | `--skip-benchmarks` |

- **变体 diff 是信息不是红**：A/B 的目的就是差异；`diff_snapshots` 只列出变化类别。
- **缺口可见**：F5/F7/F8 仍 SKIP 时在 detail 里列出；它们将来实现成 PASS 不算失败。

## 3. 门禁强度与变体边界（未拍板部分的安全默认）

- 默认 `mode=report`：红也返回 0；`--fail-on-red` 才返回 1（CLI 测试钉住两个姿态）。
- 变体只能通过 `--variant module:factory` 注入，脚本从不修改生产默认值。
- 因此本票不回答「是否允许改默认路由」「红是否阻断合并」——它让这两个答案成为开关，
  而不是隐藏假设。

## 4. 验证

- `tests/unit/scripts/test_eval_gate.py`：13 passed；
- `tests/unit/scripts/test_ci_local.py`：补用例通过；
- `python scripts/eval/run_gate.py`：corpus SKIP（本 checkout 无 `.eval-fixtures/`）、
  policy PASS、benchmarks PASS、mode=report、exit 0；
- docs/claim 门禁与全量 pytest 见 notes。

## 5. 不做什么

- 不做 L3 端到端（需预算与真实账号）；不接 GitHub workflow（本地语料无法进 CI）；
- 不改生产默认路由、不训练模型、不影响审批/账本语义。
