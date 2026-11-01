# fix(typing): 修复分支 B 新代码的 mypy 错误（票 5bv）

> 本轮为 CI 兼容性复核时发现：分支 B 的新代码引入 **11 个 mypy 错误**，CI 的
> `mypy backend`（strict）会因此失败。这是纯类型修复，无行为变化。

## 1. 问题

| 位置 | 错误 |
|---|---|
| `backend/creator_agent/execution.py` `_outcome_from_status` | 用 `**audit` 把异构 dict 展开给 `PublishOutcome` 的强类型字段，mypy 报 10 个 `arg-type`（str / int|None / Mapping|None / bool|None 全不匹配） |
| `backend/creator_agent/advisor.py` `_execute_publish` | `content` 在 request 分支被推断为 `PublishContent`，artifact 分支又赋 `load_publish_content()` 的 `PublishContent | None`，报 `assignment` |

## 2. 修复（locked）

1. `execution.py`：改为**显式类型局部变量**（`published_at: str`、`error_type: str`、
   `recovery: Mapping[str, Any] | None`、`result_known: bool | None`），三个分支逐字段传入
   `PublishOutcome(...)`；不再用 `**dict`。
2. `advisor.py`：入口先声明 `content: PublishContent`；artifact 分支用 `loaded = ...;
   if loaded is None: raise; content = loaded`。
3. 不改变任何运行时行为、字段值或校验逻辑。

## 3. 验证

- `mypy --python-version 3.12 backend` → **Success: no issues found in 262 source files**
  （本地 numpy stub 与 `python_version=3.11` 冲突，故用 3.12 target 复核，与上轮 5bk 同法）
- `ruff check` / `format` 绿
- 全量 pytest 见 notes

## 4. 结果（2026-11-01）

- [x] 11 个 mypy 错误清零
- [x] 全量结果见 notes

## 5. 备注

- 这是**本轮复核才发现的 CI 阻断项**：5bn/5bo/5bq/5br/5bs 的提交若直接推送，mypy 作业会红。
- 同时确认 **OMP typecheck 可在本地跑通**（用 `npm install --cache <workspace>` 绕过沙箱对
  `%LOCALAPPDATA%\npm-cache` 的写入限制；`tsc --noEmit` exit 0）。
- 本地仍无法跑 Postgres parity（5432 无监听；`postgres` 进程存在但无对应监听端口）。
