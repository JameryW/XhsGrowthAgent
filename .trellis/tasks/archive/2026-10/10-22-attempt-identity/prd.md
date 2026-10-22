# Attempt 身份协议（agent-os 矩阵行 2 的 Attempt 缺口）

> 状态：实现中（票 5w）。来源：`docs/agent-os-upgrade-2026q4.md` §2「五实体映射与缺口」——
> Task/Step 有；`Run` 与 `Attempt` 缺。本票只补 **Attempt**：
> 「节点内 `with_retry` 的隐式计数，没有 attempt_id，也没有 attempt 级事件」。

## 1. 目标

给节点内的 LLM 结构化重试一个**有名字、可查询的尝试实体**：

- 每次 `(结构化降级档位 × 重试序号)` 的尝试都有一条 `kind:"attempt"` 事件；
- 事件携带确定性 `attempt_id`、封闭 `outcome` 词表、以及**最少必要**字段；
- 纯观测：不改变重试预算、不改变控制流、不改变 prompt/模型调用；
- 失败写入 best-effort：事件丢失不得让节点失败（既有 telemetry 契约）。

## 2. 不变量

1. **Attempt 与 Effect 不混用**：attempt 记录 LLM 尝试；外部副作用仍由 Effect 账本负责。
2. **数据最小化**：事件不含 prompt、模型输出、原始错误消息文本；只留 `error_class`
   （异常类名）与耗时/档位/序号。
3. **确定性 id**：`attempt_id` 由 `(agent, level, attempt_no, started_at)` 派生
   （sha256 截断），同一 attempt 重发同 id；不同 attempt 必不同 id。
4. **封闭词表**：`succeeded / payload_rejected / semantic_rejected / unreachable`。
   其中 `payload_rejected`（schema 不合法）与 `semantic_rejected`（validator 拒绝）必须分开——
   前者永不可成为结果，后者可能是 advisory 接受。
5. **零行为变更**：`tests/` 全量、context baseline、harness benchmarks 均不得因本票漂移。

## 3. 落点

| 文件 | 变更 |
|---|---|
| `backend/state/attempts.py` | 新纯库：`AttemptOutcome`、`attempt_id`、`attempt_entry` |
| `backend/state/events.py` | 新增 `ATTEMPT_EVENT_KIND = "attempt"` 常量 |
| `backend/db/workflow_events.py` | `EVENT_KINDS` 增 `"attempt"` |
| `backend/agents/base.py` | `_llm_structured` 每次尝试后 append 一条 attempt entry 到既有 perf contextvar；`execute()` 的 drain/emit 路径不变 |
| `docs/agent-os-upgrade-2026q4.md` | §2 Attempt 行改「有」；§3 行 2 文本更新；新增 §5.9 落地记录 |

## 4. 验收

- `tests/unit/state/test_attempts.py`：词表、校验（空 agent/level、序号 <1、负/非有限耗时、
  未知 outcome）、id 确定性与区分度、字段集合恰为白名单、不含内容字段。
- `tests/unit/agents/test_llm_structured.py` 追加：成功 / payload 拒绝 / validator 拒绝 /
  不可达四条路径各产生正确 outcome 的 attempt 事件，且事件与既有 llm/node 条目共存。
- 突变自检：删 attempt 记录、混淆两种拒绝、id 不含尝试序号、耗时负值、字段加内容、
  events 不注册 attempt、常量漂移等，必须全红且是断言红。
- `ruff` / `mypy backend`（仅允许既有 `memory/creative.py:350`）/ 四道本地门 / 全量测试。

## 5. 不做什么

- **不补 Run 实体**（同属行 2 的另一半）：resume/rerun 的 run_id 需要动启动路径与状态，
  单票做会混两件事；行 2 保持「部分」，Run 缺口单独登记。
- **不做 attempt 级重放**：§4.1 的触发条件（出现不经 effect claim 的外部副作用路径）未满足；
  本票只补身份与遥测，不改变"节点内重试会重调 LLM"的事实。
- 不记录 prompt/输出（数据最小化）；不加 DB 表（事件存储已够）。
