# P0 正确性修复 — async 状态串扰 / Retry 语义 / 发布幂等 / 质量门 fail-closed

依据：父任务 research/p0-claims-verification.md（全部断言 VERIFIED，含 file:line）。本任务只做正确性修复，不引入 Kernel 新抽象（那是 P1a）。所有改动必须保持 LangGraph checkpoint 兼容（只允许新增 state 字段，禁止删除/改语义旧字段）。

## W1. Agent 单例的 request-scoped 可变状态清除

**BaseAgent `_llm_perf_entries` → ContextVar**
- backend/agents/base.py:41 的实例列表改为 `contextvars.ContextVar`（每个 asyncio task 天然隔离）。`_reset_llm_perf()`（:88-90）改为 set 新列表；base.py:71-83, 158-161, 302, 320, 328, 344 的 append/读 `[-1]` 全部经 ContextVar 取当前列表。
- 13 个 agent execute() 开头的 `_reset_llm_perf()` 调用点签名不变。
- 提供读取辅助（如 `_drain_llm_perf()`）供写 performance_log 的调用方使用；grep 全部 `_llm_perf_entries` 消费点一并迁移。
- 决策记录：选 ContextVar 而非 RunContext —— RunContext 是 P1a Kernel 对象，P0 不提前引入半成品抽象。

**EvaluatorAgent weights/bias 局部化**
- backend/agents/evaluator.py:87-88, 113, 134-142, 169, 186-195, 252：删除 `self._weights` / `self._bias_severity` 实例态；`asyncio.gather` 结果放进局部 `EvaluationContext` dataclass（weights, bias_severity），作为参数传入 `_build_system_prompt` 及各消费点。

**同类扫描**：grep `self._` 在 backend/agents/ 下所有在 execute/`__call__` 路径中被写的实例属性，一并局部化或 ContextVar 化（当前勘察除上述两处外未见其他承重实例态，实施时复核）。

## W2. Memory namespace fail-fast

- backend/agents/base.py:132-138：`ns_map.get(namespace, mm.insights_ns)` → 未知 namespace 直接 `raise UnknownMemoryNamespaceError(namespace)`（异常类放 backend/memory/ 或 core/，遵循现有异常风格）。
- 同时 grep base.py 及 memory 写入路径的其他 `.get(<ns 参数>, 默认)` 静默回退，一并 fail-fast。
- 现有 6 个调用方全部合法（见勘察 §6），零行为波及。

## W3. Retry / Error 语义收口

1. **移除 Publisher 的 LangGraph RetryPolicy**（外部副作用节点禁止 generic auto-retry）：backend/graph/error_handling.py:16 删除 publisher 条目；builder.py:99 相应变为无 policy。
2. **RetryPolicy 注册表收口**：builder.py:98, 124, 130 对 evaluator/brief_analyzer/shooting_planner 隐式拿 None。改为穷举注册表：`get_retry_policy(node)` 对未知节点 raise KeyError（或显式 `retry_policy_for(node) -> RetryPolicy | None` + 全节点清单断言），让"有没有框架级重试"成为显式决策。注意：agent 吞异常的现状不变，故大多数 policy 仍只对节点 wrapper 层 raise 生效——在注册表处注释说明这一点。
3. **Error taxonomy 落地（轻量）**：backend/core/error_handling.py `handle_agent_error`（:36-55）为错误分类：`transient`（网络/429/timeout/可自动重试）、`semantic`（输出非法/无结果/需修复或重规划）、`side_effect_unknown`（发布等外部动作结果不明）、`policy_violation` / `auth_expired`（需人工，fail-closed）。写入 state 新字段 `error_class`（默认 transient 保持旧路由行为）。路由暂不改变迁移逻辑（统一 retry 引擎属 P1/P2），本步只让分类进 checkpoint 并可观测。
4. **修正陈旧注释**：services/xhs_publisher.py:352 声称 XHSClient.publish_post 自带 3 次重试，实际 xhs_client.py:553-576 无重试循环——改注释或补实现（选改注释，重试属 Gateway 职责，P1c 收口）。

## W4. 发布幂等与"结果不明"保护

- **幂等键**：真实发布（非 dry-run）前生成确定性 `publish_id`（hash：account_id + 内容 artifact/正文 hash + 图片 hash + 时间窗），随执行写入 state/事件记录；同一 publish_id 已存在"已发布或结果不明"记录时禁止再次真实发布。
- **区分 failed 与 unknown**：backend/agents/publisher.py:306-318 的 catch-all 不再一律 status="failed"：浏览器/HTTP timeout 且已进入真实提交动作后的异常 → status="unknown"（可能已发帖成功）。
- **publish-retry 端点保护**：workflow.py:2587-2705 对 status="unknown" 的重试：先做对账尝试（利用现有 platform_post_id/link_status 匹配机制 :38-61 查近期帖子），对账不确定时要求请求体显式 `force=true` 才继续，并在响应中说明。
- dry-run 双层保护（publisher.py:135-138）保持不变并补测试锚定。

## W5. Evaluator 质量门 fail-closed（compliance 与 quality 分轨）

规则：**compliance/policy 维度的失败永不允许静默放行发布；质量维度可 fail-open。**

1. **降级不再直通 publisher**：nodes/evaluator.py:43-64 合成 `decision=None, degraded=True` 时，graph/routers.py:141-156 不再 `return "publisher"`。路由目标实施时按图拓扑定：优先 review_gate（若 evaluator 有可达边）；否则 END 并把 workflow 置为等待人工状态（复用现有 paused/awaiting_* 语义，**不新增前端未知状态枚举**——先 grep frontend/**/*.vue 对 status 的消费确认，见项目记忆"前端是 Vue"）。人工确认后经由现有 resume/review 通道继续发布。
2. **revision 上限不再强制发布 compliance 拒绝**：routers.py:145-153 —— 达到 max_revision_count 时仅当所有 REJECTED 都来自质量维度才放行 publisher（保持旧行为）；若 evaluator.py:586-595 的 blocking/compliance 判定参与了拒绝 → 走与 (1) 相同的人工通道。需要评估结果里带结构化标记（如 `failed_dimensions`，新字段，向后兼容缺省=质量）。
3. **空内容伪造满分**：agents/evaluator.py:156-179, 660-678 `_empty_pass()` 返回 100/APPROVED → 改为与降级同路（人工通道），空内容不得自动发布。

## 测试（先红后绿，强制）

每项修复先写能复现串扰/错误路由的回归测试，**在未改实现时必须 FAIL**（注意 seed 顺序与期望一致会造成假通过，用交错双 request 驱动、可乱序替身等手段）：
- W1：同一 agent 单例并发两次 execute（asyncio.gather + 可控 await 点），断言两侧 perf entries / weights 互不污染（Win 时间戳钟约 15.6ms 不可作并发判据，用双向 Event 会合）。tests/unit/agents/test_base_agent.py 扩展。
- W2：未知 namespace raise 测试（test_base_agent.py:199 附近）。
- W3：publisher 无 RetryPolicy 断言；未知节点名 KeyError；handle_agent_error 写 error_class。
- W4：timeout→status=unknown；同 publish_id 二次真实发布被拒；unknown 无 force 的 publish-retry 被拒（可测到 service 层）。
- W5：decision=None → 路由不再到 publisher；compliance reject + 上限 → 人工通道；quality reject + 上限 → 仍 publisher（旧行为锚定）。tests/unit/graph/test_routers.py、tests/integration/test_evaluator_gate.py 扩展。
- 全量：`uv run pytest tests/unit tests/integration`（真 PG 相关套件按现有 CI 门控，本机可 skip）；对照基线 FAILED 列表（git stash 法），不得新增失败。

## 边界（明确不做）

- 不引入 RunContext/ArtifactRef 等 Kernel 对象（P1a）；不做 Tool Registry/Gateway（P1c）；不做 RetrievalResult degraded 信号与 rerank 管线（P1b/P1a）；不重写 retry 引擎，只做语义收口。

## 决策记录（2026-09-11 check 后用户拍板，第二轮已实施）

- **F1（W5 续行通道）**：check 发现 fail-closed 走 END+PAUSED 后无任何人工继续发布通道（/resume 会整链重跑）。用户选定「resume + 人工决定」：新增 `pause_reason`，/resume 对该 reason 强制要求 `human_decision: approve|revise`（approve→as_node=evaluator_gate 直达 publisher；revise→重置修订预算；缺省→4xx，绝不整链重启），前端配套 approve/revise 按钮。拒绝 interrupt-gate 驻留方案（改图拓扑+前端流程面过大）。
- **F2（service 层错误契约）**：用户选择立即修而非延到 P1c——点击后超时映射为 `status="unknown"`（typed `publish_result_unknown`），并移除 `publish_post` 上的通用 `@retry`（副作用重提交可致重复发帖）。
- **F3（force_publish 粘性）**：改为 one-shot，任一执行结局后清除。
- W4 原 P0 范围内 mock 路径的 unknown 分支此前近乎不可达，F2 修复后真实浏览器路径同样受保护（tests/unit/services/test_xhs_publisher.py 锚定）。
