# workflow-risk-fixes

## Goal

修复自由创作/workflow 链路风险评估暴露的 3 个状态处理缺陷：content_strategist ERROR phase 被 ripple_gate 覆盖（高风险）、/recover 对 checkpoint_lost 记录 404（中风险）、OMP free draft create 缺省 niche 变空串（低风险）。#3 drafts post-filter 漏结果用户认可 spec 取舍，本 task 仅加文案明确化（非分页）。

## What I already know

**#1 ERROR 误路由（高风险）**：
- `backend/agents/base.py:217` — agent 异常被捕获，`handle_agent_error` 返回 error state（phase=ERROR），不 raise（stateful retry 设计）。
- `backend/graph/routers.py:419` `content_strategist_router` — **缺 `_check_terminal` guard**，return type 只 `Literal["ripple_finalize", "ripple_gate"]`，无 `"__end__"`。phase=ERROR 时仍路由到 ripple_gate。
- `backend/agents/nodes/ripple_gate.py:21` `_is_ripple_suboptimal` — Ripple 数据缺失时 `viral_prob=1.0, pmf=1.0`（默认不差）→ auto-accept → phase 改 creating。**策略阶段 ERROR 被覆盖**。
- 对照：`ripple_finalize_router`（紧邻）已有 `if terminal := _check_terminal(state): return terminal`。多数 router 都调，唯独 content_strategist_router 漏。

**#2 recover 404（中风险）**：
- `backend/api/routes/workflow.py:829` — `/status` 把 DB running + no task + no checkpoint 标 `checkpoint_lost`/stale，前端展示"可恢复"。
- `backend/api/routes/workflow.py:1290` — `/recover` `graph.aget_state(config)`，无 state → `WorkflowNotFoundError` 404。用户点恢复失败。

**#4 niche 空串（低风险）**：
- `backend/services/omp_bridge.py:1296` — `"niche": arguments.get("niche", "")`，agent 不传 niche 时显式传空串。
- `backend/api/routes/free.py:51` — `FreeDraft.niche: str = Field(default="母婴")`，Pydantic 默认只在字段缺失生效，显式空串覆盖成 ""。
- `_build_eval_state` 的 `draft.get("niche", "母婴")` 防御失效（draft 里是 ""，非缺失）。

## Requirements

### #1 content_strategist_router terminal guard
- `content_strategist_router` 首行加 `if terminal := _check_terminal(state): return terminal`。
- return type 加 `"__end__"`：`Literal["ripple_finalize", "ripple_gate", "__end__"]`。
- 补 ERROR phase 单测：phase=ERROR → router 返回 "__end__"（不到 ripple_gate）。

### #2 recover 对 checkpoint_lost 返回诊断
- `/recover` 对 DB 有 running/stale row 但 `aget_state` 无 checkpoint 的情况，不 404，返回明确诊断：
  - `recovered: False`，`status: "checkpoint_lost"`，message 说明"DB 有记录但 LangGraph checkpoint 丢失，无法续跑；建议 /resume restart 重新开始"。
- 实现：recover 前先查 DB row（若 aget_state 无 state），DB running/stale → 诊断响应；DB 无 row → 仍 404（真不存在）。
- 现有 derive_status 逻辑保留。

### #4 niche 空串回退
- `FreeDraft` 加 validator：niche 空串/None → "母婴"（Pydantic `field_validator` 或 model_post_init）。
- `omp_bridge.py:1296` 同步：`arguments.get("niche") or "母婴"`（防御 + 一致）。
- 影响：评估上下文 niche 不再为空，不影响稳定性。

### #3 drafts 文案明确化（非分页）
- truncated 提示文案补充："filter 仅在最近 100 篇内生效——更老的草稿需先缩小范围"。i18n 中英。
- 不加分页（BaseStore 无 portable total-count，offset 语义无法实现；YAGNI）。

## Acceptance Criteria

- [ ] phase=ERROR 时 content_strategist_router 返回 "__end__"
- [ ] phase=ERROR 不到达 ripple_gate_node（不触发 auto-accept 改 phase）
- [ ] /recover 对 DB running+no checkpoint 返回 200 + `recovered:False` + `status:checkpoint_lost` 诊断（非 404）
- [ ] /recover 对真不存在 thread 仍 404
- [ ] FreeDraft(niche="") → niche=="母婴"
- [ ] FreeDraft(niche="fashion") → niche=="fashion"（不改非空值）
- [ ] omp_bridge xhs_free_draft_create 不传 niche 时后端收到 "母婴"
- [ ] /drafts truncated 文案含 filter 限定说明
- [ ] mypy backend 绿 + ruff check/format 绿 + 全量 pytest 绿

## Definition of Done

- 3 个修复 + 各自测试
- spec 同步（free-creation niche validator、workflow recover 诊断、graph router terminal guard 约定）
- pre-push 三连绿

## Technical Approach

**#1**：最小 diff——照 `ripple_finalize_router` 模式加 guard。测试：构造 phase=ERROR state，assert router 返回 "__end__"。

**#2**：recover 路径在 `aget_state` 无 state 时，不直接 raise，先查 DB。需看 recover 是否已有 DB row 访问。最小实现：aget_state 无 state → 查 DB row by thread_id → 若 running/stale → 诊断 200；否则 WorkflowNotFoundError。message 指向 /resume restart。

**#4**：FreeDraft `field_validator(mode="after")` strip + 空串回退 "母婴"。bridge 同步 `or "母婴"`。

**#3**：i18n draftsTruncated 文案扩展。

## Out of Scope

- 真正分页/offset（BaseStore 无 portable total-count）
- content_strategist 之外其他 router 审计（用户只点名 content_strategist_router；其他多数已有 guard）
- Ripple 长任务/真实 CDP 发布/容器重启 checkpoint 恢复（真实环境，需独立验证场景）

## Technical Notes

- `backend/graph/routers.py:419` content_strategist_router（修）
- `backend/graph/routers.py:11` _check_terminal（复用）
- `backend/api/routes/workflow.py:829` status checkpoint_lost + `:1290` recover（修）
- `backend/api/routes/free.py:51` FreeDraft niche validator（修）
- `backend/services/omp_bridge.py:1296` niche default（修）
- 测试：`tests/unit/graph/test_routers.py`（或同等）、`tests/unit/api/test_workflow_routes.py`、`tests/unit/api/test_free_routes.py`
- pre-push 三连 [[pre-push-run-format-and-full-mypy]] [[pre-push-run-full-pytest-not-just-changed]]
- 从 main 新建分支 [[separate-pr-per-feature]]
