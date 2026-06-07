# Fix Prod Mode Store and Search Fallback

## Goal

Fix NoneType crash in prod mode and add graceful fallback when search APIs are unconfigured.

## Problems

1. `compile_graph_prod()` doesn't pass `store=InMemoryStore()`, causing `'NoneType' object has no attribute 'asearch'` when agents call `store.asearch`
2. Tavily Search API not configured → trend_scout tools crash instead of using mock data
3. Frontend shows raw error instead of user-friendly message

## Requirements

- Add `store=InMemoryStore()` to `compile_graph_prod()`
- Add Tavily API key to health check
- Add Tavily key to deploy.sh env passthrough
- Graceful fallback in search tools when Tavily is missing

## Acceptance Criteria

- [ ] Workflow runs in prod mode without NoneType crash
- [ ] Tavily missing → trend_scout uses LLM-generated data (not crash)
- [ ] Health check reports Tavily status
- [ ] deploy.sh passes TAVILY_API_KEY
