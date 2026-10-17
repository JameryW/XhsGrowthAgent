# Research: DeepSeek Search / Fetch API

- **Query**: Latest DeepSeek Search/Fetch API (official docs, endpoints, auth, request/response shapes, SDK support, pricing); clarify Search vs Fetch vs tool-calling `web_search`; compare vs Tavily-style APIs for integration choice
- **Scope**: mixed (external official docs + internal Tavily/DeepSeek usage)
- **Date**: 2026-10-17

## Findings

### Product names (what exists as of 2026-10-17)

Three related but distinct offerings exist on DeepSeek’s platform:

| Product | What it is | Auth | Billing |
|---|---|---|---|
| **Search API** | Standalone REST: web search → structured result list. Powered by DeepSeek’s in-house search engine. | Same DeepSeek API key (`Bearer`) | Per successful request (not tokens) |
| **Fetch API** | Standalone REST: fetch one URL → title + Markdown body | Same DeepSeek API key | Per successful request (not tokens) |
| **Built-in `web_search` tool** (Responses / agent integrations) | Server-side tool the model invokes inside a Responses (or Anthropic Messages / Claude Code / Codex / Harness) turn; results injected into context | Same DeepSeek API key | Model tokens + (from 2026-11-01 Beijing) underlying Search/Fetch request fees for Harness/Claude Code/Codex |

Official guide title: **“Search & Fetch”** (`api-docs.deepseek.com/guides/search`). Chinese title: **「网页搜索与抓取」**.

**Not the same as Chat Completions tool-calling alone:** Chat Completions currently documents **function tools only**. Application-controlled search is done by defining a function tool and calling Search/Fetch yourself (or another provider). Server-executed `web_search` is documented on the **Responses API** (and Anthropic-compatible Messages / Claude Code paths), not as a Chat Completions built-in.

---

### Base URL, auth, endpoints

| Item | Value |
|---|---|
| Base URL | `https://api.deepseek.com` |
| Search | `POST https://api.deepseek.com/v1/tools/search` |
| Fetch | `POST https://api.deepseek.com/v1/tools/fetch` |
| Auth header | `Authorization: Bearer <DeepSeek API Key>` |
| Content-Type | `application/json` (required) |

**Key reuse:** Yes — same platform API key as chat/completions (this repo’s `DEEPSEEK_API_KEY`). Docs say both APIs “use the same bearer authentication as the DeepSeek API.” No separate Search-only key is documented.

OpenAI-compatible chat base URL already used in-repo:

```85:93:backend/models/router.py
        case ModelProvider.DEEPSEEK:
            return ChatOpenAI(  # type: ignore[call-arg]
                model=config.model_name,
                temperature=config.temperature,
                max_tokens=config.max_tokens,
                timeout=effective_timeout,
                api_key=SecretStr(api_key),
                base_url="https://api.deepseek.com",
            )
```

---

### Search API — request / response

#### Request body

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `query` | string | Yes | — | 1–128 Unicode chars, not all whitespace; supports query operators |
| `count` | integer | No | `10` | 1–50 |
| `ori_question` | string \| null | No | — | User’s original question (1–128 chars); improves intent; `null` = omit |
| `localization` | string | No | `""` | IP address for localized results |
| `need_content` | boolean | No | `false` | When `false`, each result’s `content` is always `""` |

Unknown request fields are ignored.

#### Query operators (forwarded intact)

| Operator | Example | Effect |
|---|---|---|
| `site:` | `DeepSeek site:github.com` | Restrict to site(s); multi-site via `OR` |
| `-site:` | `DeepSeek -site:example.com` | Exclude site(s) |
| `-` | `DeepSeek -advertisement` | Exclude term |
| `-"..."` | `DeepSeek -"release notes"` | Exclude phrase |
| `"..."` | `DeepSeek "exact phrase"` | Exact phrase |
| `lang:` | `DeepSeek lang:zh,en` | Language codes (comma-separated) |
| `after:` | `DeepSeek after:2025` or `after:2025-01-01` | Published after |
| `before:` | `DeepSeek before:2026` or `before:2026-06-01` | Published before |

#### Response (HTTP 200)

```json
{
  "results": [
    {
      "rerank_score": 2.4,
      "title": "…",
      "url": "https://…",
      "snippet": "…",
      "summary": "…",
      "content": "…",
      "site_name": "…",
      "site_icon": "https://…/favicon.ico",
      "date": "2026-06-01T00:00:00+00:00",
      "authority": 3
    }
  ]
}
```

| Field | Type | Notes |
|---|---|---|
| `results` | array | Empty array when no matches (still HTTP 200; **not billed**) |
| `rerank_score` | number | 0–3; ≥1.5 = high-quality |
| `title` | string | |
| `url` | string | |
| `snippet` | string | ~100–200 chars (UI) |
| `summary` | string | ~600–800 chars (model-oriented) |
| `content` | string | Full page text when `need_content=true` and available; else `""` |
| `site_name` | string \| null | |
| `site_icon` | string \| null | |
| `date` | string \| null | RFC 3339 UTC |
| `authority` | integer | 0–4, or `-1` unknown; ≥3 highly authoritative |

---

### Fetch API — request / response

#### Request body

| Field | Type | Required | Notes |
|---|---|---|---|
| `url` | string | Yes | ≤8192 chars; HTTP/HTTPS with host; **no** username/password |

#### Response (HTTP 200)

```json
{
  "title": "Example article",
  "content": "# Example article\n\nArticle content."
}
```

| Field | Type | Notes |
|---|---|---|
| `title` | string | Empty string if unavailable |
| `content` | string | Page body as Markdown |

Subject to target site availability/access policy. Failures that yield no usable Markdown return **404** (and are not billed).

---

### Errors (OpenAI-compatible envelope)

```json
{
  "error": {
    "message": "'count' must be between 1 and 50",
    "type": "invalid_request_error",
    "param": null,
    "code": "invalid_request_error"
  }
}
```

`param` is always `null`.

| HTTP | Meaning |
|---|---|
| 400 | Invalid headers/body |
| 401 | Missing/invalid API key |
| 402 | Insufficient balance |
| 403 | Fetch rejected by security policy |
| 404 | Fetch: no usable content (blocked, unsupported type, empty Markdown, etc.) |
| 408 | Request body read timeout |
| 413 | Body too large |
| 429 | Search or Fetch QPS exceeded |
| 500 | Internal error |
| 504 | Downstream timeout |

Retry guidance (official): retry **408 / 429 / 5xx** after waiting; for **402** top up first; do **not** retry other 4xx without changing the request. APIs are read-only.

---

### Billing & rate limits

#### Billing (official)

| API | Unit | EN docs price | ZH docs price |
|---|---|---|---|
| Search | Per 1,000 **successful** requests | **$0.75** | **¥5** |
| Fetch | Per 1,000 **successful** requests | **$0.75** | **¥5** |

- Billed **per request**, not by tokens or by `count`.
- Billable only when HTTP **200** **and** a result is produced:
  - Search: non-empty `results`
  - Fetch: page content returned
- Failed requests, empty search results, timeouts: **not billed**.
- `count` does not change price.

**Harness / Claude Code / Codex note:** Server-side tool calls that hit Search/Fetch are **free until 00:00 Beijing time, 2026-11-01**, then per-request billing applies. Standalone REST calls follow the table above (confirm current notice before budgeting).

Rough unit cost: **$0.00075 / successful call** (EN) or **¥0.005 / successful call** (ZH).

#### Rate limits (official)

| API | Account QPS | Notes |
|---|---|---|
| Search | **5** | Account-level (all keys); independent of Fetch and of model concurrency |
| Fetch | **5** | Same; **plus** per-domain QPS (undocumented numeric value); over limit → 429 |

No separate geo-restriction page was found in the Search & Fetch guide. Localization is opt-in via `localization` (IP). Fetch 403 = security policy rejection for that URL (not a documented country blocklist).

---

### Python / OpenAI SDK compatibility

| Path | Support |
|---|---|
| **Standalone Search/Fetch** | **Raw HTTP JSON.** Official examples use `requests.post(...)`. There is **no** documented `openai` SDK method like `client.tools.search()`. Use `httpx`/`requests` (or `aiohttp`) against `/v1/tools/search` and `/v1/tools/fetch` with `Authorization: Bearer $DEEPSEEK_API_KEY`. |
| **Chat Completions** (`openai` SDK / `langchain_openai.ChatOpenAI`) | OpenAI-compatible; this repo already points at `https://api.deepseek.com`. Tools = **functions only** — wire Search/Fetch as app-executed function tools. |
| **Responses API** | OpenAI SDK `client.responses.create(...)` with `base_url="https://api.deepseek.com"`. Built-in `tools: [{"type": "web_search"}]` is **supported with `deepseek-v4-pro`**; **ignored with `deepseek-flash`**. Server runs search, injects results, continues. |
| **Anthropic-compatible Messages** | Base `https://api.deepseek.com/anthropic`. Harness provider uses versioned tool `web_search_20250305` on `/messages` (server-side search; costs a model turn). Claude Code Web Search is documented as natively supported and incurs extra model tokens for summarization. |

**Implication for this codebase:** Searching does not require a new provider SDK package; reuse `DEEPSEEK_API_KEY` and call REST directly. OpenAI SDK remains for LLM turns only unless adopting Responses `web_search`.

---

### Built-in `web_search` (tool-calling) — summary

From [Responses API guide](https://api-docs.deepseek.com/guides/responses_api) (as fetched 2026-10-17):

- `tools` includes `web_search` for **`deepseek-v4-pro`** only; **ignored** on `deepseek-flash`.
- Server executes search and continues the response.
- Streaming events: `response.web_search_call.in_progress` / `.searching` / `.completed` (**pro only**).
- Prior `web_search_call` items can be passed back in `input`; server restores search results into context.
- Other built-ins (`file_search`, `code_interpreter`, `computer_use`, `mcp`) are ignored.
- Custom tool: only `apply_patch` (Codex).

Older archive copies of the Responses guide also listed `web_search_2025_08_26` naming; the live page emphasizes `web_search` + Pro. Prefer the live guide when implementing.

For **application-controlled** retrieval (agents that need structured hits, ranking scores, Fetch-as-Markdown, retries, or Tavily-like plumbing), official docs point to the **standalone Search/Fetch REST APIs**, not Responses `web_search`.

---

### Comparison vs Tavily-style search APIs

Enough for an integration choice (facts only):

| Dimension | DeepSeek Search + Fetch | Tavily (this project’s current search health signal) |
|---|---|---|
| **Endpoints** | `POST /v1/tools/search`, `POST /v1/tools/fetch` on `api.deepseek.com` | `POST https://api.tavily.com/search` (+ Extract/Crawl/Map family) |
| **Auth** | Reuse `DEEPSEEK_API_KEY` | Separate `TAVILY_API_KEY` (already in health check / deploy / system_config) |
| **Result shape** | `snippet` + long `summary` + optional `content`; `rerank_score`, `authority`, `date`, favicon | `title`, `url`, `content`, relevancy `score`; optional LLM `answer`, images, `raw_content` |
| **Page fetch** | First-class Fetch → Markdown | Separate Extract / `include_raw_content` on search |
| **Query operators** | Rich: `site:`, `lang:`, `after:`/`before:`, phrases | Filters via params (`include_domains`, `time_range`, `topic`, `search_depth`, etc.) |
| **max results** | 1–50 (`count`) | Typically 0–20 (`max_results`) |
| **Pricing model** | Flat **$0.75 / ¥5 per 1k successful calls** each for Search and Fetch | Credit-based (basic ≈ 1 credit; advanced ≈ 2); plans from free 1k credits/mo; pay-as-you-go ~$0.008/credit → ~**$0.008+/search** at PAYG |
| **QPS** | Hard **5 QPS** per account per API | Plan/credit limited; not the same documented 5 QPS cap |
| **SDK** | Official samples = raw `requests`; no first-party Search SDK | Official Python/JS SDKs (`tavily`) |
| **LLM coupling** | Same vendor as this repo’s DeepSeek LLM route; optional Responses `web_search` on Pro | Independent vendor |
| **In this repo today** | LLM only via `DEEPSEEK_API_KEY` | Health: `search_api` checks `TAVILY_API_KEY`; message says trend_scout falls back to LLM-generated data if missing. No dedicated Tavily client module found under `backend/tools/` at research time |

**Integration-choice facts:**

- DeepSeek Search/Fetch can share the existing DeepSeek credential and avoid a second vendor key.
- Tavily already has a dedicated env/health path and a broader search-product surface (answer, images, crawl/map, Python SDK).
- DeepSeek unit price on paper is lower per successful call than Tavily PAYG basic search, but DeepSeek hard-caps at 5 QPS and bills Search and Fetch separately when both are used.
- DeepSeek returns model-oriented `summary` by default without needing a separate “advanced” depth flag; full page text is opt-in (`need_content`) or via Fetch.
- For agent loops that only need “model can browse,” Responses/`web_search` on Pro is another path; for explicit RAG/tool results matching Tavily’s role, standalone REST is the documented match.

---

### Files found (internal)

| File Path | Description |
|---|---|
| `backend/models/router.py` | DeepSeek via OpenAI SDK + `https://api.deepseek.com` + `DEEPSEEK_API_KEY` |
| `backend/api/routes/system.py` | `search_api` health = Tavily key presence (`_check_search`) |
| `backend/db/system_config.py` | Lists `DEEPSEEK_API_KEY`, `TAVILY_API_KEY` |
| `.env.example` | `DEEPSEEK_API_KEY=` |
| `scripts/deploy.sh` | Passes `TAVILY_API_KEY` into containers |
| `.trellis/spec/backend/logging-guidelines.md` | Documents `DEEPSEEK_API_KEY` as LLM credential |
| `CLAUDE.md` | Documents `search_api` as Tavily |

### Code patterns

- DeepSeek is treated as an **LLM provider** only today (`ChatOpenAI` + bearer key). No `/v1/tools/search` or `/v1/tools/fetch` client exists yet.
- Search availability is gated on **Tavily**, not DeepSeek:

```248:259:backend/api/routes/system.py
def _check_search() -> dict[str, Any]:
    """Check search API availability (Tavily)."""
    tavily = os.environ.get("TAVILY_API_KEY")
    configured = bool(tavily)
    return {
        "status": "ok" if configured else "warning",
        "configured": configured,
        "message": "搜索 API 已配置"
        if configured
        else "缺少 TAVILY_API_KEY（趋势发现将使用 LLM 生成数据）",
    }
```

### Related specs

- `.trellis/spec/backend/logging-guidelines.md` — env credential table includes `DEEPSEEK_API_KEY` (LLM); no Search/Fetch mention yet.
- No `.trellis/spec/` doc specifically covering web search providers as of this research date.

### External references

- [Search & Fetch guide (EN)](https://api-docs.deepseek.com/guides/search) — primary source for endpoints, schemas, billing, QPS
- [网页搜索与抓取 (ZH)](https://api-docs.deepseek.com/zh-cn/guides/search) — same content; ¥ pricing
- [Search API Reference](https://api-docs.deepseek.com/api/search) — OpenAPI-style request/response schema
- [Fetch API Reference](https://api-docs.deepseek.com/api/fetch)
- [Responses API](https://api-docs.deepseek.com/guides/responses_api) — built-in `web_search` (Pro)
- [Your First API Call](https://api-docs.deepseek.com/) — base URLs, OpenAI/Anthropic SDK setup, `DEEPSEEK_API_KEY`
- [Tool Calls guide](https://api-docs.deepseek.com/guides/tool_calls) — function tools on Chat Completions
- [Claude Code Web Search](https://api-docs.deepseek.com/zh-cn/quick_start/agent_integrations/claude_code) — native Web Search via DeepSeek
- [Pandaily coverage (2026-10-17)](https://pandaily.com/deepseek-api-search-fetch-endpoints-5-yuan-per-1000-requests-5-qps-agents-rag) — launch summary aligning with official ¥5 / 5 QPS figures
- [Tavily Search API](https://docs.tavily.com/documentation/api-reference/endpoint/search) / [Credits & Pricing](https://docs.tavily.com/documentation/api-credits) — comparison baseline

## Caveats / Not Found

- Official docs do **not** publish a numeric value for Fetch’s **per-domain** QPS (only that it exists and returns 429).
- No dedicated geo-block documentation found for Search/Fetch beyond `localization` IP and Fetch 403 security policy.
- No first-party Python package exclusively for Search/Fetch beyond raw HTTP examples.
- Live Responses guide text on `web_search` model support (`deepseek-v4-pro` vs flash) should be re-checked at implementation time; archived copies differed on naming (`web_search_2025_08_26`) and flash vs pro support.
- This repo’s trend_scout path is described as falling back when Tavily is missing; a concrete Tavily client module under `backend/tools/` was **not** found in this pass (health/config only). Confirm call sites before replacing the provider.
- EN `$0.75` and ZH `¥5` per 1k are both official; treat them as currency presentations of the same product rather than conflicting rates.
