# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

XhsGrowthAgent is a LangGraph-based multi-agent system for automating content growth on Xiaohongshu (小红书). It orchestrates a full workflow: trend scouting → content strategy → copywriting → visual design → human review → publishing → analytics → engagement.

## Development Commands

```bash
# Install dependencies
pip install -e ".[dev,browser]"

# Run CLI workflow (with progress visualization)
xhs-growth run --account-id my_account --phase scouting

# Run with verbose logging
xhs-growth run --verbose

# Run with dry-run (no real API calls)
xhs-growth run --dry-run

# Start API server
xhs-growth serve --port 8000

# Check workflow status (enhanced with table output)
xhs-growth status <thread_id>

# Resume interrupted workflow
xhs-growth resume <thread_id>

# View workflow logs
xhs-growth logs <thread_id>

# Check configuration status
xhs-growth config

# Show version info
xhs-growth version

# Run tests
pytest

# Run single test
pytest tests/test_graph.py -v

# Lint
ruff check .

# Format
ruff format .

# Type check
mypy backend
```

## Architecture

### Directory Structure (2026-05-27 Refactor)

The project follows a clear layered architecture with `backend` as the core package:

```
backend/
├── core/           # Base infrastructure (BaseAgent, error handling, validators)
├── agents/         # Business logic
│   ├── nodes/      # Node functions (split from graph/nodes.py)
│   │   └── optimization/  # Pre-publish optimization nodes
│   └── mixins/     # Agent capabilities (retry, validation, memory)
├── services/       # Tool orchestration layer
├── tools/          # Atomic operations
├── graph/          # Topology definition only
├── state/          # TypedDict schemas
├── api/            # FastAPI routes with unified responses
│   ├── routes/     # Workflow, review, analytics, realtime
│   └── responses.py # ApiResponse envelope
├── realtime/       # WebSocket + SSE event streaming
├── memory/         # Long-term memory (store, index, creative, types)
├── cli/            # Typer CLI with Rich progress
├── config/         # Model routing, prompts
└── omp/            # oh-my-pi terminal agent extensions
    └── extensions/
        └── xhsagent-ext/  # XhsGrowthAgent tools for omp TUI

frontend/
├── src/
│   ├── views/      # Dashboard (32 lines, split into 5 components) + AgentTUI
│   ├── components/ # Reusable Vue components
│   ├── stores/     # Pinia stores with toast notifications
│   └── realtime/   # WebSocket client with event recovery
```

**Import paths:**
```python
# Main package
from backend import XHSGrowthState, compile_graph_dev, WorkflowPhase

# Core
from backend.core import BaseAgent, AgentError, handle_agent_error

# Agents
from backend.agents import OrchestratorAgent, TrendScoutAgent
from backend.agents.nodes import orchestrator_node

# Services
from backend.services import XHSClient, RippleService

# Models
from backend.models import get_model, CostTracker

# State
from backend.state import merge_dict, append_list

# Tools
from backend.tools.content import layout_recommender, style_library
from backend.tools.analysis import topic_scorer

# Memory
from backend.memory import MemoryManager, CreativeMemory, get_store_index, get_prod_store_index

# API responses
from backend.api.responses import success, error
```

**Key changes from refactor:**
- Directory renamed from `xhs_growth` to `backend` for clearer naming
- Node functions moved from `graph/nodes.py` to `agents/nodes/`
- Dashboard.vue split into 5 sub-components (WorkflowHeader, WorkflowTimeline, ContentCards, OptimizationPanel, ActionButtons)
- Service layer added for tool orchestration
- CLI enhanced with progress bars, toast notifications, and new commands
- API enhanced with SSE streaming, cancel endpoint, and progress tracking
- Memory module added with semantic search index and creative memory layers

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

### Agent Base Class (core/base_agent.py)

All agents inherit from `BaseAgent`:
- Define `task_type: TaskType`, `agent_name: str`, `prompt_file: str`
- Prompt loaded from `backend/config/prompts/<agent>.yaml`
- `execute(state, store)` returns dict of state updates
- Model routed via `get_model(task_type.value)` from `models/router.py`

### CLI Commands (cli/main.py)

Typer-based CLI with Rich progress visualization:
- `run`: Start workflow with progress bar and spinner
- `serve`: Start API server with uvicorn
- `status`: View workflow status in table format
- `resume`: Resume interrupted workflow
- `logs`: View workflow messages and performance log
- `list`: List active workflows (placeholder for Postgres)
- `version`: Show version info
- `config`: Check environment configuration

### API Routes (api/routes/)

FastAPI routes with unified `ApiResponse` envelope:

**Workflow routes (`workflow.py`):**
- `POST /start`: Start workflow (async_mode, SSE/WebSocket URLs)
- `GET /status/{thread_id}`: Get status with progress_percent
- `POST /pause/{thread_id}`: Pause workflow
- `POST /resume/{thread_id}`: Resume workflow
- `POST /cancel/{thread_id}`: Cancel workflow
- `GET /stream/{thread_id}`: SSE progress streaming
- `GET /list`: List workflows (placeholder)

**Realtime routes (`realtime.py`):**
- `WS /ws`: WebSocket with subscribe/unsubscribe/ping/get_missed
- `GET /events/missed`: HTTP recovery for lost events

**System routes (`system.py`):**
- `GET /health`: System health check (see Health Check section below)

### Frontend Stores (frontend/src/stores/)

Pinia stores with toast notifications:
- `workflow.ts`: Progress tracking (0-100), phase change notifications
- `realtime.ts`: WebSocket connection with event recovery
- `toast.ts`: Success/error/warning/info notifications

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

### Memory Store (memory/)

LangGraph BaseStore integration with namespaces per account, semantic search, and creative memory layers.

**Index Configuration (`memory/index.py`):**
- `IndexConfig` with direct `Embeddings` object construction (not string-based resolution)
- Supported providers: `openai`, `openai_compatible`, `local`
- Env vars: `XHS_EMBED_MODEL` (default: `openai:text-embedding-3-small`), `XHS_EMBED_DIMS` (default: 1536), `XHS_EMBED_BASE_URL` (for OpenAI-compatible APIs like DeepSeek)
- `get_store_index()`: Returns `IndexConfig | None` — falls back to `None` when no API key is available (store operates without semantic search)
- `get_prod_store_index()`: Same as above but adds `distance_type: "cosine"` for Postgres store
- `_build_embeddings()`: Constructs `OpenAIEmbeddings` (openai/openai_compatible) directly from `langchain_openai`, or `HuggingFaceEmbeddings` (local) from `langchain_huggingface` — bypassing the langchain meta-package string resolution
- `local` provider: Runs embedding inference on CPU via `sentence-transformers` / `langchain-huggingface`. No API key required. Model weights downloaded on first use (cached under `~/.cache/huggingface`). Set `HF_ENDPOINT` to a mirror (e.g. `https://hf-mirror.com`) if HuggingFace Hub is unreachable. When switching embedding dimensions, the Postgres `store_vectors` table must be cleared (old vectors are incompatible with new dimensions).
- Indexed fields: title, body, insight, note, preference, content, tone, visual_style, topic, tags, hashtag_style, trigger_condition, title_formula, opening_hook, niche, category, voice_patterns, layout_preference

**MemoryManager (`memory/store.py`):**
- Namespace-based memory with semantic + keyword search
- All recall methods accept `keywords: list[str] | None` and `filter: dict | None` params:
  - `recall_similar_content(store, query, limit, *, keywords, filter)`
  - `recall_audience_preferences(store, query, limit, *, keywords, filter)`
  - `recall_insights(store, query, limit, *, keywords, filter)`
  - `recall_strategy_notes(store, query, limit, *, keywords, filter)`
- `_keyword_filter(items, keywords)`: Post-filters asearch results — all keywords must appear in any string value field (case-insensitive text-contains match)
- `asearch(filter=)`: Passes `filter` dict directly for exact field matching (e.g. `{"tone": "治愈"}`)
- Over-fetches by `limit * 2` when keywords are provided, to compensate for post-filtering
- Write methods: `store_content_record`, `store_insight`, `store_audience_preference`, `store_strategy_note`

**CreativeMemory (`memory/creative.py`):**
- Three-layer creative memory: style DNA, conversion playbook, material vault
- Namespaces: `accounts/{id}/style_dna`, `accounts/{id}/conversion_playbook`, `accounts/{id}/material_vault`, `benchmarks/{niche}`
- Recall methods with same `keywords`/`filter` params:
  - `recall_style(query, limit, *, keywords, filter)` — returns `StyleDNA` list, falls back to default styles
  - `recall_plays(condition, niche, limit, *, keywords, filter)` — returns `ConversionPlay` list
  - `recall_materials(category, tags, limit, *, keywords, filter)` — returns `MaterialEntry` list, sorted by weight
- `calibrate(payload)`: Updates engagement rates, proven counts, and effectiveness using `aget(namespace, key=id)` for direct ID lookup (not asearch) — more reliable when semantic search is disabled or data volume is large
- Deposit methods: `deposit_style` (merges similar styles), `deposit_play`, `deposit_material`, `deposit_benchmark`
- Cold-start threshold: `MIN_SAMPLES = 5`; soft downgrade: effectiveness < 0.3 reduces weight by 0.8x

**Postgres Store:**
- Uses `pgvector/pgvector:pg15` Docker image (not `postgres:15`) — required for vector similarity support
- `AsyncPostgresStore` creates `store_vectors` table with HNSW index for cosine similarity
- Configured via `XHS_POSTGRES_URI` or `POSTGRES_URI` env var
- `compile_graph_prod()` and `compile_graph_dev()` both support Postgres store with semantic index

### Health Check (`/api/system/health`)

System health endpoint checks all external dependencies:
- `llm_providers`: API key availability for Anthropic, OpenAI, DeepSeek, DashScope
- `xhs_platform`: XHS cookie and user ID (optional — preview-only without it)
- `ripple_cas`: Ripple CAS engine connectivity
- `search_api`: Tavily API key
- `database`: Checkpointer mode detection (postgres/sqlite/memory)
- `memory_store`: Backend type (postgres/memory/unavailable), semantic index status (enabled/disabled), embed model name, embed dimensions, namespace counts with total items

Overall status: `ok` if LLM providers are configured; `degraded` if memory store lacks semantic index; `warning` if memory store is unavailable.

## Module Structure

All modules have proper `__init__.py` exports for clean imports:

```python
# Main package
from backend import XHSGrowthState, compile_graph_dev, WorkflowPhase

# Core
from backend.core import BaseAgent, AgentError, handle_agent_error

# Agents
from backend.agents import OrchestratorAgent, TrendScoutAgent
from backend.agents.nodes import orchestrator_node

# Services
from backend.services import XHSClient, RippleService

# Models
from backend.models import get_model, CostTracker

# State
from backend.state import merge_dict, append_list

# Tools
from backend.tools.content import layout_recommender, style_library
from backend.tools.analysis import topic_scorer

# Memory
from backend.memory import MemoryManager, CreativeMemory, get_store_index, get_prod_store_index

# API responses
from backend.api.responses import success, error
```

## Environment Setup

Required environment variables (see `.env.example`):
- `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `DEEPSEEK_API_KEY`, `DASHSCOPE_API_KEY` — LLM providers
- `XHS_COOKIE`, `XHS_USER_ID` — Xiaohongshu platform access
- `RIPPLE_BASE_URL`, `RIPPLE_API_TOKEN` — Ripple CAS engine
- `POSTGRES_URI`, `REDIS_URI` — Production persistence
- `XHS_EMBED_MODEL`, `XHS_EMBED_DIMS`, `XHS_EMBED_BASE_URL` — Memory store semantic search (optional; defaults to `openai:text-embedding-3-small`, 1536 dims). Use `local:BAAI/bge-small-zh-v1.5` with `XHS_EMBED_DIMS=512` for on-device CPU embedding (no API key needed; requires `langchain-huggingface` + `sentence-transformers`)

## Deployment

Deploy using `scripts/deploy.sh` (not manual `podman run`):
- The script reads `.env` and passes all env vars to containers
- Postgres container must use `pgvector/pgvector:pg15` image (not `postgres:15`) for vector similarity support
- Embedding env vars (`XHS_EMBED_MODEL`, `XHS_EMBED_DIMS`, `XHS_EMBED_BASE_URL`) are passed to the backend container for semantic search
- `HF_ENDPOINT` (default: `https://hf-mirror.com`) is passed to the backend container for HuggingFace model downloads when using the `local` embedding provider
- The bge-small-zh-v1.5 model is **baked into the image** as a seed at `/opt/hf-cache-seed` (via `COPY .hf-cache` in the Dockerfile — the `.hf-cache/` dir on the host holds a one-time download; build containers can't reliably reach the HF mirror, so baking is offline). At runtime `HF_HOME=/opt/hf-cache` and the host dir `/test/xhs/.hf-cache` is bind-mounted there. `scripts/container-entrypoint.sh` seeds the mount from the image copy on first run (when the mount is empty), giving zero runtime network dependency + a host-visible, rebuild-persistent cache.
- Model file locations: host `/test/xhs/.hf-cache/hub/models--BAAI--bge-small-zh-v1.5/`, container mount `/opt/hf-cache` (`HF_HOME`), image seed `/opt/hf-cache-seed`. `.hf-cache/` is gitignored.
- When switching embedding dimensions (e.g. 1536 → 512), clear the Postgres `store_vectors` table first: `podman exec postgres-xhs psql -U xhs -d xhs_growth -c "TRUNCATE store_vectors;"`
- Without embedding config, the store operates in degraded mode (namespace recency only, no semantic search)

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
- Contract tests verify OpenAPI spec sync (`tests/contract/test_type_sync.py`)
- Ripple service tests cover singleton, health check, retry, fallback (`tests/unit/services/test_ripple_service.py`)
- Memory tests: index config (`tests/unit/memory/test_index.py`), store (`tests/unit/memory/test_store.py`), creative memory (`tests/unit/memory/test_creative_memory.py`)

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
