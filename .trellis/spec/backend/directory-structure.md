# Backend Directory Structure

> How backend code is organized in this project, derived from the actual codebase.

---

## Overview

The `backend/` package is the core of XhsGrowthAgent. It follows a layered architecture where each directory has a single responsibility: agents own business logic, tools are atomic operations, services orchestrate tools, graph defines topology, and state declares schemas. All modules use `__init__.py` to re-export public symbols, enabling clean import paths like `from backend.agents import TrendScoutAgent`.

---

## Directory Layout

```
backend/
├── __init__.py                          # Top-level exports: compile_graph_dev, XHSGrowthState, WorkflowPhase
│
├── core/                                # Base infrastructure
│   ├── __init__.py                      # Exports: BaseAgent, AgentError, WorkflowCancelledError, handle_agent_error
│   ├── base_agent.py                    # BaseAgent ABC — shared logic for all sub-agents
│   └── error_handling.py                # AgentError, WorkflowCancelledError, handle_agent_error
│
├── agents/                              # Business logic — Agent classes
│   ├── __init__.py                      # Exports all *Agent classes + BaseAgent
│   ├── base.py                          # Duplicate BaseAgent (legacy, imports from core)
│   ├── orchestrator.py                  # OrchestratorAgent
│   ├── trend_scout.py                   # TrendScoutAgent
│   ├── content_strategist.py            # ContentStrategistAgent
│   ├── copywriter.py                    # CopywriterAgent
│   ├── visual_designer.py              # VisualDesignerAgent
│   ├── publisher.py                     # PublisherAgent
│   ├── analyst.py                       # AnalystAgent
│   ├── brief_analyzer.py                # BriefAnalyzerAgent
│   ├── shooting_planner.py              # ShootingPlannerAgent
│   ├── viral_matcher.py                 # ViralMatcherAgent
│   ├── content_analyzer.py              # ContentAnalyzerAgent
│   ├── version_generator.py             # VersionGeneratorAgent
│   ├── mixins/                          # Agent capability mixins
│   │   ├── __init__.py                  # Exports: RetryMixin, ValidationMixin, MemoryMixin
│   │   ├── retry_mixin.py
│   │   ├── validation_mixin.py
│   │   └── memory_mixin.py
│   └── nodes/                           # LangGraph node functions (wraps agents)
│       ├── __init__.py                  # Exports all *_node functions + NodeContext, NodeResult
│       ├── _base.py                     # NodeContext, NodeResult, _check_cancelled, emit_error_event
│       ├── orchestrator.py              # orchestrator_node
│       ├── trend_scout.py               # trend_scout_node
│       ├── content_strategist.py         # content_strategist_node
│       ├── copywriter.py                # copywriter_node
│       ├── visual_designer.py           # visual_designer_node
│       ├── publisher.py                 # publisher_node
│       ├── analyst.py                   # analyst_node
│       ├── review_gate.py               # review_gate_node
│       ├── revise_content.py            # revise_content_node
│       ├── brief_analyzer.py            # brief_analyzer_node
│       ├── brief_gate.py                # brief_gate_node
│       ├── shooting_planner.py          # shooting_planner_node
│       └── optimization/                # Pre-publish optimization nodes
│           ├── __init__.py              # Exports: viral_matcher_node, content_analyzer_node, etc.
│           ├── viral_matcher.py         # viral_matcher_node
│           ├── content_analyzer.py      # content_analyzer_node
│           ├── version_generator.py     # version_generator_node
│           ├── draft_gate.py            # draft_gate_node
│           └── choice_gate.py           # choice_gate_node
│
├── services/                            # Tool orchestration layer
│   ├── __init__.py                      # Exports: OptimizationService, RippleService, RippleHealthStatus
│   ├── ripple_service.py                # RippleService (singleton, health check, retry, fallback)
│   ├── optimization_service.py          # OptimizationService
│   ├── xhs_client.py                    # XHS API client
│   ├── xhs_api.py                       # XHS API helpers
│   ├── xhs_publisher.py                 # XHS publishing service
│   ├── xhs_engagement.py                # XHS engagement service
│   ├── xhs_signature.py                 # XHS signature generation
│   ├── visual_analysis.py               # VisualAnalysisService
│   ├── visual_extractor.py              # VisualDataExtractor
│   └── llm_enrichment.py                # LLM enrichment service
│
├── tools/                               # Atomic operations (LangChain @tool)
│   ├── __init__.py                      # Exports: ToolRegistry
│   ├── registry.py                      # ToolRegistry — maps workflow agents to tools
│   ├── content/                         # Content generation tools
│   │   ├── __init__.py                  # Exports: hashtag_researcher, title_generator, etc.
│   │   ├── hashtag_researcher.py        # hashtag_researcher
│   │   ├── title_generator.py           # title_generator
│   │   ├── image_prompt.py              # image_prompt_generator
│   │   ├── layout.py                    # layout_recommender, get_default_layouts
│   │   └── style.py                     # style_library, get_default_styles
│   ├── analysis/                        # Data analysis tools
│   │   ├── __init__.py                  # Exports: detect_content_patterns, generate_growth_report, topic_scorer
│   │   ├── report_generator.py          # detect_content_patterns, generate_growth_report
│   │   └── topic_scorer.py              # topic_scorer
│   ├── ripple/                          # Ripple CAS simulation tools
│   │   ├── __init__.py                  # Exports all ripple_* tool functions
│   │   ├── client.py                    # ripple_predict_content_spread, ripple_validate_pmf, etc.
│   │   └── integration.py              # Ripple integration helpers
│   ├── xhs/                             # Xiaohongshu platform tools
│   │   ├── __init__.py                  # Exports all xhs_* platform tool functions
│   │   ├── trending.py                  # xhs_trending, keyword_monitor, competitor_analyzer
│   │   ├── publisher.py                 # xhs_publisher, ab_test_manager, post_scheduler
│   │   ├── analytics.py                 # analytics_reader, pattern_detector
│   │   └── engagement.py                # Manual-only tools; not registered for workflow agents
│   └── scheduling/                      # Scheduling tools
│       ├── __init__.py                  # Exports: timing_optimizer
│       └── calendar.py                  # timing_optimizer
│
├── graph/                               # Topology definition only
│   ├── __init__.py                      # Re-exports build_graph, compile_graph_*, plus all *_node functions
│   ├── builder.py                       # build_graph(), compile_graph_dev(), compile_graph_prod()
│   ├── routers.py                       # Conditional edge functions (orchestrator_router, should_plan, etc.)
│   └── error_handling.py                # get_retry_policy()
│
├── state/                               # TypedDict schemas + enums + reducers + substates
│   ├── __init__.py                      # Exports all state types, enums, reducers
│   ├── schema.py                        # XHSGrowthState (main TypedDict)
│   ├── enums.py                         # WorkflowPhase, ContentStatus, ContentType, Urgency, WorkflowMode, ExecutionMode
│   ├── reducers.py                      # merge_dict, append_list, replace, max_value
│   ├── substates.py                     # TrendData, ContentPlan, CopyContent, VisualPlan, etc.
│   └── machine.py                       # WorkflowStatus, derive_status
│
├── api/                                 # FastAPI routes with unified responses
│   ├── __init__.py                      # Exports: app, ApiResponse, success, error, error codes
│   ├── app.py                           # FastAPI app factory
│   ├── responses.py                     # ApiResponse, ErrorDetail, success(), error()
│   ├── middleware.py                    # error_handler_middleware
│   ├── deps.py                          # FastAPI dependencies
│   ├── auth.py                          # Auth helpers
│   ├── errors.py                        # APIError, WorkflowNotFoundError, ReviewNotPendingError, ValidationError
│   ├── generated/                       # Auto-generated OpenAPI models
│   │   ├── __init__.py
│   │   └── models.py
│   └── routes/                          # API route modules
│       ├── __init__.py                  # Exports: workflow_router, review_router, analytics_router
│       ├── workflow.py                  # POST /start, GET /status, POST /pause|resume|cancel, GET /stream
│       ├── review.py                    # Human review endpoints
│       ├── analytics.py                 # Analytics endpoints
│       ├── realtime.py                  # WebSocket /ws, SSE /events
│       ├── optimization.py              # Optimization endpoints
│       ├── auth.py                      # Auth endpoints
│       ├── system.py                    # System health endpoints
│       └── _runner.py                   # Workflow runner logic (shared by routes)
│
├── realtime/                            # WebSocket + SSE event streaming
│   ├── __init__.py                      # Exports: EventType, Event, EventBusService, WebSocketManager, WsSession
│   ├── events.py                        # Event, EventType enum
│   ├── event_bus.py                     # EventBusService (singleton)
│   └── websocket.py                     # WebSocketManager, WsSession
│
├── cli/                                 # Typer CLI with Rich progress
│   ├── __init__.py                      # Empty (CLI entry via main.py)
│   └── main.py                          # Typer commands: run, serve, status, resume, logs, list, version, config
│
├── config/                              # Model routing, prompts (YAML), settings
│   ├── __init__.py                      # Exports: TaskType, ModelProvider, ModelConfig, Settings
│   ├── models.py                        # TaskType, ModelProvider, ModelConfig, MODEL_REGISTRY, resolve_model_id
│   ├── settings.py                      # Settings (Pydantic Settings class)
│   ├── scenes/                          # Scene configuration JSON files
│   │   └── food.json
│   └── prompts/                         # Agent prompt YAML files
│       ├── __init__.py
│       ├── orchestrator.yaml
│       ├── trend_scout.yaml
│       ├── content_strategist.yaml
│       ├── copywriter.yaml
│       ├── visual_designer.yaml
│       ├── publisher.yaml
│       ├── analyst.yaml
│       ├── brief_analyzer.yaml
│       ├── shooting_planner.yaml
│       ├── content_analyzer.yaml
│       ├── viral_matcher.yaml
│       ├── version_generator.yaml
│       └── tools/                       # Tool-specific prompt YAML files
│           ├── hashtag_researcher.yaml
│           ├── timing_optimizer.yaml
│           ├── title_generator.yaml
│           └── image_prompt.yaml
│
├── models/                              # LLM model router + cost tracking + visual types
│   ├── __init__.py                      # Exports: get_model, get_router, ModelRouter, CostTracker, visual types
│   ├── router.py                        # ModelRouter, get_model(), get_router()
│   ├── cost_tracker.py                  # CostTracker, TokenUsage
│   └── visual_types.py                  # ColorPalette, LayoutOption, StyleOption, SceneAnalysisResult
│
├── memory/                              # LangGraph BaseStore management
│   ├── __init__.py                      # Exports: MemoryManager, SceneDatabase
│   ├── store.py                         # MemoryManager (namespace management per account)
│   ├── content_history.py               # Content history helpers
│   └── scene_database.py                # SceneDatabase (7-day expiry, per-scene caching)
│
└── omp/                                 # oh-my-pi (omp) terminal agent extensions
    └── extensions/
        └── xhsagent-ext/                # XhsGrowthAgent domain tools for omp TUI
            ├── package.json             # omp extension manifest (omp.extensions entry)
            ├── tsconfig.json
            ├── .gitignore               # Exclude package-lock.json, node_modules
            └── src/
                ├── index.ts             # Extension entry: registers tools, commands, events
                ├── config.ts            # XHS_AGENT_API_BASE env var
                ├── types.ts             # API response types + textResult helper
                ├── api_client.ts        # HTTP + SSE client (unwraps ApiResponse envelope)
                ├── events.ts            # session_start health check + before_agent_start context
                ├── tools/               # omp tools (one file per API endpoint)
                │   ├── workflow_status.ts   # xhs_workflow_status (full snapshot)
                │   ├── workflow_pause.ts
                │   ├── workflow_resume.ts
                │   ├── workflow_cancel.ts
                │   ├── publish_retry.ts     # xhs_publish_retry (publish existing content)
                │   ├── review_approve.ts    # xhs_review_approve (decision: "approved")
                │   └── review_reject.ts     # xhs_review_reject (decision: "needs_revision")
                └── commands/            # omp slash commands
                    ├── xhs.ts              # /xhs — start creation workflow
                    └── xhs_review.ts       # /xhs-review — review pending content
```

---

## Import Paths

Every module uses `__init__.py` to re-export public symbols. This enables short, clean import paths:

```python
# Top-level
from backend import XHSGrowthState, compile_graph_dev, WorkflowPhase

# Agents
from backend.agents import TrendScoutAgent, OrchestratorAgent, BaseAgent

# Nodes
from backend.agents.nodes import trend_scout_node, orchestrator_node
from backend.agents.nodes.optimization import viral_matcher_node, draft_gate_node

# Core
from backend.core import BaseAgent, AgentError, handle_agent_error

# State
from backend.state import XHSGrowthState, WorkflowPhase, merge_dict, append_list
from backend.state.substates import TrendData, ContentPlan

# Tools
from backend.tools import ToolRegistry
from backend.tools.content import hashtag_researcher, title_generator
from backend.tools.ripple import ripple_predict_content_spread
from backend.tools.xhs import xhs_trending
# Manual-only; never supplied to workflow agents.
from backend.tools.xhs import comment_replier

# Services
from backend.services import RippleService, OptimizationService

# Graph (re-exports nodes for backward compatibility)
from backend.graph import build_graph, compile_graph_dev, trend_scout_node

# API
from backend.api.responses import success, error, ApiResponse
from backend.api.errors import WorkflowNotFoundError

# Realtime
from backend.realtime import EventBusService, EventType, WebSocketManager

# Config
from backend.config import TaskType, ModelProvider, Settings

# Models
from backend.models import get_model, CostTracker

# Memory
from backend.memory import MemoryManager, SceneDatabase
```

---

## Where New Files Go

### Adding a New Agent

1. Create `backend/agents/<name>.py` — class named `<PascalCase>Agent` extending `BaseAgent`
2. Create matching node `backend/agents/nodes/<name>.py` — async function named `<snake_case>_node`
3. Add prompt YAML to `backend/config/prompts/<name>.yaml`
4. Add `TaskType` entry in `backend/config/models.py` if needed
5. Register tools in `backend/tools/registry.py:_agent_tools`
6. Add node + edges in `backend/graph/builder.py`
7. Add routing logic in `backend/graph/routers.py` if conditional edges needed
8. Export agent class in `backend/agents/__init__.py`
9. Export node function in `backend/agents/nodes/__init__.py`

**Real example — BriefAnalyzerAgent:**
- Agent: `backend/agents/brief_analyzer.py` → `BriefAnalyzerAgent`
- Node: `backend/agents/nodes/brief_analyzer.py` → `brief_analyzer_node`
- Prompt: `backend/config/prompts/brief_analyzer.yaml`
- TaskType: `BRIEF_ANALYSIS` in `backend/config/models.py`
- Registered in `backend/agents/__init__.py` and `backend/agents/nodes/__init__.py`

### Adding a New Tool

1. Create tool file in `backend/tools/<category>/<name>.py` — use `@tool` decorator from `langchain_core.tools`
2. Export tool function in `backend/tools/<category>/__init__.py`
3. For a workflow-agent tool, register it in `ToolRegistry._agent_tools` in
   `backend/tools/registry.py`; manual-only operator tools must remain importable
   but unregistered (for example, `backend/tools/xhs/engagement.py`)
4. Add tool-specific prompt YAML in `backend/config/prompts/tools/<name>.yaml` if LLM-enriched

**Real example — hashtag_researcher tool:**
- Tool: `backend/tools/content/hashtag_researcher.py` → `hashtag_researcher`
- Exported in: `backend/tools/content/__init__.py`
- Prompt: `backend/config/prompts/tools/hashtag_researcher.yaml`
- Registered for agent `"copywriter"` in `ToolRegistry._agent_tools`

### Adding a New Optimization Node

1. Create node in `backend/agents/nodes/optimization/<name>.py`
2. Create matching agent in `backend/agents/<name>.py`
3. Add prompt YAML in `backend/config/prompts/<name>.yaml`
4. Export in `backend/agents/nodes/optimization/__init__.py`
5. Add node + edges in `backend/graph/builder.py`
6. Add `TaskType` in `backend/config/models.py`

**Real example — viral_matcher optimization node:**
- Agent: `backend/agents/viral_matcher.py` → `ViralMatcherAgent`
- Node: `backend/agents/nodes/optimization/viral_matcher.py` → `viral_matcher_node`
- Prompt: `backend/config/prompts/viral_matcher.yaml`
- TaskType: `VIRAL_MATCHING`
- Exported in `backend/agents/nodes/optimization/__init__.py`

### Adding a New Service

1. Create `backend/services/<name>_service.py` — class named `<PascalCase>Service`
2. Export in `backend/services/__init__.py`

**Real example:**
- `backend/services/ripple_service.py` → `RippleService`
- `backend/services/optimization_service.py` → `OptimizationService`

### Adding a New API Route

1. Create `backend/api/routes/<name>.py` — define `router = APIRouter(prefix="/api/<name>")`
2. Export in `backend/api/routes/__init__.py`
3. Mount in `backend/api/app.py`

### Adding a New State Sub-type

1. Define TypedDict in `backend/state/substates.py`
2. Add field to `XHSGrowthState` in `backend/state/schema.py`
3. Export from `backend/state/__init__.py`

---

## Naming Conventions

### File Naming

| Pattern | Convention | Examples |
|---------|-----------|----------|
| Agent files | `snake_case.py` (matches `agent_name`) | `trend_scout.py`, `brief_analyzer.py` |
| Node files | `snake_case.py` (matches node function name without `_node`) | `trend_scout.py`, `review_gate.py` |
| Service files | `snake_case_service.py` | `ripple_service.py`, `optimization_service.py` |
| Tool files | `snake_case.py` (matches tool function name) | `hashtag_researcher.py`, `topic_scorer.py` |
| Prompt files | `snake_case.yaml` (matches agent file name) | `trend_scout.yaml`, `brief_analyzer.yaml` |
| Route files | `snake_case.py` (matches URL prefix) | `workflow.py`, `analytics.py` |
| Private/base files | `_prefix.py` | `_base.py` in `agents/nodes/`, `_runner.py` in routes |

### Class Naming

| Type | Convention | Examples |
|------|-----------|----------|
| Agent classes | `<PascalCase>Agent` | `TrendScoutAgent`, `BriefAnalyzerAgent`, `ViralMatcherAgent` |
| Service classes | `<PascalCase>Service` | `RippleService`, `OptimizationService`, `EventBusService` |
| State types | `<PascalCase>` (noun) | `TrendData`, `ContentPlan`, `RipplePrediction` |
| Enums | `<PascalCase>` | `WorkflowPhase`, `ContentStatus`, `TaskType` |
| API models | `<PascalCase>` | `ApiResponse`, `ErrorDetail`, `RippleHealthStatus` |

### Function Naming

| Type | Convention | Examples |
|------|-----------|----------|
| Node functions | `<snake_case>_node` | `trend_scout_node`, `review_gate_node`, `brief_gate_node` |
| Tool functions | `snake_case` (verb or noun) | `hashtag_researcher`, `xhs_trending`, `ripple_predict_content_spread` |
| Router functions | `snake_case` (question form) | `should_plan`, `should_continue`, `should_optimize` |
| Reducer functions | `snake_case` (verb) | `merge_dict`, `append_list`, `replace` |
| Private helpers | `_snake_case` | `_check_cancelled`, `_parse_json_response`, `_fetch_real_data` |

### Tool Naming (LangChain Convention)

Tools follow LangChain's convention of descriptive, often compound names:
- Platform tools prefixed with `xhs_`: `xhs_trending`, `xhs_publisher`
- Ripple tools prefixed with `ripple_`: `ripple_predict_content_spread`, `ripple_validate_pmf`
- Content tools are descriptive nouns: `hashtag_researcher`, `title_generator`, `image_prompt_generator`
- Analysis tools are descriptive: `topic_scorer`, `analytics_reader`, `pattern_detector`

### Agent `agent_name` vs Class Name

The `agent_name` class attribute uses `snake_case` matching the file name, while the class name uses `PascalCase` with `Agent` suffix:

| File | `agent_name` | Class |
|------|-------------|-------|
| `trend_scout.py` | `"trend_scout"` | `TrendScoutAgent` |
| `brief_analyzer.py` | `"brief_analyzer"` | `BriefAnalyzerAgent` |
| `viral_matcher.py` | `"viral_matcher"` | `ViralMatcherAgent` |

This `agent_name` string is used in `ToolRegistry._agent_tools` keys, `current_agent` state field, and logging.

### Prompt YAML Structure

Every prompt YAML has two keys:

```yaml
system: |
  Agent instructions and role description...
  {memory_context}   # optional placeholder for memory recall
  {account_niche}    # optional placeholder for account niche

user_template: |
  Template with {placeholders} for state values...
```

The `prompt_file` attribute on the agent class matches the YAML filename: `prompt_file = "trend_scout.yaml"` loads `backend/config/prompts/trend_scout.yaml`.

### Node Function Signature

All node functions follow the same async signature required by LangGraph:

```python
async def <name>_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
```

They instantiate the agent as a module-level singleton, call `_check_cancelled(state)`, execute the agent, emit events, and wrap the result in `NodeResult(result, "agent_name").to_dict()`.

---

## Key Examples with Real File Paths

### Full Agent + Node Pair

**Agent** (`backend/agents/trend_scout.py`):
```python
class TrendScoutAgent(BaseAgent):
    task_type = TaskType.SCOUTING
    agent_name = "trend_scout"
    prompt_file = "trend_scout.yaml"

    async def execute(self, state: XHSGrowthState, store: BaseStore) -> dict[str, Any]:
        ...
```

**Node** (`backend/agents/nodes/trend_scout.py`):
```python
_trend_scout = TrendScoutAgent()

async def trend_scout_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    _check_cancelled(state)
    result = await _trend_scout(state, store=store)
    return NodeResult(result, "trend_scout").to_dict()
```

### Tool Registration

**Tool definition** (`backend/tools/content/hashtag_researcher.py`):
```python
@tool
async def hashtag_researcher(keyword: str, ...) -> dict:
    ...
```

**Registry mapping** (`backend/tools/registry.py`):
```python
_agent_tools: dict[str, list[str]] = {
    "copywriter": ["hashtag_researcher", "title_generator", "ripple_predict_content_spread"],
    ...
}
```

### Graph Topology

**Builder** (`backend/graph/builder.py`):
```python
builder.add_node("trend_scout", trend_scout_node, retry_policy=get_retry_policy("trend_scout"))
builder.add_conditional_edges("trend_scout", should_plan, {
    "content_strategist": "content_strategist",
    "__end__": END,
})
```

### State Definition

**Schema** (`backend/state/schema.py`):
```python
class XHSGrowthState(TypedDict, total=False):
    phase: WorkflowPhase
    trend_data: TrendData
    messages: Annotated[list, add_messages]
    content_versions: Annotated[list[ContentVersion], _append_list]
    brief_content: Annotated[BriefContent, _merge_dict]
```
