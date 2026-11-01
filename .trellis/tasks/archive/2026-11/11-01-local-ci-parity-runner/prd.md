# chore(ci): 本地 CI 等价检查脚本 scripts/ci_local.py（票 5bw）

> 动因：票 5bv 的 mypy 阻断是**直到推送前复核才被发现**的——CI 的九个作业里，本地
> 没有一条命令能一次跑完。本票提供一个诚实的本地等价运行器：能跑的真跑、不能用
> 环境理由跳过、沙箱怪癖写成代码而不是再踩一遍。

## 1. 已核实的事实

| 事实 | 证据 |
|---|---|
| CI 有 9 个作业：lint-format、mypy、test、context-baseline、harness-benchmarks、tool-runtime-gate、compliance-gate、omp-typecheck、frontend | `.github/workflows/ci.yml` |
| `ruff format --check .` 在 Windows mixed-CRLF checkout 上产生假阳性 | 票 5bj 的复核过程 |
| `mypy backend` 在本地因 numpy 2.5 stub 的 PEP 695 语法（target 3.11）失败，CI 无 numpy | 票 5bk/5bv |
| `tempfile.mkdtemp`（0700）目录在沙箱内不可写；显式 `mkdir(0o777)` 可写 | 本轮实测 |
| 进程管道受沙箱限制；文件重定向不受限 | 5bq 轮的 Node EPERM 记录 + 本轮 `_run` 实现 |
| frontend `npm install` 在沙箱内 EPERM（-4048）；OMP 扩展用工作区 npm cache 可以装成功 | 本轮实测 |

## 2. 交付

`scripts/ci_local.py`：
- 作业：`lint`、`format`、`mypy`、`gates`、`tests`、`frontend`、`omp`；
- `--list` 列出作业；`--only a,b` 选择；`--skip-tests` 跳过全量；
- **format**：复制 681 个 tracked `.py` 到工作区临时目录并统一 LF + 复制 `pyproject.toml`，
  在该树上跑 `ruff format --check`，避免 CRLF 假阳性；临时目录用 `mkdir(0o777)` 创建、
  尽力清理（残留已被 `.ci-local-*/` gitignore）；
- **mypy**：先按 CI 口径跑；仅当输出匹配 numpy stub 语法错误时用 `--python-version 3.12`
  重试并在摘要里写明原因；
- **gates**：context-compiler baseline / harness benchmarks / tool-runtime gate /
  compliance gate 四个脚本；
- 子进程输出走文件重定向（不用 pipe），兼容沙箱；
- **SKIP 是显式的**：frontend/omp 缺 `node_modules`、npm 不可用时给出原因，不冒充 PASS；
- 任何 FAIL 退出码 1，`--only` 未知作业退出码 2。

配套：
- `tests/unit/scripts/test_ci_local.py`：5 个用例（job 列表、未知 `--only` 用法错误、
  `--skip-tests` 语义、`_tail` 截断、tracked 文件列表）；
- `CLAUDE.md` Development Commands 增加 `python scripts/ci_local.py`；
- `.gitignore` 增加 `.ci-local-*/`。

## 3. 验证

- `python scripts/ci_local.py --only lint,format,mypy,gates,omp` →
  **PASS lint / PASS format（681 files）/ PASS mypy / PASS gates / PASS omp**；
  frontend 为 SKIP（npm install 被沙箱 EPERM）。
- 新单测 5 passed。
- 全量 pytest 见 notes。

## 4. 结果（2026-11-01）

- [x] 本地可复现 CI 的主要静态门禁
- [x] 5bv 那类"mypy 到推送前才发现"的问题，现在 `python scripts/ci_local.py` 就会红
- [x] 顺带修正两个被 ruff format 指出的文件（`backend/db/creator_agent.py`、
      `tests/unit/agents/test_run_publish.py`，纯格式）

## 5. 不做什么

- 不替代 CI：Postgres parity、frontend vitest、真实浏览器/模型调用仍只能在 CI 或真机跑；
  脚本会明确 SKIP 而不是假装通过。
- 不改 CI 配置；不引入 pre-commit 钩子（保持本票范围）。
