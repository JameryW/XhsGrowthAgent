# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

XhsGrowthAgent is a LangGraph-based multi-agent system for automating content growth on Xiaohongshu (小红书). It orchestrates a full workflow: trend scouting → content strategy → copywriting → visual design → human review → publishing → analytics → engagement.

## Development Commands

```bash
# Install dependencies
pip install -e ".[dev,browser]"

# Run CLI workflow
xhs-growth run --account-id my_account --phase scouting

# Run with dry-run (no real API calls)
xhs-growth run --dry-run

# Start API server
xhs-growth serve --port 8000

# Check workflow status
xhs-growth status <thread_id>

# Run tests
pytest

# Run single test
pytest tests/test_graph.py -v

# Lint
ruff check .

# Format
ruff format .

# Type check
mypy xhs_growth
```

## Architecture

### New Layered Structure (2026-05-27)

The codebase now follows a clear layered architecture:

```
xhs_growth/
├── core/           # Base infrastructure (BaseAgent, error handling, validators)
├── agents/         # Business logic
│   ├── nodes/      # Node functions (split from graph/nodes.py)
│   │   └── optimization/  # Pre-publish optimization nodes
│   └── mixins/     # Agent capabilities (retry, validation, memory)
├── services/       # Tool orchestration layer
├── tools/          # Atomic operations
├── graph/          # Topology definition only
├── state/          # TypedDict schemas
└── config/         # Model routing, prompts
```

**Import paths:**
- `from xhs_growth.core import BaseAgent`
- `from xhs_growth.agents.nodes import orchestrator_node`
- `from xhs_growth.services import OptimizationService`

**Key changes:**
- Node functions moved from `graph/nodes.py` to `agents/nodes/`
- Dashboard.vue split into 5 sub-components (32 lines from 263)
- Service layer added for tool orchestration

### LangGraph Workflow (graph/builder.py)

The system is a StateGraph with nodes and conditional edges:

```
START → orchestrator → [trend_scout | content_strategist | analyst | engagement | END]
              ↓
        trend_scout → [content_strategist | END]
              ↓
        content_strategist → copywriter → visual_designer → review_gate
              ↓                                           ↓
        review_gate → [publisher | revise_content → copywriter]
              ↓
        publisher → analyst → [orchestrator | END]
              ↓
        engagement → orchestrator
```

- `compile_graph_dev()`: Memory checkpointer, interrupts at `review_gate` for human-in-the-loop
- `compile_graph_prod()`: Postgres checkpointer for persistence

### State Schema (state/schema.py)

`XHSGrowthState` is a TypedDict with workflow control + sub-state models:
- `phase: WorkflowPhase` — idle/scouting/planning/creating/reviewing/publishing/analyzing/engaging/completed/error
- `trend_data, content_plan, copy_content, visual_plan, publish_result, analytics` — per-stage outputs
- `ripple_prediction, ripple_pmf` — Ripple CAS engine results
- `messages: Annotated[list, add_messages]` — LangGraph message reducer
- Lists use `_append_list` reducer, dicts use `_merge_dict` reducer

Reducers imported from `state/reducers.py`:
- `merge_dict`: Shallow merge (right overrides left)
- `append_list`: Append right to left
- `replace`: Simple replacement
- `max_value`: Keep larger value

### Agent Base Class (agents/base.py)

All agents inherit from `BaseAgent`:
- Define `task_type: TaskType`, `agent_name: str`, `prompt_file: str`
- Prompt loaded from `xhs_growth/config/prompts/<agent>.yaml`
- `execute(state, store)` returns dict of state updates
- Model routed via `get_model(task_type.value)` from `models/router.py`

### Model Router (models/router.py)

Routes tasks to different LLM providers by `TaskType`:
- ROUTING/SCOUTING/ENGAGEMENT → `deepseek-chat`
- STRATEGY/WRITING → `claude-sonnet-4-20250514`
- VISUAL/ANALYSIS → `gpt-4o`
- PUBLISHING → `qwen-plus`

Provider support: Anthropic, OpenAI, DeepSeek, DashScope (Qwen).

### Tool Registry (tools/registry.py)

Maps agents to their tools:
- `trend_scout`: xhs_trending, keyword_monitor, competitor_analyzer
- `content_strategist`: topic_scorer, timing_optimizer, calendar_manager, ripple_predict_content_spread, ripple_validate_pmf
- `copywriter`: hashtag_researcher, title_generator, ripple_predict_content_spread
- `visual_designer`: image_prompt_generator, layout_recommender, style_library
- `analyst`: analytics_reader, pattern_detector, report_generator, ripple_get_simulation_result, ripple_generate_report
- `publisher`: xhs_publisher, ab_test_manager, post_scheduler
- `engagement`: comment_replier, dm_handler, escalation_flagger

### Ripple CAS Integration (tools/ripple/client.py)

External simulation engine for content spread prediction and PMF validation:
- `ripple_predict_content_spread`: Predicts viral probability, estimated reach, spread phases
- `ripple_validate_pmf`: Validates product-market fit for content seeding
- Configuration via `RIPPLE_*` env vars (base_url, api_token, enabled)

### Memory Store (memory/store.py)

LangGraph BaseStore integration with namespaces per account:
- Content history, audience preferences, performance insights, strategy notes
- Agents recall via `_recall_memory(store, account_id, query, namespace)`

## Module Structure

All modules have proper `__init__.py` exports for clean imports:

```python
# Main package
from xhs_growth import XHSGrowthState, compile_graph_dev, WorkflowPhase

# Agents
from xhs_growth.agents import OrchestratorAgent, TrendScoutAgent

# Services
from xhs_growth.services import XHSClient, XHSPost

# Models
from xhs_growth.models import get_model, CostTracker

# State
from xhs_growth.state import merge_dict, append_list

# Tools
from xhs_growth.tools.content import layout_recommender, style_library
from xhs_growth.tools.analysis import topic_scorer
```

## Environment Setup

Required environment variables (see `.env.example`):
- `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `DEEPSEEK_API_KEY`, `DASHSCOPE_API_KEY` — LLM providers
- `XHS_COOKIE`, `XHS_USER_ID` — Xiaohongshu platform access
- `RIPPLE_BASE_URL`, `RIPPLE_API_TOKEN` — Ripple CAS engine
- `POSTGRES_URI`, `REDIS_URI` — Production persistence

## Key Patterns

### Adding a New Agent

1. Create `agents/<name>.py` extending `BaseAgent`
2. Add prompt YAML to `config/prompts/<name>.yaml`
3. Register tools in `tools/registry.py:_agent_tools`
4. Add node + edges in `graph/builder.py`
5. Update `TaskType` enum in `config/models.py` if needed
6. Export agent class in `agents/__init__.py`

### Adding a New Tool

1. Create tool file in appropriate `tools/<category>/` subdirectory
2. Use `@tool` decorator from `langchain_core.tools`
3. Register in `ToolRegistry.register()` or `register_many()`
4. Add to agent's tool list in `_agent_tools`
5. Export tool in `tools/<category>/__init__.py`

### Prompt YAML Format

```yaml
system: |
  Agent instructions and role description...
user_template: |
  Template with {placeholders} for state values...
```

## Testing

- `tests/conftest.py`: fixtures for `initial_state`, `mock_llm`, `mock_store`
- Use `pytest-asyncio` (auto mode) for async tests
- Mock LLM responses with JSON content in `MagicMock().content`

## Visual Design Tools (tools/visual/)

### Architecture Overview

The visual design tools implement a data-driven architecture:

1. **VisualDataExtractor** (`extractor.py`): AI-powered extraction of visual patterns from XHS posts
   - `extract_color_palette()`: Extracts primary, secondary, accent colors from images
   - `detect_layout_type()`: Identifies layout patterns (grid, collage, single_focus, split, carousel)
   - `identify_visual_elements()`: Extracts visual elements (text_overlay, product_shot, lifestyle_scene)
   - `classify_visual_style()`: Classifies styles (minimalist, vibrant, warm, cool, editorial)

2. **SceneDatabase** (`database.py`): Scene-based pattern storage with automatic expiry
   - Stores analysis results per scene (food, travel, fashion, beauty, etc.)
   - 7-day expiry for stale data (configurable via `SCENE_ANALYSIS_EXPIRY_DAYS`)
   - Minimum 10 samples required before caching recommendations
   - Provides default fallback recommendations for each scene

3. **VisualAnalysisService** (`service.py`): Coordinates extraction and storage
   - `analyze_scene()`: Fetches posts, extracts patterns, calculates distributions
   - `get_layout_recommendations()`: Returns layout options filtered by content type, image count, style
   - `get_style_recommendations()`: Returns style options filtered by category, with trending boost
   - Uses LLM-based extraction with caching for performance

4. **VisualTypes** (`types.py`): TypedDict models for type safety
   - `ColorPalette`: RGB color values for design consistency
   - `LayoutOption`: Complete layout recommendation with pros/cons, suitability
   - `StyleOption`: Complete style recommendation with color palette
   - `SceneAnalysisResult`: Aggregated analysis per scene with timestamp

### Scene Keyword Mapping

| Scene | XHS Search Keywords |
|-------|---------------------|
| `food` | 美食, 探店, 餐厅 |
| `travel` | 旅游, 旅行攻略, 景点 |
| `fashion` |穿搭, 时尚, OOTD |
| `beauty` | 护肤, 化妆, 美妆 |
| `lifestyle` | 生活, 日常, vlog |
| `fitness` |健身, 运动, 瑜伽 |
| `home_decor` | 家居, 装修, 室内设计 |

### Default Recommendations

**Layout Defaults** (per scene):
- Grid layouts for product showcases
- Collage for lifestyle content
- Single focus for hero shots
- Split for comparison content

**Style Defaults** (per scene):
- Scene-specific color palettes
- Pro/cons based on content type
- Trending scores from historical data

### Integration Points

The tools integrate with:
- `layout_recommender` tool: Calls `VisualAnalysisService.get_layout_recommendations()`
- `style_library` tool: Calls `VisualAnalysisService.get_style_recommendations()`
- XHS API client: Fetches posts for scene analysis
- LLM router: Uses `get_model(TaskType.VISUAL)` for extraction

### Testing

Visual tools have comprehensive test coverage:
- `tests/test_visual_types.py`: Data structure validation
- `tests/test_visual_extractor.py`: Extraction logic tests
- `tests/test_scene_database.py`: Storage and expiry logic
- `tests/test_visual_service.py`: Service coordination tests
- `tests/test_layout_tool.py`: Tool integration tests
- `tests/test_style_tool.py`: Tool integration tests
- `tests/test_visual_integration.py`: Full workflow tests

Run visual tests: `pytest tests/test_visual* tests/test_scene* tests/test_layout* tests/test_style* -v`

---

## Placeholder Tools

Some tools remain as placeholder implementations (return mock data with TODO notes):
- `topic_scorer`: Topic heat scoring
- Various XHS platform tools (trending, publisher, engagement)

These need real implementation before production use.