# fix(typing): 修复 mypy 2.3 下的 benchmark 双写类型错误（票 5bk）

> CI 的 `mypy` 作业对 `backend` 跑 strict 检查（`python_version = "3.11"`，干净安装、
> 不装 numpy）。本次在本地用 mypy 2.3.0 复核发现 `backend/memory/creative.py` 的
> benchmark store 双写传 `NicheBenchmark`（TypedDict）给
> `BaseStore.aput(value=dict)`，在较新 mypy/langgraph 类型下报 `arg-type`；
> 既有 `# type: ignore[union-attr]` 不覆盖它。这会让 CI mypy 失败（与本次迁移无关，
> 属预存问题）；顺手修复并复核整体类型面。

## 1. 已核实的事实

| 事实 | 证据 |
|---|---|
| CI 跑 `mypy backend`（strict） | `.github/workflows/ci.yml` 的 mypy 作业 |
| `aput` 的 `value` 期望 `dict[str, Any]`，`NicheBenchmark` 是 TypedDict | `backend/memory/creative.py:360`；本地 mypy 2.3.0 报 `arg-type` |
| 既有 ignore 只覆盖 `union-attr` | 同址注释 |
| 本地 `mypy backend` 被 numpy 2.5 stub 的 PEP 695 `type` 语句挡住（target 3.11） | 本地环境；仓库未声明 numpy 依赖 |
| `mypy --python-version 3.12 backend` 可绕开该 stub 语法错误 | 本地实测 |

## 2. 决定（locked）

1. `value=dict(benchmark)`：运行时等价（TypedDict 本就是 dict，复制一份），仅把类型收窄为
   `dict[str, Any]`；不改任何行为/存储内容语义。
2. 不引入 mypy override 去"忽略"numpy（实测 `follow_imports=skip` 并不能绕过 stub 语法
   解析，加了也无效、只会误导）；本地以 `--python-version 3.12` 复核，CI 干净环境按配置
   跑 3.11 目标。
3. 不为这行修改变更测试断言；跑 memory 套件 + 全量确认无行为漂移。

## 3. 结果（2026-11-01）

- [x] creative.py 双写 value 改 `dict(benchmark)`
- [x] `mypy --python-version 3.12 backend`：**Success: no issues found in 262 source files**
- [x] memory 套件 339 passed；全量结果见 notes
- [x] pyproject 未加无效 override（复核后已还原，无 diff）

## 4. 不做什么

- 不改 CI 配置/mypy 版本；不处理 numpy stub 的本地环境限制（非仓库依赖）。
