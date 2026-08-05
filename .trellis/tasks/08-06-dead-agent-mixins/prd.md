# 删除死 agent mixins 目录

## 背景

`backend/agents/mixins/` 3 个 mixin（RetryMixin/ValidationMixin/MemoryMixin）0 生产消费：
- 14 个 agent 全继承 `BaseAgent(ABC)`，**0 个继承任何 mixin**（grep 确认）
- `BaseAgent` 自带 retry（`_llm_ainvoke`）、memory recall（`_recall_memory`）、validation 在 state reducer / agent 内部
- mixin 是 BaseAgent 的平行替代实现，从未进入继承链

## 死代码清单

- `backend/agents/mixins/__init__.py` — 导出 3 mixin（0 外部 import 此包）
- `backend/agents/mixins/retry_mixin.py` — RetryMixin (execute_with_retry / _async)
- `backend/agents/mixins/validation_mixin.py` — ValidationMixin (validate_state_update)
- `backend/agents/mixins/memory_mixin.py` — MemoryMixin (recall_context，被 BaseAgent._recall_memory 取代)
- `tests/test_mixins.py` — 测 mixin 自身（MockAgent 继承），随 mixin 删

## 保留

- `BaseAgent` 自带 `_llm_ainvoke`（retry）/ `_recall_memory` / validation — 不受影响

## AC

1. 删 `backend/agents/mixins/` 整目录 + `tests/test_mixins.py`
2. `ruff check .` + `mypy backend` + 全量 pytest 全绿
3. 14 agent 不受影响

## 风险

低。0 生产消费（grep + 继承链双重确认）。mixin 是从未接入的抽象层，YAGNI 删。
