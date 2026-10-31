# 清理不可达路由 should_brief_or_optimize（票 5aw）

> B 类裁定（用户 2026-10-31 拍板：处理“去留”）。决定：**删除**这个不可达的公开路由，
> 连同 wiring 表的豁免与 planning.md 的登记行。理由：它自登记起就没有调用者，图从
> `viral_matcher` 走普通边去 `blogger_scout`；保留一个“写好了但永远不跑”的路由是把
> 未验证行为伪装成能力。删除后 `should_optimize`（`shooting_planner_router` 的 helper）
> 保留不动。

## 1. 现状（已核实）

- `backend/graph/routers.py:453` `should_brief_or_optimize(state) -> Literal["shooting_planner","__end__"]`；
  全仓**零调用**（`tests/unit/graph/test_wiring_registry.py:257` 断言 routers.py 里恰好只出现
  它自己的定义一次；`ROUTERS_WITHOUT_AN_EDGE` 含它）。
- `backend/graph/wiring.py:331-349`：注释解释它与 `should_optimize` 的区别，frozenset
  `{"should_optimize", "should_brief_or_optimize"}`。
- `docs/planning.md` §4「登记未修」第 1 行登记了它；`tests/unit/scripts/test_planning_claims.py`
  重算 planning.md 的 claim 块（改动后要同步数值，若 claim 定义涉及它）。

## 2. 要求

1. 删除 `should_brief_or_optimize` 函数；`ROUTERS_WITHOUT_AN_EDGE` 只留 `{"should_optimize"}`；
   wiring.py 的注释改成只解释 `should_optimize`（保留“注册而非删除”的理由，但只说一个成员）。
2. `tests/unit/graph/test_wiring_registry.py`：删掉针对 `should_brief_or_optimize` 的反向断言，
   保留/修正表成员断言；若存在“已知未接路由”快照，改成只有一个成员。
3. `docs/planning.md` §4 第 1 行改为「已结（票 5aw）：删除不可达路由」并从“未修”列表移除
   （或标注 resolved，按该文档自身格式）；若 claim 块数值变化，按 `test_planning_claims.py` 重算更新。
4. `grep -rn "should_brief_or_optimize"` 只剩历史记录（planning/task 归档可保留文字说明）。
5. `ruff check`/`format` 绿；`pytest tests/unit/graph/test_wiring_registry.py tests/unit/scripts/test_planning_claims.py` 绿。

## 3. 不做什么

- 不动 `should_optimize`（它是 `shooting_planner_router` 的 helper）。
- 不给 brief/optimize 补边（那是产品/图设计决定，不在本票）。
- 不改其它路由与边。

## 4. 结果（2026-10-31）

- [x] `should_brief_or_optimize` 删除；`ROUTERS_WITHOUT_AN_EDGE` 只剩 `should_optimize`（字面快照断言钉住）
- [x] wiring.py 注释只解释 `should_optimize`，保留“注册而非删除/接上必须来删豁免”的理由
- [x] `docs/planning.md` §4 原第 1 行移除、其余重新编号，新增“已结（票 5aw）”段落；claim `routers_without_an_edge` 同步为 `should_optimize`
- [x] 全仓引用只剩 planning.md 的历史说明；`tests/unit/graph` 266 passed；planning claims 重算绿；ruff/format 绿

