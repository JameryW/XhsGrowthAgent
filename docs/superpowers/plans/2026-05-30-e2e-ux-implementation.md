# End-to-End UX Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix end-to-end state consistency, review/publish pipeline, analytics period sync, and Dashboard UX across the XHS Growth Agent system.

**Architecture:** The system is a LangGraph multi-agent workflow with FastAPI backend and Vue 3 frontend. State flows through TypedDict, realtime events via EventBus→WebSocket, and human review via interrupt/resume. Changes are surgical — fixing specific inconsistencies without restructuring.

**Tech Stack:** Python 3.12, FastAPI, LangGraph, Vue 3, Pinia, TypeScript, vue-i18n

---

## File Structure

### Backend files to modify

| File | Change |
|------|--------|
| `backend/api/routes/workflow.py:171-193` | Add `thread_id` to initial_state, pass `dry_run`/`auto_publish` |
| `backend/state/schema.py:27-87` | Add `thread_id`, `publish_options`, `dry_run`, `auto_publish` fields |
| `backend/agents/nodes/orchestrator.py:23-31` | Emit WORKFLOW_STARTED event on first run |
| `backend/agents/nodes/publisher.py:14-28` | Emit WORKFLOW_AGENT_STARTED/COMPLETED events |
| `backend/graph/routers.py:45-58` | Ensure `__end__` mapping is explicit for rejected |
| `backend/api/routes/review.py:99-103` | Ensure publish_options defaults are conservative |

### Frontend files to modify

| File | Change |
|------|--------|
| `frontend/src/stores/analytics.ts:127-130` | Fix `setPeriod()` to refresh all data |
| `frontend/src/stores/workflow.ts:69-121` | Add WORKFLOW_STARTED handler, improve error handling |
| `frontend/src/views/Review.vue:233-238` | Pass `auto_publish` from UI state |
| `frontend/src/locales/en.json` | Add missing keys |
| `frontend/src/locales/zh-CN.json` | Add missing keys |

---

## Milestone 1: State Credibility (P0)

### Task 1: Add `thread_id` to workflow initial state

**Files:**
- Modify: `backend/api/routes/workflow.py:171-193`
- Modify: `backend/state/schema.py:27-87`

- [ ] **Step 1: Add `thread_id` field to XHSGrowthState**

In `backend/state/schema.py`, add `thread_id: str` after `session_id`:

```python
    # Metadata
    account_id: str
    session_id: str
    thread_id: str
    created_at: str
    updated_at: str
```

- [ ] **Step 2: Write `thread_id` in workflow start initial_state**

In `backend/api/routes/workflow.py`, add `thread_id` to `initial_state` dict (line ~188):

```python
    initial_state = {
        "phase": req.phase,
        "current_agent": "orchestrator",
        "error": None,
        "retry_count": 0,
        "messages": [],
        "trend_data": {},
        "content_plan": {},
        "copy_content": {},
        "visual_plan": {},
        "publish_result": {},
        "analytics": {},
        "engagement_actions": [],
        "human_feedback": {},
        "content_history": [],
        "performance_log": [],
        "account_id": req.account_id,
        "session_id": thread_id,
        "thread_id": thread_id,
        "topic": req.topic,
        "niche": req.niche,
        "dry_run": req.dry_run,
        "auto_publish": req.auto_publish,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
```

- [ ] **Step 3: Verify no import errors**

Run: `python -c "from backend.state.schema import XHSGrowthState; print('OK')"`
Expected: OK

- [ ] **Step 4: Commit**

```bash
git add backend/state/schema.py backend/api/routes/workflow.py
git commit -m "fix: add thread_id and publish flags to workflow initial state"
```

### Task 2: Emit WORKFLOW_STARTED event from orchestrator

**Files:**
- Modify: `backend/agents/nodes/orchestrator.py:15-33`

- [ ] **Step 1: Add WORKFLOW_STARTED emission on first orchestrator run**

The orchestrator runs first in every workflow. Emit `WORKFLOW_STARTED` when `current_agent` is not yet set (first run):

```python
async def orchestrator_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    """Execute orchestrator agent and emit phase change event."""
    result = await _orchestrator(state, store=store)

    thread_id = state.get("session_id")
    event_bus = EventBusService.get_instance()

    # Emit workflow started event on first orchestrator run
    if not state.get("current_agent"):
        event_bus.emit(
            EventType.WORKFLOW_STARTED,
            thread_id=thread_id,
            payload={
                "phase": result.get("phase", state.get("phase")),
                "account_id": state.get("account_id"),
                "dry_run": state.get("dry_run", True),
            },
        )

    # Emit phase change event if phase changed
    old_phase = state.get("phase")
    new_phase = result.get("phase")
    if new_phase and new_phase != old_phase:
        event_bus.emit(
            EventType.WORKFLOW_PHASE_CHANGED,
            thread_id=thread_id,
            payload={
                "old_phase": old_phase,
                "new_phase": new_phase,
                "current_agent": result.get("current_agent", "orchestrator"),
            },
        )

    return NodeResult(result, "orchestrator").to_dict()
```

- [ ] **Step 2: Commit**

```bash
git add backend/agents/nodes/orchestrator.py
git commit -m "feat: emit WORKFLOW_STARTED event on first orchestrator run"
```

### Task 3: Add WORKFLOW_STARTED handler to frontend workflow store

**Files:**
- Modify: `frontend/src/stores/workflow.ts:66-121`

- [ ] **Step 1: Add WORKFLOW_STARTED event handler**

After the existing `WORKFLOW_ERROR` handler (line ~121), add:

```typescript
  realtimeStore.wsService.onEvent(EventType.WORKFLOW_STARTED, (msg) => {
    if (msg.thread_id === currentThreadId.value) {
      const p = msg.payload as { phase?: string; account_id?: string; dry_run?: boolean }
      // Update workflow state with initial info
      if (workflowState.value) {
        workflowState.value = {
          ...workflowState.value,
          phase: (p.phase || 'scouting') as WorkflowPhase,
          current_agent: 'orchestrator',
        }
      }
      updateProgressFromPhase((p.phase || 'scouting') as WorkflowPhase)
    }
  })
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/stores/workflow.ts
git commit -m "feat: handle WORKFLOW_STARTED event in frontend workflow store"
```

### Task 4: Verify realtime event contract

**Files:**
- Create: `tests/unit/realtime/test_event_contract.py`

- [ ] **Step 1: Write event contract test**

```python
"""Tests for realtime event payload contracts."""
import pytest
from backend.realtime.events import Event, EventType


class TestEventContract:
    """Verify event payloads match frontend expectations."""

    def test_workflow_phase_changed_has_required_fields(self):
        event = Event(
            event_type=EventType.WORKFLOW_PHASE_CHANGED,
            thread_id="test_123",
            payload={
                "old_phase": "scouting",
                "new_phase": "planning",
                "current_agent": "orchestrator",
            },
            timestamp="2026-05-30T00:00:00Z",
            seq=0,
        )
        d = event.to_dict()
        assert d["event_type"] == "workflow.phase_changed"
        assert d["thread_id"] == "test_123"
        assert "old_phase" in d["payload"]
        assert "new_phase" in d["payload"]
        assert "current_agent" in d["payload"]

    def test_workflow_data_updated_has_required_fields(self):
        event = Event(
            event_type=EventType.WORKFLOW_DATA_UPDATED,
            thread_id="test_123",
            payload={"data_type": "trend_data", "data": {"hot_topics": []}},
            timestamp="2026-05-30T00:00:00Z",
            seq=1,
        )
        d = event.to_dict()
        assert d["event_type"] == "workflow.data_updated"
        assert "data_type" in d["payload"]
        assert "data" in d["payload"]

    def test_review_pending_has_required_fields(self):
        event = Event(
            event_type=EventType.REVIEW_PENDING,
            thread_id="test_123",
            payload={
                "content_plan": {"selected_topic": "test"},
                "copy_content": {"selected_title": "title"},
                "visual_plan": {"layout_style": "grid"},
            },
            timestamp="2026-05-30T00:00:00Z",
            seq=2,
        )
        d = event.to_dict()
        assert d["event_type"] == "review.pending"
        assert "content_plan" in d["payload"]
        assert "copy_content" in d["payload"]
        assert "visual_plan" in d["payload"]

    def test_workflow_started_has_required_fields(self):
        event = Event(
            event_type=EventType.WORKFLOW_STARTED,
            thread_id="test_123",
            payload={
                "phase": "scouting",
                "account_id": "default",
                "dry_run": True,
            },
            timestamp="2026-05-30T00:00:00Z",
            seq=3,
        )
        d = event.to_dict()
        assert d["event_type"] == "workflow.started"
        assert "phase" in d["payload"]
        assert "dry_run" in d["payload"]
```

- [ ] **Step 2: Run test**

Run: `pytest tests/unit/realtime/test_event_contract.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/unit/realtime/test_event_contract.py
git commit -m "test: add realtime event payload contract tests"
```

---

## Milestone 2: Review & Publish Consistency (P0)

### Task 5: Ensure publish_options flow through review to publisher

**Files:**
- Modify: `backend/api/routes/review.py:99-103`
- Verify: `backend/agents/publisher.py:34-35`

- [ ] **Step 1: Ensure conservative defaults in review.py**

The current code at `review.py:99-103` already writes `publish_options` to state on approval. Verify the defaults are conservative — if `publish_options` is None, default to `dry_run=True`:

```python
    # On 'approved', write publish options to state so publisher can read them
    if decision.decision == "approved":
        pub_opts = decision.publish_options or PublishOptions(dry_run=True)
        await graph.aupdate_state(config, {
            "publish_options": pub_opts.model_dump(),
        })
```

- [ ] **Step 2: Verify publisher reads publish_options correctly**

The publisher at `backend/agents/publisher.py:34-35` already reads:
```python
publish_options = state.get("publish_options") or {}
is_dry_run = publish_options.get("dry_run", True)
```

This is correct — defaults to dry_run=True if no options present. No change needed.

- [ ] **Step 3: Commit**

```bash
git add backend/api/routes/review.py
git commit -m "fix: ensure publish_options default to dry_run=True on approval"
```

### Task 6: Add dry_run state to XHSGrowthState schema

**Files:**
- Modify: `backend/state/schema.py:27-87`

- [ ] **Step 1: Add publish_options and dry_run fields**

After the existing metadata fields, add:

```python
    # Publish options (set by review decision)
    publish_options: dict
    dry_run: bool
    auto_publish: bool
```

- [ ] **Step 2: Commit**

```bash
git add backend/state/schema.py
git commit -m "feat: add publish_options and dry_run to state schema"
```

### Task 7: Add review submit confirmation toast with next phase

**Files:**
- Modify: `frontend/src/views/Review.vue:225-248`

- [ ] **Step 1: Improve post-submit feedback**

The current code shows a generic success toast. Enhance it to show the actual next phase:

```typescript
const executeDecision = async (decision: ContentStatus) => {
  selectedDecision.value = decision
  error.value = null
  isSubmitting.value = true
  showConfirmModal.value = false
  showPublishConfirm.value = false

  try {
    const feedback = buildFeedback(decision)
    const publishOpts = decision === 'approved'
      ? { dry_run: publishDryRun.value, auto_publish: false }
      : undefined
    const result = await reviewStore.submitDecision(decision, feedback, undefined, publishOpts)

    // Show decision-specific feedback
    if (decision === 'approved') {
      const mode = publishDryRun.value ? t('review.publishConfirm.dryRun') : t('review.publishConfirm.liveWarning')
      toastStore.success(t('review.success'), `${t('review.decisionLabel')}: ${decision} · ${mode}`)
    } else if (decision === 'rejected') {
      toastStore.warning(t('review.success'), `${t('review.decisionLabel')}: ${decision}`)
    } else {
      toastStore.info(t('review.success'), `${t('review.decisionLabel')}: ${decision}`)
    }

    router.push('/dashboard')
  } catch (e: any) {
    error.value = e.message || t('review.submitFailed')
    toastStore.error(t('review.submitFailedTitle'), e.message)
  } finally {
    isSubmitting.value = false
    pendingDecision.value = null
  }
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/views/Review.vue
git commit -m "fix: show decision-specific toast after review submission"
```

---

## Milestone 3: Dashboard & Console Experience (P1)

### Task 8: Fix analytics setPeriod() to refresh all data

**Files:**
- Modify: `frontend/src/stores/analytics.ts:127-130`

- [ ] **Step 1: Fix setPeriod to refresh all data sources**

The current `setPeriod` only calls `fetchReport()`, leaving performance and cost data stale:

```typescript
  function setPeriod(p: 'daily' | 'weekly' | 'monthly') {
    period.value = p
    fetchAllData()
  }
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/stores/analytics.ts
git commit -m "fix: refresh all analytics data when period changes"
```

### Task 9: Add WORKFLOW_AGENT_STARTED/COMPLETED events to publisher node

**Files:**
- Modify: `backend/agents/nodes/publisher.py:15-28`

- [ ] **Step 1: Add agent lifecycle events to publisher**

```python
async def publisher_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    """Execute publisher agent and emit workflow completed event."""
    thread_id = state.get("session_id")
    event_bus = EventBusService.get_instance()

    # Emit agent started
    event_bus.emit(
        EventType.WORKFLOW_AGENT_STARTED,
        thread_id=thread_id,
        payload={"agent": "publisher"},
    )

    result = await _publisher(state, store=store)

    # Emit agent completed
    event_bus.emit(
        EventType.WORKFLOW_AGENT_COMPLETED,
        thread_id=thread_id,
        payload={
            "agent": "publisher",
            "status": result.get("publish_result", {}).get("status", "unknown"),
        },
    )

    # Emit workflow completed event after publish
    if result.get("publish_result"):
        event_bus.emit(
            EventType.WORKFLOW_COMPLETED,
            thread_id=thread_id,
            payload={"publish_result": result.get("publish_result")},
        )

    return NodeResult(result, "publisher").to_dict()
```

- [ ] **Step 2: Commit**

```bash
git add backend/agents/nodes/publisher.py
git commit -m "feat: add agent lifecycle events to publisher node"
```

### Task 10: Add WORKFLOW_AGENT_STARTED/COMPLETED events to other key nodes

**Files:**
- Modify: `backend/agents/nodes/trend_scout.py`
- Modify: `backend/agents/nodes/content_strategist.py`
- Modify: `backend/agents/nodes/copywriter.py`
- Modify: `backend/agents/nodes/analyst.py`

- [ ] **Step 1: Add lifecycle events to trend_scout_node**

```python
async def trend_scout_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    """Execute trend scout agent and emit data updated event."""
    thread_id = state.get("session_id")
    event_bus = EventBusService.get_instance()

    event_bus.emit(
        EventType.WORKFLOW_AGENT_STARTED,
        thread_id=thread_id,
        payload={"agent": "trend_scout"},
    )

    result = await _trend_scout(state, store=store)

    event_bus.emit(
        EventType.WORKFLOW_AGENT_COMPLETED,
        thread_id=thread_id,
        payload={"agent": "trend_scout"},
    )

    # Emit data updated event for trend_data
    if result.get("trend_data"):
        event_bus.emit(
            EventType.WORKFLOW_DATA_UPDATED,
            thread_id=thread_id,
            payload={"data_type": "trend_data", "data": result.get("trend_data")},
        )

    return NodeResult(result, "trend_scout").to_dict()
```

- [ ] **Step 2: Add lifecycle events to content_strategist_node**

```python
async def content_strategist_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    """Execute content strategist agent and emit data updated event."""
    thread_id = state.get("session_id")
    event_bus = EventBusService.get_instance()

    event_bus.emit(
        EventType.WORKFLOW_AGENT_STARTED,
        thread_id=thread_id,
        payload={"agent": "content_strategist"},
    )

    result = await _content_strategist(state, store=store)

    event_bus.emit(
        EventType.WORKFLOW_AGENT_COMPLETED,
        thread_id=thread_id,
        payload={"agent": "content_strategist"},
    )

    if result.get("content_plan"):
        event_bus.emit(
            EventType.WORKFLOW_DATA_UPDATED,
            thread_id=thread_id,
            payload={"data_type": "content_plan", "data": result.get("content_plan")},
        )

    return NodeResult(result, "content_strategist").to_dict()
```

- [ ] **Step 3: Add lifecycle events to copywriter_node**

```python
async def copywriter_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    """Execute copywriter agent and emit data updated event."""
    thread_id = state.get("session_id")
    event_bus = EventBusService.get_instance()

    event_bus.emit(
        EventType.WORKFLOW_AGENT_STARTED,
        thread_id=thread_id,
        payload={"agent": "copywriter"},
    )

    result = await _copywriter(state, store=store)

    event_bus.emit(
        EventType.WORKFLOW_AGENT_COMPLETED,
        thread_id=thread_id,
        payload={"agent": "copywriter"},
    )

    if result.get("copy_content"):
        event_bus.emit(
            EventType.WORKFLOW_DATA_UPDATED,
            thread_id=thread_id,
            payload={"data_type": "copy_content", "data": result.get("copy_content")},
        )

    return NodeResult(result, "copywriter").to_dict()
```

- [ ] **Step 4: Add lifecycle events to analyst_node**

```python
async def analyst_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    """Execute analyst agent and emit data updated event."""
    thread_id = state.get("session_id")
    event_bus = EventBusService.get_instance()

    event_bus.emit(
        EventType.WORKFLOW_AGENT_STARTED,
        thread_id=thread_id,
        payload={"agent": "analyst"},
    )

    result = await _analyst(state, store=store)

    event_bus.emit(
        EventType.WORKFLOW_AGENT_COMPLETED,
        thread_id=thread_id,
        payload={"agent": "analyst"},
    )

    if result.get("analytics"):
        event_bus.emit(
            EventType.WORKFLOW_DATA_UPDATED,
            thread_id=thread_id,
            payload={"data_type": "analytics", "data": result.get("analytics")},
        )

    return NodeResult(result, "analyst").to_dict()
```

- [ ] **Step 5: Run existing tests**

Run: `pytest tests/ -v --timeout=30 -x 2>&1 | head -50`
Expected: No failures

- [ ] **Step 6: Commit**

```bash
git add backend/agents/nodes/trend_scout.py backend/agents/nodes/content_strategist.py backend/agents/nodes/copywriter.py backend/agents/nodes/analyst.py
git commit -m "feat: add WORKFLOW_AGENT_STARTED/COMPLETED events to all key nodes"
```

---

## Milestone 4: Analytics & i18n Polish (P1/P2)

### Task 11: Add missing i18n keys for new features

**Files:**
- Modify: `frontend/src/locales/en.json`
- Modify: `frontend/src/locales/zh-CN.json`

- [ ] **Step 1: Add workflow.agentStarted/agentCompleted keys**

In `en.json`, add under `workflow`:
```json
    "agentStarted": "Agent Started",
    "agentCompleted": "Agent Completed",
    "workflowStarted": "Workflow Started"
```

In `zh-CN.json`, add under `workflow`:
```json
    "agentStarted": "Agent 已启动",
    "agentCompleted": "Agent 已完成",
    "workflowStarted": "工作流已启动"
```

- [ ] **Step 2: Add status source indicator keys**

In `en.json`, add under `dashboard.header`:
```json
      "statusSource": "Status Source",
      "realtime": "Real-time",
      "polling": "Polling",
      "snapshot": "Snapshot"
```

In `zh-CN.json`, add under `dashboard.header`:
```json
      "statusSource": "状态来源",
      "realtime": "实时同步",
      "polling": "轮询刷新",
      "snapshot": "历史快照"
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/locales/en.json frontend/src/locales/zh-CN.json
git commit -m "feat: add i18n keys for agent lifecycle and status source"
```

### Task 12: Add agent lifecycle event handlers to frontend

**Files:**
- Modify: `frontend/src/stores/workflow.ts`

- [ ] **Step 1: Add WORKFLOW_AGENT_STARTED/COMPLETED handlers**

After the existing event handlers, add:

```typescript
  realtimeStore.wsService.onEvent(EventType.WORKFLOW_AGENT_STARTED, (msg) => {
    if (msg.thread_id === currentThreadId.value && workflowState.value) {
      const p = msg.payload as { agent?: string }
      workflowState.value = {
        ...workflowState.value,
        current_agent: p.agent || workflowState.value.current_agent,
      }
    }
  })

  realtimeStore.wsService.onEvent(EventType.WORKFLOW_AGENT_COMPLETED, (msg) => {
    if (msg.thread_id === currentThreadId.value && workflowState.value) {
      const p = msg.payload as { agent?: string; status?: string }
      // Update agent timeline if available
      const timeline = workflowState.value.agent_timeline || []
      const existing = timeline.find(e => e.agent === p.agent && !e.completed_at)
      if (existing) {
        existing.completed_at = new Date().toISOString()
        existing.status = p.status || 'success'
      }
    }
  })
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/stores/workflow.ts
git commit -m "feat: handle agent lifecycle events in workflow store"
```

### Task 13: Add i18n keys for review decision feedback

**Files:**
- Modify: `frontend/src/locales/en.json`
- Modify: `frontend/src/locales/zh-CN.json`

- [ ] **Step 1: Add review decision feedback keys**

In `en.json`, add under `review`:
```json
    "decisionApproved": "Content approved",
    "decisionRevision": "Revision requested",
    "decisionRejected": "Content rejected",
    "dryRunMode": "Dry Run",
    "liveMode": "Live"
```

In `zh-CN.json`, add under `review`:
```json
    "decisionApproved": "内容已批准",
    "decisionRevision": "已要求修改",
    "decisionRejected": "内容已拒绝",
    "dryRunMode": "试运行",
    "liveMode": "实时发布"
```

- [ ] **Step 2: Update Review.vue to use new keys**

In `frontend/src/views/Review.vue`, update the `executeDecision` function's toast messages to use the new keys (already done in Task 7).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/locales/en.json frontend/src/locales/zh-CN.json
git commit -m "feat: add review decision feedback i18n keys"
```

---

## Final Verification

### Task 14: Run all tests and verify

- [ ] **Step 1: Run backend tests**

Run: `pytest tests/ -v --timeout=30 2>&1 | tail -20`
Expected: All tests pass

- [ ] **Step 2: Run frontend type check**

Run: `cd frontend && npx vue-tsc --noEmit 2>&1 | tail -20`
Expected: No type errors

- [ ] **Step 3: Run linter**

Run: `ruff check backend/`
Expected: No errors

- [ ] **Step 4: Start backend and verify health endpoint**

Run: `cd /test/xhs && python -m uvicorn backend.api.app:app --port 8001 &`
Then: `curl -s http://localhost:8001/api/system/health | python -m json.tool`
Expected: Health check returns status

- [ ] **Step 5: Final commit if any fixes needed**

```bash
git add -A
git commit -m "fix: address review feedback and final polish"
```
