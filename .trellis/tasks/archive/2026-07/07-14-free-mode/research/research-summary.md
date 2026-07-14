# Research: Free Mode 工具暴露现状 + 去编排化改造可行性

- **Query**: 用户新原则"自由创作模式不要暴露工作流相关任何工具，所有流程编排能力交给 omp，工具只提供最基本的原子能力"
- **Scope**: Internal (codebase + omp source) / mixed
- **Date**: 2026-07-14

---

## 1. OmpSession 与 mode 的关系

### 结论：OmpSession 完全无 mode 概念；一个 session 对所有 mode 通用；bridge 无法感知当前是 free mode。

**OmpSession 定义** (`backend/services/omp_bridge.py:1990-2010`):
```python
class OmpSession:
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        ...
```
`__init__` 只接收 `session_id`，**没有 mode 参数**。OmpSession 不跟踪、不存储、不区分 mode。

**get_or_create_session** (`omp_bridge.py:2533-2554`):
```python
async def get_or_create_session(self, session_id: str | None = None) -> OmpSession:
    if session_id and session_id in self._sessions:
        ...
        return self._sessions[session_id]
    ...
    session = OmpSession(session_id)
    await session.start()
    ...
```
只有 `session_id` 参数，**没有 mode 参数**。一个 session 理论上可跨 trend/brief/free 复用（同一 omp 进程服务多种 mode）。

**free mode 入口** (`frontend/src/views/Home.vue:80-82`):
```javascript
const query: Record<string, string> = { mode: 'free' }
...
await router.push({ name: 'tui', query })
```
free mode 通过 `/tui?mode=free` 路由进入。但 mode 信息**只停留在前端 Vue route query 中**。

**WebSocket 连接** (`frontend/src/views/AgentTUI.vue:82`):
```javascript
const WS_URL = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/api/agent/ws`
```
WS_URL 是常量，**不带 session_id 也不带 mode**。`connectAgentWs()` (line 532) `new WebSocket(WS_URL)` 不附加任何 query 参数。

**后端 WebSocket handler** (`backend/api/routes/agent.py:51`):
```python
session_id_param = websocket.query_params.get("session_id")
```
只读 `session_id`，**不读 mode**。`get_or_create_session(session_id_param)` (line 59) 不传 mode。

**结论**：从 `/tui?mode=free` 到 omp bridge 的整条路径，mode 信息**在 WebSocket 连接时丢失**。bridge 不知道当前 session 是 free 还是 trend/brief。所有 session 启动时注册相同的 `XHS_HOST_TOOLS` 全量列表。

### Files Found

| File Path | Description |
|---|---|
| `backend/services/omp_bridge.py:1990-2010` | OmpSession 类定义，无 mode 字段 |
| `backend/services/omp_bridge.py:2533-2554` | get_or_create_session，无 mode 参数 |
| `backend/api/routes/agent.py:51,59` | WebSocket handler 只读 session_id，不读 mode |
| `frontend/src/views/AgentTUI.vue:82,532-535` | WS_URL 常量不带 mode；connectAgentWs 不传 mode |
| `frontend/src/views/Home.vue:80-82` | /tui?mode=free 路由入口，mode 只在 query 中 |
| `frontend/src/router/index.ts:75` | /tui 路由定义 |

---

## 2. 工具注册时机与 set_host_tools 重发能力

### 结论：set_host_tools 是全量替换语义，可在 session 运行中多次调用重发不同工具子集。

**注册时机** (`omp_bridge.py:2057-2058`):
```python
# Register XHS host tools right after ready
await self.register_host_tools(XHS_HOST_TOOLS)
```
在 `OmpSession.start()` 中，omp 发出 ready 信号后立即注册全量 `XHS_HOST_TOOLS`。

**register_host_tools 方法** (`omp_bridge.py:2140-2142`):
```python
async def register_host_tools(self, tools: list[dict[str, Any]]) -> None:
    """Register host tools with omp. Sends set_host_tools command."""
    await self._request({"type": "set_host_tools", "tools": tools})
```
这是公开方法，可在运行中再次调用。

**omp 源码 — set_host_tools 命令处理** (`/home/admin/.npm-global/.../src/modes/rpc/rpc-mode.ts:815-819`):
```typescript
case "set_host_tools": {
    const tools = normalizeHostToolDefinitions(command.tools);
    const rpcTools = hostToolBridge.setTools(tools);
    await session.refreshRpcHostTools(rpcTools);
    return success(id, "set_host_tools", { toolNames: tools.map(tool => tool.name) });
}
```

**omp 源码 — setTools 全量替换** (`/home/admin/.npm-global/.../src/modes/rpc/host-tools.ts:87-89`):
```typescript
setTools(tools: RpcHostToolDefinition[]): AgentTool[] {
    this.#definitions = new Map(tools.map(tool => [tool.name, tool]));
    return tools.map(tool => new RpcHostToolAdapter(tool, this));
}
```
`this.#definitions = new Map(...)` — **直接替换整个 Map**，不是 append/merge。

**omp 源码 — refreshRpcHostTools 运行时刷新** (`/home/admin/.npm-global/.../src/session/agent-session.ts:5218-5244`):
```typescript
async refreshRpcHostTools(rpcTools: AgentTool[]): Promise<void> {
    ...
    for (const name of previousRpcHostToolNames) {
        this.#toolRegistry.delete(name);  // 删除旧工具
    }
    this.#rpcHostToolNames.clear();
    for (const tool of rpcTools) {
        ...
        this.#toolRegistry.set(finalTool.name, finalTool);  // 注册新工具
        this.#rpcHostToolNames.add(finalTool.name);
    }
```
先删除之前的 RPC host tools，再注册新的。注释明确写 "Replace RPC host-owned tools and refresh the active tool set **before the next model call**"。

**关键发现**：set_host_tools 是幂等的全量替换。可以在 session 运行中多次调用，每次发送不同的工具子集，omp 会在下一次 model call 前刷新可用工具列表。这意味着**方案 A（按 mode 注册子集 + mode 切换重发）在 omp 协议层面完全可行**。

### Files Found

| File Path | Description |
|---|---|
| `backend/services/omp_bridge.py:2057-2058` | start() 中 ready 后全量注册 |
| `backend/services/omp_bridge.py:2140-2142` | register_host_tools 方法，可运行中调用 |
| `/home/admin/.npm-global/.../rpc-mode.ts:815-819` | omp set_host_tools 命令处理 |
| `/home/admin/.npm-global/.../host-tools.ts:87-89` | setTools 全量替换 Map |
| `/home/admin/.npm-global/.../agent-session.ts:5218-5244` | refreshRpcHostTools 运行时刷新工具集 |
| `.trellis/tasks/archive/2026-06/06-27-web-tui-omp-rpc-ai-agent/research/omp-rpc-protocol.md` | omp RPC 协议研究文档 |

---

## 3. Free Mode 当前可见的工具

### 结论：XHS_HOST_TOOLS 是单扁平 list，set_host_tools 把全部 tool schema 下发给 LLM。free mode agent 能看到所有 36 个工具的 description（包括 20+ 个 thread-bound 工作流工具）。

**XHS_HOST_TOOLS 定义** (`omp_bridge.py:119-798`)，共 36 个工具：

**Thread-bound 工作流工具（20 个，free mode 不应暴露）**:

| Tool name | Line | Description |
|---|---|---|
| `xhs_workflow_status` | 121 | Query workflow status (需 thread_id) |
| `xhs_workflow_pause` | 133 | Pause a running workflow (需 thread_id) |
| `xhs_workflow_resume` | 145 | Resume a paused workflow (需 thread_id) |
| `xhs_workflow_cancel` | 157 | Cancel a workflow (需 thread_id) |
| `xhs_review_approve` | 169 | Approve content in review gate (需 thread_id) |
| `xhs_review_reject` | 182 | Reject content with feedback (需 thread_id) |
| `xhs_review_pending` | 201 | Get content awaiting review (需 thread_id) |
| `xhs_review_versions` | 213 | Get all content versions (需 thread_id) |
| `xhs_blogger_pending` | 225 | Get pending blogger candidates (需 thread_id) |
| `xhs_blogger_select` | 237 | Select a blogger candidate (需 thread_id) |
| `xhs_optimization_draft` | 256 | Generate optimization draft (需 thread_id) |
| `xhs_optimization_select` | 268 | Select optimization version (需 thread_id) |
| `xhs_workflow_list` | 288 | List all workflows (无 thread_id) |
| `xhs_workflow_delete` | 294 | Delete a workflow (需 thread_id) |
| `xhs_workflow_history` | 342 | Get checkpoint history (需 thread_id) |
| `xhs_workflow_trigger_analytics` | 362 | Manually trigger analytics (需 thread_id) |
| `xhs_publish_retry` | 377 | Publish/retry existing workflow content (需 thread_id) |
| `xhs_ripple_pending` | 395 | Get Ripple CAS decision status (需 thread_id) |
| `xhs_ripple_decision` | 410 | Submit Ripple CAS decision (需 thread_id) |
| `xhs_ripple_retry` | 432 | Retry Ripple CAS analysis (需 thread_id) |
| `xhs_evaluation_result` | 569 | Get RQGM evaluation for a workflow (需 thread_id) |
| `xhs_evaluation_run` | 584 | Manually evaluate a workflow (需 thread_id) |

**Thread-less free mode 工具（10 个）**:

| Tool name | Line | Description |
|---|---|---|
| `xhs_free_draft_create` | 599 | Create a free-mode draft |
| `xhs_free_evaluate` | 637 | Evaluate a free-mode draft |
| `xhs_free_publish` | 657 | Publish a free-mode draft |
| `xhs_free_analytics` | 677 | Post-publish engagement for free draft |
| `xhs_free_suggestions` | 699 | Creative suggestions for free mode |
| `xhs_free_draft_list` | 715 | List free-mode drafts |
| `xhs_free_draft_update` | 730 | Update a free-mode draft |
| `xhs_free_draft_delete` | 770 | Delete a free-mode draft |
| `xhs_free_guide` | 789 | Read-only guide for free mode |

**Account-bound 通用工具（6 个，无 thread_id，free mode 可用）**:

| Tool name | Line | Description |
|---|---|---|
| `xhs_analytics_dashboard` | 306 | Analytics dashboard (需 account_id) |
| `xhs_analytics_costs` | 318 | LLM cost tracking (无参数) |
| `xhs_system_health` | 333 | System health check (无参数) |
| `xhs_analytics_report` | 447 | Growth report (需 account_id) |
| `xhs_analytics_performance` | 464 | Post performance (需 account_id) |
| `xhs_creator_stats` | 486 | Creator Center stats (需 account_id) |
| `xhs_creator_analysis` | 509 | Creator data analysis (需 account_id) |
| `xhs_creator_suggestions` | 527 | Creator suggestions (需 account_id, mode param) |
| `xhs_creator_quality` | 551 | Historical creative quality (需 account_id) |

**set_host_tools 下发机制** (`omp_bridge.py:2058`): `register_host_tools(XHS_HOST_TOOLS)` 把整个 list（36 个工具的 name/label/description/parameters schema）通过 `set_host_tools` 命令发给 omp，omp 把它们注册到 tool registry 中供 LLM 调用。

**结论**：free mode agent **真能看到**所有 36 个工具的 description。set_host_tools 把全部 tool schema 下发给 LLM，包括 20+ 个 thread-bound 工作流工具。这直接违背用户新原则"自由创作模式不要暴露工作流相关任何工具"。

注意：`xhs_workflow_start` **不在 XHS_HOST_TOOLS 中**（已移除），但 `_execute_xhs_host_tool` 中仍有 disabled 分支处理它（line 899-907），作为防御性措施。

### Files Found

| File Path | Description |
|---|---|
| `backend/services/omp_bridge.py:119-798` | XHS_HOST_TOOLS 完整定义（36 个工具） |
| `backend/services/omp_bridge.py:801` | _XHS_TOOL_NAMES = {t["name"] for t in XHS_HOST_TOOLS} |

---

## 4. Thread-bound 工具在 Free Mode 调用时的现有拦截

### 结论：除了 xhs_workflow_start 有 disabled 分支外，其他所有 thread-bound 工具在 free mode 调用时**无任何拦截**，直接执行（用空 thread_id 调 API → 404/error）。

**xhs_workflow_start 拦截** (`omp_bridge.py:899-907`):
```python
if tool_name == "xhs_workflow_start":
    return _make_text_result(
        (
            "xhs_workflow_start is disabled in OMP free orchestration. "
            "Use the Simple Mode UI to run the fixed workflow."
        ),
        None,
        is_error=True,
    )
```
这是唯一的工具级拦截，在 `_execute_xhs_host_tool` 函数入口处。

**其他 thread-bound 工具无拦截**：从 line 960 开始的 dispatch 链（`if tool_name == "xhs_workflow_status": ... elif tool_name == "xhs_workflow_pause": ...` 等），每个分支直接提取 `thread_id = arguments.get("thread_id", "")` 然后调 API。

如果 free mode agent 调用 `xhs_workflow_status`（thread_id 为空）:
```python
thread_id = arguments.get("thread_id", "")  # → ""
resp = await client.get(f"{url}/workflow/status/{thread_id}")  # → GET /api/workflow/status/
```
这会命中 FastAPI 路由的 404（路径不匹配）或 _unwrap_envelope 抛 RuntimeError。

**_handle_host_tool_call 判断逻辑** (`omp_bridge.py:2374`):
```python
if tool_name in _XHS_TOOL_NAMES:
    # Auto-execute known XHS tool in backend
    ...
```
只要工具名在 `_XHS_TOOL_NAMES` 集合中（所有 36 个工具都在），就自动执行。**不检查 mode、不检查是否 thread-bound、不检查 thread_id 是否为空**。

**结论**：free mode agent 如果调 thread-bound 工具，不会收到"此工具在 free mode 不可用"的明确提示，而是收到一个 HTTP 404 或 API error。这不是友好的拦截，agent 可能反复尝试。

### Files Found

| File Path | Description |
|---|---|
| `backend/services/omp_bridge.py:899-907` | xhs_workflow_start disabled 分支（唯一拦截） |
| `backend/services/omp_bridge.py:960-1953` | dispatch 链，其他工具无 mode 拦截 |
| `backend/services/omp_bridge.py:2374` | _handle_host_tool_call 只检查 _XHS_TOOL_NAMES，不检查 mode |

---

## 5. Free 工具 Description 的编排内容

### 结论：xhs_free_draft_create/evaluate/publish 的 description 含步骤编号和编排提示，应删；xhs_free_analytics 的依赖提示是正确性护栏，应留。

**xhs_free_draft_create** (`omp_bridge.py:601-606`):
```
"Step 1 of 3 (create). Create a free-mode content draft (thread-less). "
"Returns draft_id — feed it to xhs_free_evaluate (step 2) "
"then xhs_free_publish (step 3). "
"For the full orchestration guide call xhs_free_guide."
```
- 编排措辞（应删）: "Step 1 of 3 (create)", "feed it to xhs_free_evaluate (step 2)", "then xhs_free_publish (step 3)", "For the full orchestration guide call xhs_free_guide"
- 应留: "Create a free-mode content draft (thread-less). Returns draft_id."

**xhs_free_evaluate** (`omp_bridge.py:639-643`):
```
"Step 2 of 3 (evaluate). Evaluate a free-mode draft via the RQGM agent-as-a-judge "
"panel. Input draft_id from xhs_free_draft_create. Returns EvaluationResult "
"(overall_score, dimensions, decision)."
```
- 编排措辞（应删）: "Step 2 of 3 (evaluate)", "Input draft_id from xhs_free_draft_create"
- 应留: "Evaluate a free-mode draft via the RQGM agent-as-a-judge panel. Returns EvaluationResult (overall_score, dimensions, decision)."

**xhs_free_publish** (`omp_bridge.py:659-663`):
```
"Step 3 of 3 (publish). Publish a free-mode draft to Xiaohongshu (thread-less) "
"via the account's CDP profile login state. Input draft_id from xhs_free_draft_create. "
"Run xhs_free_evaluate first for a quality check."
```
- 编排措辞（应删）: "Step 3 of 3 (publish)", "Input draft_id from xhs_free_draft_create", "Run xhs_free_evaluate first for a quality check"
- 应留: "Publish a free-mode draft to Xiaohongshu (thread-less) via the account's CDP profile login state."

**xhs_free_analytics** (`omp_bridge.py:679-685`):
```
"Post-publish engagement check. Fetch views/likes/collects/comments/shares/"
"engagement_rate for a published free draft via XHSClient.get_post_analytics. "
"Input draft_id from xhs_free_draft_create/publish. The draft must have been "
"published (post_id persisted) — call xhs_free_publish first. Returns current "
"engagement snapshot (single fetch, not trend over time)."
```
- 编排措辞（应删）: "Input draft_id from xhs_free_draft_create/publish"
- 正确性护栏（应留）: "The draft must have been published (post_id persisted) — call xhs_free_publish first."（这是依赖约束——analytics 需要 post_id，未发布的 draft 调 analytics 会 400）
- 应留: "Post-publish engagement check. Fetch views/likes/collects/comments/shares/engagement_rate for a published free draft. Returns current engagement snapshot."

**xhs_free_suggestions** (`omp_bridge.py:701-705`):
```
"Creative suggestions (style/topic/format/timing) for the account from "
"imported Creator Center stats. No draft_id needed — call any time. "
"Returns a cold-start note when no stats are imported yet."
```
- 已符合原子工具原则：无编排措辞，无步骤编号，无 `next:` cue。"No draft_id needed — call any time" 是使用说明不是编排。
- 应留全部。

**xhs_free_draft_list** (`omp_bridge.py:717-719`):
```
"List free-mode drafts for an account (thread-less). Returns draft_id + title "
"summary, no full body. Use to find a draft_id for evaluate/publish/update/delete."
```
- 编排措辞（应删）: "Use to find a draft_id for evaluate/publish/update/delete"（指向下一步该调什么工具）
- 应留: "List free-mode drafts for an account (thread-less). Returns draft_id + title summary, no full body."

**xhs_free_draft_update** (`omp_bridge.py:732-734`):
```
"Update a free-mode draft (thread-less). Overwrites specified fields, keeps "
"draft_id unchanged. Use to refine before evaluate/publish."
```
- 编排措辞（应删）: "Use to refine before evaluate/publish"
- 应留: "Update a free-mode draft (thread-less). Overwrites specified fields, keeps draft_id unchanged."

**xhs_free_draft_delete** (`omp_bridge.py:772-774`):
```
"Delete a free-mode draft (thread-less). Idempotent — deleting a non-existent "
"draft is not an error."
```
- 已符合原子工具原则，无编排措辞。应留全部。

**xhs_free_guide** (`omp_bridge.py:791-795`):
```
"Read-only guide for free creation mode. Returns the orchestration steps and tool "
"chain. Call this first in free mode to learn the create→evaluate→publish loop and "
"which tools to use."
```
- 编排措辞（应删）: "Returns the orchestration steps and tool chain", "Call this first in free mode to learn the create→evaluate→publish loop and which tools to use"
- 如果按新原则改造，guide 工具本身可能需要重新定位——它返回的编排内容（步骤编号、工具链）本身就是编排。但如果保留 guide 作为参考文档，description 可改为中性的 "Read-only reference for free creation mode tools and usage rules."

**额外发现 — render 中的 next:/note: cue**：description 之外，`_execute_xhs_host_tool` 的 render 输出也含编排 cue：
- `xhs_free_draft_create` render (line 1714-1718): `next: call xhs_free_evaluate({draft_id}) for a quality check before publish.`
- `xhs_free_evaluate` render (line 1769-1772): `next: revise per the hints via xhs_free_draft_update (keep draft_id), then xhs_free_evaluate again before publish.`
- `xhs_free_publish` render (line 1798-1801): `next: call xhs_free_analytics({draft_id}) to check post-publish engagement.`

这些 render cue 是 spec 文档 (`free-creation.md:57-113`) 明确要求的编排性提示。按新原则，这些 `next:` cue 属于编排（告诉 agent 下一步调什么），应删。但 mock/degraded/failure 的 `note:` cue 是正确性护栏（防止错误调用），应留。

### Files Found

| File Path | Description |
|---|---|
| `backend/services/omp_bridge.py:599-797` | 9 个 xhs_free_* 工具的 description |
| `backend/services/omp_bridge.py:1714-1718` | create render 中的 next: cue |
| `backend/services/omp_bridge.py:1769-1772` | evaluate render 中的 next: cue |
| `backend/services/omp_bridge.py:1798-1801` | publish render 中的 next: cue |
| `.trellis/spec/backend/free-creation.md:57-113` | spec 要求 render 含 next:/note: cue |

---

## 6. xhs_free_guide 的编排 vs 护栏分层

### 结论：guide 文本含步骤编号、工具链顺序、revise loop 规则（编排，应删），也含 thread-bound 工具禁用、degraded 勿发、publish 失败恢复（护栏，应留）。

**guide 文本全文** (`omp_bridge.py:911-957`)，分层如下：

**编排内容（应删）**:
1. Line 916-922 — 步骤编号 + 工具链:
   ```
   "1. CREATE: xhs_free_draft_create ... → returns draft_id"
   "2. EVALUATE: xhs_free_evaluate (draft_id) → RQGM 6-dimension quality score + decision"
   "3. PUBLISH: xhs_free_publish (draft_id) → publishes via account CDP login state"
   "4. ANALYTICS: xhs_free_analytics (draft_id) → post-publish engagement ..."
   ```
2. Line 939 — 顺序规则:
   ```
   "Reuse draft_id across create→evaluate→publish; do not recreate on each step."
   ```
3. Line 940 — 顺序规则:
   ```
   "Run xhs_free_evaluate before xhs_free_publish for a quality gate."
   ```
4. Line 941-943 — revise loop 规则:
   ```
   "If evaluate returns needs_revision/rejected, use xhs_free_draft_update "
   "per the revision_hints (keep the same draft_id), then xhs_free_evaluate "
   "again before publish — do not publish a needs_revision draft."
   ```
5. Line 956 — happy path 编排:
   ```
   "After a successful publish, call xhs_free_analytics to check engagement."
   ```

**正确性护栏内容（应留）**:
1. Line 935-937 — thread-bound 工具禁用:
   ```
   "Do NOT call thread-bound tools (xhs_workflow_status/pause/resume/cancel, "
   "xhs_review_*, xhs_optimization_*) — free mode has no thread_id; they will fail."
   ```
   这是防止 agent 调不存在/不适用的工具的护栏。
2. Line 938 — workflow_start 禁用:
   ```
   "xhs_workflow_start is disabled in free mode."
   ```
3. Line 944-949 — degraded 勿发:
   ```
   "Evaluate can degrade (LLM timeout → pass-through fallback with "
   "degraded=True, overall_score=100/decision=approved): the 100/approved "
   "is a FAKE fallback, NOT a real score. ... do NOT publish on a degraded "
   "verdict — re-run xhs_free_evaluate (keep draft_id) once the LLM is available."
   ```
   防止 agent 在假分数上发布的正确性护栏。注意其中 "re-run xhs_free_evaluate" 有编排成分，但核心是"不要相信假分数→不要发布"。
4. Line 950-955 — publish 失败恢复:
   ```
   "Publish can fail (status=failed/auth_expired): the render shows "
   "Error/Error Type/Recovery — read the recovery hint, fix the cause "
   "(e.g. re-login the account), then re-run xhs_free_publish "
   "(keep the same draft_id). Do NOT call xhs_free_analytics on a failed "
   "publish (no post_id → 400)."
   ```
   防止在失败 publish 上调 analytics（会 400）的护栏。"re-run xhs_free_publish" 有编排成分，但核心是"失败→看 recovery→修→重试"和"不要在失败上调 analytics"。

**工具参考（中性，应留）**：
- Line 924-933 — Suggestions 和 Draft management 工具列表:
  ```
  "Suggestions:\n- xhs_free_suggestions (account_id) → ...\n"
  "Draft management:\n- xhs_free_draft_list (account_id) → ...\n"
  "- xhs_free_draft_update (draft_id, fields...) → ...\n"
  "- xhs_free_draft_delete (draft_id) → remove a draft"
  ```
  这部分是工具的参数说明，如果去掉步骤编号和 → 箭头，可作为中性参考保留。

**关键矛盾**：guide 文本的核心是编排（步骤 1-4 + revise loop），如果按新原则删除所有编排，guide 文本会被大幅缩减。但护栏部分（thread-bound 禁用、degraded 勿发、publish 失败恢复）仍有价值。改造方案需要决定：是删除 guide 工具本身，还是保留一个只含护栏的精简版 guide。

### Files Found

| File Path | Description |
|---|---|
| `backend/services/omp_bridge.py:911-957` | xhs_free_guide 完整文本 |
| `.trellis/spec/backend/free-creation.md:115-137` | spec 描述 guide 的 discovery 机制 |

---

## 7. TS Extension 路径

### 结论：TS extension 注册所有工具（含工作流工具），无 mode 过滤。TS extension 通过 before_agent_start 注入 system prompt（含编排内容）。但 Web TUI free mode 走 bridge 路径，不走 TS extension。

**TS extension 工具注册** (`backend/omp/extensions/xhsagent-ext/src/index.ts:52-112`):
```typescript
export default function xhsagentExt(pi: ExtensionAPI) {
  registerWorkflowStatus(pi);    // 工作流工具
  registerWorkflowPause(pi);
  registerWorkflowResume(pi);
  registerWorkflowCancel(pi);
  registerWorkflowList(pi);
  ...
  registerReviewApprove(pi);    // review 工具
  ...
  registerOptimizationDraft(pi); // optimization 工具
  ...
  registerEvents(pi);            // 事件 hooks
}
```
TS extension **无条件注册所有工具**（工作流 + review + optimization + analytics + evaluation + ripple + blogger），没有 mode 判断。而且 TS extension **没有注册任何 xhs_free_* 工具**——free 工具只在 Python bridge 的 XHS_HOST_TOOLS 中。

**TS extension system prompt** (`backend/omp/extensions/xhsagent-ext/src/events.ts:19-46`):
```typescript
pi.on("before_agent_start", () => {
    return {
      systemPrompt: [
        "You have access to XhsGrowthAgent tools for Xiaohongshu (小红书) free orchestration.",
        "Do not start the fixed workflow from OMP. ...",
        "Free orchestration loop (no workflow thread — use thread-less xhs_free_* tools):",
        "1. CREATE: xhs_free_draft_create ...",
        "2. EVALUATE: xhs_free_evaluate ...",
        "3. PUBLISH: xhs_free_publish ...",
        "4. ANALYTICS: xhs_free_analytics ...",
        ...
        "Do NOT call thread-bound tools ... in free mode — there is no thread_id.",
        ...
      ],
    };
  });
```
TS extension 的 before_agent_start 注入的 system prompt **含完整编排内容**（步骤 1-4 + revise loop + degraded 规则 + publish 失败恢复）。

**关键架构事实**（`free-creation.md:116-137`）：
> The Web TUI free mode goes through the Python RPC bridge (`OmpSession`), NOT the TS extension. The omp RPC protocol has **no `set_system_prompt` command** and no `before_agent_start` hook (that hook is TS-extension-API only). So the bridge **cannot inject a system prompt**.

**结论**：
- Web TUI free mode 走 **bridge 路径**，不走 TS extension。TS extension 的 system prompt 对 Web TUI free mode **不生效**。
- TS extension 路径用于 omp CLI 直接使用时（非 Web TUI），此时 TS extension 注册所有工作流工具 + 注入含编排的 system prompt。
- 两条路径工具暴露现状：
  - **Bridge 路径**（Web TUI）：set_host_tools 下发全部 36 个工具（含 20+ thread-bound），无 system prompt。
  - **TS extension 路径**（omp CLI）：注册全部 ~31 个工作流工具（不含 xhs_free_*），注入含编排的 system prompt。
- 两条路径都暴露工作流工具给 agent，都需改造。

### Files Found

| File Path | Description |
|---|---|
| `backend/omp/extensions/xhsagent-ext/src/index.ts:52-112` | TS extension 无条件注册所有工具 |
| `backend/omp/extensions/xhsagent-ext/src/events.ts:19-46` | before_agent_start 注入含编排的 system prompt |
| `.trellis/spec/backend/free-creation.md:116-137` | bridge 无 set_system_prompt，TS prompt 不生效于 Web TUI |
| `.trellis/spec/backend/omp-integration.md:312-354` | 两条平行实现 cross-audit 约定 |

---

## 8. 改造方案选项

基于以上调研，列出 3 个可行方案：

### 方案 A：启动时按 mode 注册子集 + mode 切换时重发 set_host_tools

**机制**：
1. WebSocket URL 加 mode 参数: `ws://...//api/agent/ws?mode=free`
2. agent.py 读取 mode，传给 get_or_create_session
3. OmpSession.start() 按 mode 选择工具子集: free mode 只注册 xhs_free_* + account-bound 通用工具（~19 个），不注册 thread-bound 工作流工具
4. mode 切换时（如果支持），调 register_host_tools(new_subset) 重发 set_host_tools

**可行性**：
- omp 协议支持：set_host_tools 是全量替换，可在运行中多次调用（`host-tools.ts:87-89`, `agent-session.ts:5218-5244` 证实）
- 前端改动：WS_URL 需动态拼接 mode（`AgentTUI.vue:82`）
- 后端改动：agent.py 读 mode query param，OmpSession 按 mode 选工具子集

**工作量**：中等。需改 agent.py（读 mode）、omp_bridge.py（OmpSession 按 mode 选工具子集、工具列表分类常量）、AgentTUI.vue（WS_URL 拼接 mode）。

**风险**：
- 如果一个 WebSocket 连接需要切换 mode（如用户从 free 切到 trend），需要重连或重发 set_host_tools。但当前架构中 mode 在连接时确定，切换 mode 是页面级导航（重新进入 /tui?mode=xxx），WebSocket 会重连，所以每个连接的 mode 是固定的。
- 如果同一 session_id 跨 mode 复用（用户先 free mode 用 session A，再切 trend mode 带 session_id=A 重连），会命中已有 session 的旧工具集。需要在 get_or_create_session 中检测 mode 不匹配时重建 session 或重发工具。

**是否真满足"不暴露"**：**是**。free mode 的 omp 进程注册时就不含 thread-bound 工具，LLM 看不到它们的 description，不会尝试调用。

### 方案 B：工具运行时拦截 + description 标 mode

**机制**：
1. 保持 XHS_HOST_TOOLS 全量不变，set_host_tools 仍下发全部 36 个工具
2. 在工具 description 中标注 "[free mode only]" / "[workflow mode only]" 标签
3. _execute_xhs_host_tool 中对 thread-bound 工具加 mode 检查：如果是 free mode 但工具是 thread-bound，返回 "this tool is not available in free mode" 错误
4. 需要 bridge 知道当前 mode（同方案 A 的 mode 传递）

**可行性**：
- 不依赖 set_host_tools 重发
- 但工具 description 仍下发全部 36 个给 LLM

**工作量**：中等。需改 agent.py（读 mode）、omp_bridge.py（_execute_xhs_host_tool 加 mode 检查、工具 description 加标签）。

**风险**：
- LLM 仍然看到 thread-bound 工具的 description（只是标注了不可用），可能仍尝试调用 → 收到错误 → 浪费 turn
- 不满足"不暴露"的严格定义——description 仍然可见

**是否真满足"不暴露"**：**否**。工具 description 仍下发，LLM 能看到。"不暴露"应理解为 LLM 不知道这些工具存在，而非调用时被拦。

### 方案 C：单 session 全量但 free mode 用 system prompt 约束

**机制**：
1. 保持 XHS_HOST_TOOLS 全量不变
2. bridge 路径注入 system prompt（但 spec 明确说 bridge 无 set_system_prompt 命令）

**可行性**：
- **不可行**。spec (`free-creation.md:118-120`) 明确写："The omp RPC protocol has no `set_system_prompt` command and no `before_agent_start` hook"。bridge 无法注入 system prompt。
- 除非 omp 协议新增 set_system_prompt 命令（需改 omp 源码），否则方案 C 在 bridge 路径不可行。

**是否真满足"不暴露"**：**否**。即使能注入 system prompt，工具 description 仍全量下发，LLM 能看到。

### 推荐方案

**方案 A 最符合用户原则**。set_host_tools 全量替换语义已在 omp 源码中证实（`host-tools.ts:87-89`），可在 session 运行中多次调用（`agent-session.ts:5218` 注释 "before the next model call"）。free mode 启动时只注册 xhs_free_* + account-bound 通用工具子集，LLM 看不到 thread-bound 工作流工具的 description。

同时需配合去除编排内容（问题 5/6 中的步骤编号、next: cue、guide 编排文本），使工具 description 只描述原子能力。

---

## Caveats / Not Found

1. **TS extension 路径改造未深入**：TS extension 注册全部工作流工具且无 mode 过滤（`index.ts:52-112`），但 Web TUI free mode 不走此路径。如果 omp CLI 直接使用时也需按 mode 过滤工具，TS extension 需额外改造（ExtensionAPI 是否支持运行时 unregister tool 未查）。

2. **mode 切换时的 session 复用问题**：如果用户先在 free mode 用 session A，然后切到 trend mode 带 session_id=A 重连，get_or_create_session 会返回已有 session（工具集是 free 子集）。需在 get_or_create_session 中检测 mode 不匹配并重发工具或重建 session。当前 get_or_create_session 无 mode 参数，需新增。

3. **xhs_free_guide 工具的存废**：guide 文本核心是编排（步骤 1-4 + revise loop）。按新原则，编排交给 omp，guide 可能应删除或改为只含护栏的精简版。但 guide 也是 agent 发现工具链的主要途径（spec `free-creation.md:122-127` 描述 guide 为 discovery 机制），删除后 agent 如何发现工具用法需考虑。

4. **render 中的 next:/note: cue 去留**：spec (`free-creation.md:57-113`) 明确要求 render 含 next:/note: cue。按新原则，next: cue（编排）应删，note: cue（mock/degraded/failure 护栏）应留。但 spec 文档需同步更新，否则 spec 与代码不一致。

5. **spec 中的 atomic-tool principle 已存在**：`free-creation.md:174` 已写 "Atomic-tool principle (free mode): free-mode host tools expose only atomic data operations... They carry no orchestration"。但当前工具 description 和 render 中的编排内容违反了这条 spec。说明 spec 先于代码写了原则，但实现未跟上。
