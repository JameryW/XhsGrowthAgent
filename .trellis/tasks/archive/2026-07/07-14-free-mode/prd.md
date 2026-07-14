# Free Mode 工具隔离 + 去编排化

## 背景 / 问题

用户新原则："自由创作模式不要暴露工作流相关任何工具，所有流程编排能力交给
omp，工具只提供最基本的原子能力"。

调研（research/research-summary.md）确认现状违背：
1. `XHS_HOST_TOOLS` 是单扁平 list（36 工具），`OmpSession.start()` 全量注册
   (`omp_bridge.py:2058`)，无 mode 区分。free mode agent 看到 20+ thread-bound
   工作流工具（xhs_workflow_*/xhs_review_*/xhs_optimization_*/xhs_blogger_*/
   xhs_ripple_*/xhs_evaluation_*）的 description。
2. `OmpSession` 无 mode 概念（`__init__` 只收 session_id），`get_or_create_session`
   无 mode 参数，WS handler (`agent.py:51`) 不读 mode。bridge 无法感知 free mode。
3. 除 `xhs_workflow_start` 有 disabled 分支外，thread-bound 工具在 free mode 调用
   时无拦截（空 thread_id → 404/error，非友好提示）。
4. free 工具 description 含编排（"Step 1/2/3 of 3"、"feed it to evaluate step 2"、
   "Run xhs_free_evaluate first"）；render 含 `next:` cue（create→evaluate→
   publish→analytics）；`xhs_free_guide` 整个是编排文本（步骤1-4 + revise loop）。
5. spec (`free-creation.md:174`) 已写 atomic-tool principle，但实现未跟上。

## 决策（用户已定）

1. **mode 传递**：session 级 mode 字段 + 切换时 `register_host_tools` 重发工具子集
   （不重连）。OmpSession 持 `mode`，`get_or_create_session(session_id, mode)` 检测
   mode 不匹配则重发工具子集。
2. **guide**：精简为纯护栏参考。删步骤编号/create→evaluate→publish 链/revise loop/
   `next:` cue；留 thread-bound 工具禁用、degraded 勿发、publish 失败恢复、mock 勿
   查 analytics。description 改中性。
3. **render cue**：删 create/evaluate/publish 的 `next:` cue；留 mock/degraded/
   failure 的 `note:` cue（正确性护栏）。

## 方案

### A. mode 传递 + 工具子集注册

**工具分类常量**（omp_bridge.py 新增）：
- `THREAD_BOUND_TOOLS`: 20+ 工作流工具名集合（xhs_workflow_*/xhs_review_*/
  xhs_optimization_*/xhs_blogger_*/xhs_ripple_*/xhs_evaluation_*）。
- `FREE_MODE_TOOLS`: xhs_free_* + account-bound 通用工具（xhs_analytics_*、
  xhs_system_health、xhs_creator_*）。
- `_tools_for_mode(mode)`: 返回该 mode 的工具子集 list。free → FREE_MODE_TOOLS；
  其他（trend/brief/None）→ 全量 XHS_HOST_TOOLS（保持现状，工作流模式不变）。

**OmpSession 改造**：
- `__init__(session_id, mode="workflow")` 加 mode 字段。
- `start()` 中 `register_host_tools(_tools_for_mode(self.mode))` 替代全量。
- 新增 `async def set_mode(self, mode)`: 更新 self.mode + `register_host_tools(
  _tools_for_mode(mode))` 重发（omp 源码证实全量替换语义，下次 model call 前刷新）。

**get_or_create_session 改造**：
- 签名加 `mode: str = "workflow"`。
- 已存在 session 且 `session.mode != mode` → 调 `session.set_mode(mode)` 重发工具子集
  （不重建 session，保留对话上下文；用户选了 session 级 mode + 切换重发）。

**WS handler 改造**（agent.py:51）：
- 读 `mode = websocket.query_params.get("mode", "workflow")`。
- `get_or_create_session(session_id_param, mode)`。

**前端**（AgentTUI.vue:82,532）：
- `WS_URL` 拼接 `?mode=free`（free mode 入口）或无 mode 参数（trend/brief）。
- `isFreeCreationEntry` 决定拼接。

### B. 工具 description 去编排

按调研问题5清单：
- `xhs_free_draft_create`: 删 "Step 1 of 3"、"feed it to evaluate step 2"、
  "then publish step 3"、"For the full guide call xhs_free_guide"。留 "Create a
  free-mode content draft (thread-less). Returns draft_id."
- `xhs_free_evaluate`: 删 "Step 2 of 3"、"Input draft_id from create"。留评估描述。
- `xhs_free_publish`: 删 "Step 3 of 3"、"Input draft_id from create"、"Run
  xhs_free_evaluate first"。留发布描述。
- `xhs_free_analytics`: 删 "Input draft_id from create/publish"。留 "draft must
  have been published (post_id persisted)"（依赖护栏）。
- `xhs_free_draft_list`: 删 "Use to find a draft_id for evaluate/publish/update/delete"。
- `xhs_free_draft_update`: 删 "Use to refine before evaluate/publish"。
- `xhs_free_suggestions`/`delete`: 已符合，不动。
- `xhs_free_guide`: description 改 "Read-only reference for free creation mode
  tools and usage rules."

### C. guide 文本精简为纯护栏

重写 guide 文本（omp_bridge.py:911-957）：
- 删：步骤 1-4 编号、"Reuse draft_id across create→evaluate→publish"、"Run
  evaluate before publish"、revise loop、"After publish call analytics"。
- 留：thread-bound 工具禁用清单、workflow_start disabled、degraded 勿发假分数、
  publish 失败恢复 + 勿调 analytics。
- 中性工具清单（xhs_free_* 列表，无顺序、无 → 箭头指向下一步）。

### D. render 去 next: 留 note:

- `xhs_free_draft_create` render: 删 `next: call xhs_free_evaluate...`。
- `xhs_free_evaluate` render: 删 `next: revise per hints via update, then
  evaluate again...`。
- `xhs_free_publish` render: 删 `next: call xhs_free_analytics...`；留 real/mock
  的 `note:`（mock: dry-run, analytics not available）和 failure 的 Error/Recovery。
- `xhs_free_analytics`: 无 next: cue，不动。
- mock/degraded/failure 的 `note:` cue 全留（防错误调用）。

### E. spec 同步

- `free-creation.md`:
  - render subsection（57-113）：删 `next:` cue 要求，留 `note:` cue 要求。
  - guide 文本描述（115-137）：改为"纯护栏参考"。
  - atomic-tool principle（174）：扩展，加"工具按 mode 隔离 + description 无编排"。
  - 新增 "Mode-based tool isolation" 段：free mode 只注册 FREE_MODE_TOOLS 子集。
- `omp-integration.md`（cross-audit 约定 312-354）：TS extension 路径单独 task
  （见 Out of scope）。

## Out of scope

- **TS extension 路径**（omp CLI 直接使用，非 Web TUI）：TS extension 无条件注册
  全部工作流工具 + 注入含编排的 system prompt（index.ts:52-112, events.ts:19-46）。
  Web TUI free mode 走 bridge 不走 TS extension，故本 task 不动 TS extension。
  TS extension 改造（按 mode 过滤 + system prompt 去编排）另开 task，需先查
  ExtensionAPI 是否支持运行时 unregister tool。
- **mode 切换 UI**：用户在 free/trend 间切换是页面级导航，WS 重连。本 task 只确保
  重连后正确注册子集 + 同 session_id 跨 mode 重发。不做 in-page mode 切换。

## Tests

- `test_omp_bridge.py`:
  - `_tools_for_mode("free")` 返回 FREE_MODE_TOOLS，不含任何 thread-bound 工具。
  - `_tools_for_mode("workflow")` 返回全量。
  - `OmpSession(mode="free")` 启动注册子集（mock register_host_tools 断言子集）。
  - `set_mode("free"→"workflow")` 重发全量。
  - `get_or_create_session` mode 不匹配 → 调 set_mode。
  - guide 文本断言：无 "Step 1"/"Run evaluate before publish"/"create→evaluate→
    publish"；有 "thread-bound"/"degraded"/"publish can fail"。
  - render 断言：create/evaluate/publish 无 `next:`；publish 仍含 mock `note:` +
    failure Recovery。
  - description 断言：create 无 "Step 1 of 3"。
- `test_free_routes.py`: 无变化（route 层不涉及 mode 工具注册）。
- 新增 `test_agent_ws_mode`（agent.py WS 读 mode 传 session）：若 agent route 可测。

## Validation

ruff check . + ruff format --check + mypy backend + pytest + vue-tsc --noEmit。
