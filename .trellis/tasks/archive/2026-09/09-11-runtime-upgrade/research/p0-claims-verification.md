# P0 断言勘察报告（对 2026-09-11 main 分支的逐条验证）

勘察方式：两路 Explore 子代理并行读码。所有断言均对当前代码核实，附 file:line。

## 结论总览

| # | 断言 | 结论 |
|---|------|------|
| 1 | Agent 模块级单例被全部请求共享 | VERIFIED（14 个 node 单例 + 3 个路由级 EvaluatorAgent 单例） |
| 2 | BaseAgent `self._llm_perf_entries` 异步交叉污染 | VERIFIED |
| 3 | EvaluatorAgent `self._weights/_bias_severity` 实例态串扰 | VERIFIED |
| 4 | 两套以上 Retry 体系并存且 LangGraph RetryPolicy 实际失效 | VERIFIED |
| 5 | Publisher 带 RetryPolicy 但异常被吞、无幂等键 | VERIFIED |
| 6 | Memory namespace 拼错静默回退 insights | VERIFIED（现有调用方全部合法，fail-fast 零波及） |
| 7 | 语义索引不可用时 asearch 静默退化为 recency | VERIFIED |
| 8 | Evaluator 失败/降级 → 直通 publisher；revision 上限 → 强制发布 | VERIFIED |
| 9 | creator_agent ActionIntent→Confirm→Execute→Receipt 模型完整且未接入主链 | VERIFIED |
| 10 | Publisher dry-run 双层保护 | VERIFIED |

## 1. Agent 单例

`backend/agents/nodes/` 下 14 个模块级单例：analyst.py:12, blogger_scout.py:12, brief_analyzer.py:13, evaluator.py:27, copywriter.py:12, content_strategist.py:12, trend_scout.py:12, shooting_planner.py:13, publisher.py:12, visual_designer.py:12, orchestrator.py:12, optimization/viral_matcher.py:12, optimization/version_generator.py:12, optimization/content_analyzer.py:12。
另有 3 个路由级：api/routes/free.py:51, evaluation.py:56, review.py:34。
服务端为单进程 async uvicorn（Dockerfile:81 无 --workers；cli/main.py:183），workflow 以 asyncio 后台任务共享同一 event loop（api/routes/_runner.py:35-39, :316）→ 并发交叉真实可发生。

## 2. BaseAgent perf 实例态

- 定义：backend/agents/base.py:41 `self._llm_perf_entries: list = []`
- `_reset_llm_perf()` base.py:88-90，被 13 个 agent 的 execute() 开头调用（如 evaluator.py:150, copywriter.py:38, trend_scout.py:107）
- await 后 append：base.py:71-83；另 base.py:302, 320, 328, 344（`__call__`）；parse_ms 回写 `[-1]`：base.py:158-161

## 3. Evaluator 实例态

backend/agents/evaluator.py:87-88 初始化；:113 `self._weights, self._bias_severity = await asyncio.gather(...)`（由 :186-195 触发）；:134-142 `_build_system_prompt` 消费；:169, :252 降级/覆盖路径消费。并发第二次评估可在 prompt 构建前覆盖 weights。

## 4. Retry 全景

- LangGraph RetryPolicy 定义于 backend/graph/error_handling.py:13-25：trend_scout=3, publisher=3, copywriter/visual_designer/analyst/content_strategist=2, orchestrator/review_gate=1。**builder.py:98,124,130 对 evaluator/brief_analyzer/shooting_planner 调用 get_retry_policy 返回 None（dict 无此键）**。
- 实际失效原因：BaseAgent.__call__ 捕获一切异常并返回（base.py:295-324），注释明说"以 stateful retry 换掉 raise"（base.py:277-282；core/error_handling.py:46-48）。
- Stateful retry：handle_agent_error（backend/core/error_handling.py:36-55）写 phase=ERROR + retry_count+1；路由 should_plan（graph/routers.py:69-98）在 retry_count<2 时重跑 trend_scout（:91），否则 _check_terminal（:12-27）END；orchestrator_router ERROR→END（:48,61）；OrchestratorAgent.execute（agents/orchestrator.py:26-32）retry_count>=3 放弃。
- Model 级：backend/models/retry.py:94-144 `_RetryChatModel`（max 3 + backoff，env XHS_LLM_MAX_RETRIES）。
- 恢复类：POST /resume/{thread_id}（api/routes/workflow.py:1160）、/recover/{thread_id}（:1433-1541，retry_failed/retry_from_last_success/skip_to_next）、/publish-retry/{thread_id}（:2587-2705）。
- 工具内部：omp_bridge.py:887-954 `_retry_http`（429/502-504）；ripple_service.py:468-480 max_retries=3。
- 陈旧注释：services/xhs_publisher.py:352 声称 "XHSClient.publish_post retries up to 3x"，但 xhs_client.py:553-576 并无重试循环。

## 5. Publisher 副作用安全

- publisher 带 RetryPolicy(max_attempts=3)：graph/error_handling.py:16, builder.py:99。
- run_publish 吞掉所有异常转 status="failed"，不 raise：backend/agents/publisher.py:306-318（早退 failed 分支 :192-239）。RetryPolicy 只对 wrapper 侧 raise 生效（nodes/publisher.py:23-31 的 _check_cancelled/event-bus）。
- 无请求侧幂等键/去重。现有防护：dry_run 双检（publisher.py:135-138）；publish-retry 端点拒绝 published/success（workflow.py:2645-2654）+ 并发守卫（:2613-2615）；XHS 风控冷却计数（services/xhs_publisher.py:227-255）；事后对账仅靠 platform_post_id/link_status:"unmatched"（publisher.py:38-61）。

## 6. Memory namespace

backend/agents/base.py:132-138 `_recall_memory` 的 `ns_map.get(namespace, mm.insights_ns)`。合法键 4 个：content_history / audience_preferences / performance_insights / strategy_notes。现有调用方（analyst.py:86, copywriter.py:60,67, content_strategist.py:52, trend_scout.py:129, evaluator.py:192）全部合法 → 改 raise 零波及。ns 属性定义：backend/memory/store.py:42-60。

## 7. 语义检索静默降级

- backend/memory/index.py:181-238 `get_store_index()`：缺 key / provider 不可解析 / embeddings 构建异常 → 返回 None，仅 logger.warning。
- graph/builder.py:394-395, 406-411 以 index=None 建 store → asearch 按 namespace recency 返回（index.py:3 docstring 自证）。
- memory/store.py:103-117, 128-141, 152-165, 176-189 所有 recall_* 以 try/except→warning→[] 吞错。
- 唯一出口 semantic_index_status()（index.py:134-178）仅供 /system/health（api/routes/system.py:264），业务层不可见。
- 注：RetrievalResult 显式 degraded/mode 信号列入 P1（kernel 层），P0 不动。

## 8. Evaluator 质量门失败策略

- 节点失败 pass-through：backend/agents/nodes/evaluator.py:11-12（docstring 自证）、:43-64 合成 `{"decision": None, "status": "degraded"}`。
- 路由：graph/routers.py:141-156，decision 缺省 APPROVED；None/未知 → `return "publisher"`（:156 注释"approved 或未知 → 放行发布"）。
- LLM timeout 亦降级 decision: None（agents/evaluator.py:233-257）；空内容 `_empty_pass()` 伪造 100/APPROVED（:156-179, 660-678）。
- revision 上限强制发布：routers.py:145-153（decision 为 needs_revision/rejected 也 return "publisher"）；上限来源 nodes/revise_content.py:19,36。
- 10 维 judge：9 加权维 + bias_check（agents/evaluator.py:48-58, 73）。**compliance 维已存在且有硬拒绝规则**（:586-595，is_blocking 或 compliance < reject_threshold → REJECTED，权重 0.14）→ fail-closed 收口的现成切面。

## 9. creator_agent Action 模型（拟提升为全局执行协议）

- 模型：backend/creator_agent/models.py — ActionIntentRequest:525, ActionResolution:553, ActionIntent:559（status PENDING_CONFIRMATION:570）, ActionExecutionStatus:576, ActionExecution:583（不可变 receipt）, ActionExecutionReceipt 别名:604。
- 流程：advisor.py plan_action:261-313（幂等键、无副作用）→ resolve_action:321-327（确认不执行）→ execute_action:329-398（要求 CONFIRMED:350-351；确定性 receipt；repo 锁内复查 db/creator_agent.py:1047-1085）。
- 现状：仅 api/routes/creator_agent.py:320-379 等使用；backend/graph/ 与 backend/agents/ 零 import → 确系平行子系统。

## 回归测试地形

routers/上限：tests/unit/graph/test_routers.py；evaluator 门：tests/integration/test_evaluator_gate.py, tests/unit/agents/test_evaluator.py, tests/unit/agents/nodes/test_evaluator_snapshot.py；memory ns：tests/unit/agents/test_base_agent.py:199, tests/unit/memory/test_store.py；publisher/dry-run：tests/unit/agents/test_publisher_account.py, tests/unit/agents/test_run_publish.py, tests/integration/test_workflow_bug_fixes.py。
