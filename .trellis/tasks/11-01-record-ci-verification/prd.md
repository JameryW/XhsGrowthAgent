# docs: 记录推送与 CI 全绿证据（票 5bz）

> 分支 B 收口与本地工具链完成时，仓库文档只写了"本地验证过"。真实环境的验证发生在
> 2026-11-01 推送之后：CI 两次运行、10 个作业全绿。把这份证据写进架构记录，避免后续
> 会话重复验证，或误以为改动"只在本地跑过"。

## 1. 事实

| 事实 | 证据 |
|---|---|
| 102 个本地提交 + journal 提交已推送 `origin/main` | `546c99c0..cccb0041`、`cccb0041..2d614709` |
| CI run `41306901460`（commit `cccb0041`）10 作业 success | `gh run view 41306901460` |
| CI run `41307361407`（commit `2d614709`）10 作业 success | `gh run view 41307361407` |
| 其中包含本地无法执行的三项 | mypy（无 numpy 环境 strict）、Test py3.11/3.12（Postgres service parity）、Frontend（vitest/type-check/i18n）与 OMP tsc |

## 2. 交付

- `docs/publish-action-protocol.md`：分支 B 收口段记录 commit/run 与"10 作业全绿"；
- `docs/agent-os-upgrade-2026q4.md`：§9.2 分支 B 行补充 CI 验证证据，结论段改为
  "完成并推送、CI 10 作业全绿"。

## 3. 验证

- `tests/unit/scripts`（含 claim/锚点/citations）：**108 passed**
- `ruff check` 绿；`scripts/ci_local.py --only format` PASS
- 纯文档改动：未重跑全量 pytest（由推送后的 CI 覆盖）

## 4. 不做什么

- 不改代码、不新增 claim；不改 CI 配置。
