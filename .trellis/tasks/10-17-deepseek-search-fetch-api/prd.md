# 接入 DeepSeek Search/Fetch API

## Goal

用 DeepSeek 官方 **Search & Fetch** REST（复用 `DEEPSEEK_API_KEY`）补上网页搜索能力，并以 Tavily Search/Extract 作备用；统一 provider 接口接入 Gateway 与 `trend_scout`，health 可观测，失败不炸工作流。

## Decision (ADR-lite)

| Topic | Decision |
|-------|----------|
| MVP 深度 | Client + Gateway tools + health + 接入 `trend_scout` |
| Provider | DeepSeek 优先；`TAVILY_API_KEY` 存在时 Tavily 备用 |
| Tavily 深度 | Search + Extract（分别顶统一 `search` / `fetch`） |
| 抽象 | 统一 `WebSearchProvider` 接口（便于第三家） |
| Health | `search_api` 报告各 key 配置态 + `active_provider` |
| 失败 | DeepSeek 429/5xx/未配置 → fallback Tavily；皆失败 → scout 沿用 LLM 降级 |

## Requirements

1. **`WebSearchProvider` facade**（`search` / `fetch`）+ DeepSeek + Tavily 实现  
2. DeepSeek：`POST /v1/tools/search`、`/v1/tools/fetch`；超时、429/5xx 重试后 fallback  
3. Tavily：Search + Extract，映射到同一结果模型  
4. Gateway tools：`search.web` / `search.fetch`（命名可微调）  
5. `trend_scout`：XHS 不足或需站外语境时调用网页搜索；必要时 Fetch 补正文  
6. `_check_search()` / system_config / `.env.example` / deploy：反映双 provider  
7. 单测：mock HTTP（成功/空结果/错误/fallback）+ scout 接线/降级  

## Acceptance Criteria

* [ ] Search/Fetch 经 facade 可调用并解析官方响应形状  
* [ ] DeepSeek 失败/未配置且 Tavily 可用时自动 fallback  
* [ ] Gateway 可发现并调用 search/fetch tools  
* [ ] `trend_scout` 在合适条件下使用网页搜索结果（非纯占位）  
* [ ] health 含 provider 配置态与 `active_provider`  
* [ ] 双端皆失败时 scout 降级、不中断工作流  
* [ ] 单测覆盖上述路径  

## Definition of Done

* Tests added/updated；lint / typecheck / CI green  
* Docs/notes（configuration / security）更新搜索后端说明  
* Rollout：无 key 时行为与今日一致（LLM/XHS 降级）  

## Technical Approach

* 新模块：`backend/services/web_search/`（protocol + deepseek + tavily + router）  
* Tools：`backend/tools/search/` + `catalog.py` 注册  
* `trend_scout._fetch_real_data`（或等价）调用 facade  
* Health：扩展 `_check_search()`  
* 不引入新重型 SDK；`httpx` + 现有 key  

## Out of Scope

* Responses API 内置 `web_search`（Pro）  
* Tavily Crawl/Map  
* 强制第三家 provider 实现（只留接口）  

## Research References

* [`research/deepseek-search-fetch-api.md`](research/deepseek-search-fetch-api.md) — 官方 Search/Fetch REST、计费/QPS、与 Tavily 对照  

## Open Questions

* （无阻塞项）  
