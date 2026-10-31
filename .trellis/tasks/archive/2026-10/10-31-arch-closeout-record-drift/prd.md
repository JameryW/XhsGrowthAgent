# 架构收口：历史收口记录纠偏 + 注释旧措辞（票 5ap）

> 来源：核验（本轮前序）确认的两处 **C 类文档滞后**：归档记录与被改代码的注释
> 仍在声称早前状态。两者都不改行为，只让记录追上代码。

## 1. 目标

1. `.trellis/tasks/archive/2026-09/09-11-runtime-upgrade/task.json` 的 notes 里
   “EIGHT REGISTERED ITEMS, NOT FIXED” 已部分过时：(1) 两条修复路径的租约由
   #635/#636 关闭、(6) ripple-retry 直调 RippleService 由票 5p #709 关闭；
   (2)(4)(5)(7)(8) 仍是记录在案的 B 类（裁决 + 触发条件 / 钉住的约束 / 设计裁定）。
   追加一条 dated CORRECTION，**不改原文**（沿用该文件既有的 CORRECTION 先例）。
2. `backend/memory/promotion_observations.py` 的 module docstring 仍写
   “plays/materials 的目标命名空间未裁决（PRD §9）”；PRD §9 六问已全部关闭
   （票 5y/5z/5aa/5ab/5ac），实际状态是“未接 promote 目标 ns，属产品裁决”。
   订正措辞。

## 2. 已核实的事实

| 事实 | 证据 |
|---|---|
| (1) 两条修复路径已持共享租约 | `backend/api/routes/_wf_actions.py` 两处 `async with _execution_lease`；`tests/unit/api/test_repair_paths_take_the_lease.py` |
| (6) ripple-retry 已走 Gateway | `_wf_actions.py` 的 `gateway.invoke("ripple.predict_spread"/"validate_pmf")`；`docs/tool-runtime.md` 三条残留全解决（票 5p #709） |
| (2)(4)(5)(7)(8) 仍开放 | `docs/publish-action-protocol.md`、`tests/unit/graph/test_wiring_registry.py`、`TestTheTwoParsersCannotBeMerged`、`docs/outcome-learning.md` |
| PRD §9 六问已关闭 | `.trellis/tasks/archive/2026-10/10-21-memory-promotion-pipeline/prd.md` §9；`docs/memory-promotion.md` §12 |
| 只有 style 在机晋升范围内 | `backend/memory/promotion_observations.py` 的实现与 `promotion_ttl.py` 常量表（唯一目标 ns = `strategy_notes`） |

## 3. 要求

1. 归档 task.json：在 notes 末尾追加一条 dated CORRECTION（英文，与该文件语言一致），
   列出“已关闭的两项 + 仍开放的六项（含 (3) 已回撤）”，并声明原文保持原样、未改代码。
2. `promotion_observations.py` docstring：把 “has not been decided (PRD §9)” 改为
   “是产品裁决；PRD §9 六问已关闭”，不改变模块行为。
3. 验证：`pytest tests/unit/memory`（含 promotion observations 相关）与
   `tests/unit/scripts/test_docs_citations.py` 可跑的语料检查绿；
   `python -cjson.load` 校验归档 task.json 仍是合法 JSON。

## 4. 验收

- [x] 归档 task.json 仍是合法 JSON，notes 含 “CORRECTION 2 (2026-10-31”
- [x] 原文未被改写（旧 CORRECTION 段落逐字仍在；已用 json load + 子串断言核对）
- [x] promotion_observations docstring 不再点名 “PRD §9 未裁决”
- [x] memory 相关测试绿（335 passed，4 个 tmp_path ERROR 为沙箱环境性）；ruff/format 绿

## 5. 不做什么

- 不改任何生产行为/契约；不重写归档历史原文。
- 不处理 (2)(4)(5)(7)(8) 本身（B 类，需裁决/触发条件）。
