# Error Handling Guide

本文档说明 XHS Growth Agent 的错误处理策略。

## 错误类型

### API 错误 (backend/api/errors.py)

| 错误类 | HTTP 状态码 | 说明 |
|--------|-------------|------|
| `ValidationError` | 400 | 参数验证失败 |
| `WorkflowNotFoundError` | 404 | 工作流线程不存在 |
| `ReviewNotPendingError` | 400 | 当前没有待处理的审核门 |
| `ChoiceNotPendingError` | 400 | 当前没有待处理的 choice 门 |
| `AuthenticationError` | 401 | 认证失败（基类） |
| `TokenMissingError` / `TokenInvalidError` / `LoginFailedError` | 401 | `AuthenticationError` 的三个子类 |
| `APIError` 家族 | 400/404/409/501 等 | 另有 Creator* 系列（笔记/模型/决策/记忆晋升/Action 等）；完整清单以 `backend/api/errors.py` 为准 |

### XHS 平台错误 (backend/services/xhs_client.py)

| 错误类 | 说明 | 处理方式 |
|--------|------|----------|
| `XHSRateLimitError` | 小红书 API 限流 | 等待后重试 |
| `XHSAuthError` | Cookie 过期或无效 | 通知用户刷新 |
| `XHSPublishError` | 发布失败 | 检查内容合规性 |
| `XHSApiError` | 一般 API 错误 | 记录日志，降级处理 |
| `XHSSignatureUnavailableError` | 签名路径不可用（`XHSApiError` 子类） | 不走逆向签名路径，如实报错 |

### LLM 错误恢复分派（`backend/models/recovery_policy.py`）

| 类别 | 典型触发 | 处理 |
|------|----------|------|
| `RETRY_SAME` | 429 / 5xx / 网络 | 原模型重试 |
| `DEGRADE_MODEL` | 400/404/409/422、schema、结构化解析失败 | 降级模型/结构化模式 |
| `ESCALATE_MODEL` | 同错误重复（stalled） | 升级档位（未配置模型矩阵时为 `RETRY_SAME`） |
| `STOP_AND_REPORT` | 401/403、内容策略拒绝、重试预算耗尽 | 停止并上报（拒绝优先，重试拒绝=绕过路径） |

底层传输重试在 `backend/models/retry.py`：默认最多 3 次、base delay 1.0s、上限 30s，
指数退避加抖动；可用 `XHS_LLM_MAX_RETRIES` / `XHS_LLM_RETRY_BASE_DELAY` /
`XHS_LLM_RETRY_MAX_DELAY` 覆盖。

---

## 重试策略

### 图节点重试（`backend/graph/error_handling.py`）

`RETRY_POLICIES` 是穷举注册表：每个节点都必须登记（`RetryPolicy(max_attempts=N)` 或显式
`None`），`get_retry_policy` 对未登记节点抛 `KeyError`；`tests/unit/graph/test_retry_registry.py`
钉住 `build_graph()` 的全部节点都在表里。`publisher` 显式为 `None`（外部副作用节点，禁止
generic auto-retry；发布重试只走 `/publish-retry` 的人工通道）。

### LLM 传输重试（`backend/models/retry.py`）

只对可重试错误（429 / 5xx / 网络）重试，默认 3 次、指数退避 + 抖动、上限 30 秒；认证与
参数错误直接传播。错误→动作的分派见上面 `recovery_policy` 表。

### 哪些操作会重试

| 操作 | 重试 | 说明 |
|------|------|------|
| LLM 调用 | 是 | Agent execute 内部处理 |
| XHS API | 是 | Rate limit 时指数退避 |
| Memory 操作 | 否 | 直接返回空结果 |
| Playwright 操作 | 是 | 页面加载失败重试 |

---

## 三层降级策略

Tools 使用三层降级确保永不失败:

```
┌─────────────────┐
│  LLM Enrichment │  ← 主要路径（智能分析）
└────────┬────────┘
         │ 失败
         ↓
┌─────────────────┐
│ Algorithmic     │  ← 算法降级（纯数据处理）
└────────┬────────┘
         │ 失败
         ↓
┌─────────────────┐
│ Default Fallback│  ← 保底返回（预定义默认值）
└─────────────────┘
```

### 示例

```python
async def hashtag_researcher(keyword: str) -> list[dict]:
    try:
        # Tier 1: LLM enrichment
        return await _enrich_with_llm(keyword)
    except Exception:
        # Tier 2: Algorithmic scoring
        trending = await _fetch_trending_tags(keyword)
        if trending:
            return _algorithmic_score(trending)
        # Tier 3: Default fallback
        return _get_defaults(keyword)
```

---

## Agent 错误处理

### Orchestrator 路由

```python
async def execute(state, store):
    error = state.get("error")
    retry_count = state.get("retry_count", 0)
    
    if error and retry_count >= 3:
        return {"phase": WorkflowPhase.ERROR}  # 进入错误状态
    
    if error:
        # 清除错误，重新开始
        return {"phase": WorkflowPhase.SCOUTING, "error": None}
```

### BaseAgent 错误捕获

```python
async def __call__(state, *, store):
    try:
        result = await self.execute(state, store)
        return result
    except Exception as e:
        return {
            "error": f"{self.agent_name}: {type(e).__name__}: {e}",
            "retry_count": state.get("retry_count", 0) + 1,
        }
```

---

## 用户可恢复错误

下表按 `PublishErrorType`（`backend/api/errors.py`）列出发布相关的可恢复错误：

| 错误类型 | 用户操作 |
|------|----------|
| `auth_expired` / `account_unverified` | 重新扫码登录 / 完成账号验证 |
| `content_violation` | 修改内容后重新审核 |
| `image_missing` | 补充图片后重试 |
| `rate_limited` / `network_error` | 稍后重试（属于可自动重试类） |
| `unknown` | 人工排查；结果不明时先对账再决定是否重试 |

---

## 日志记录

### 错误日志格式

```python
logger.error(f"{agent_name} failed: {type(e).__name__}: {e}", exc_info=True)
```

### 日志级别使用

| 级别 | 场景 |
|------|------|
| `ERROR` | 操作失败，影响流程 |
| `WARNING` | 降级处理，流程继续 |
| `INFO` | 正常操作完成 |
| `DEBUG` | 详细调试信息 |

**注意**: 不在日志中记录敏感信息（Cookie、API key）。

---

## 错误恢复流程

```
┌──────────────┐
│ Agent 失败   │
└──────┬───────┘
       │
       ↓
┌──────────────┐
│ retry_count++│
└──────┬───────┘
       │
       ↓
┌──────────────────┐
│ retry_count >= 3?│
└──────┬───────────┘
       │
   Yes │ No
       ↓
┌──────────────┐    ┌──────────────┐
│ ERROR 阶段   │    │ 清除错误重试 │
└──────────────┘    └──────────────┘
```

---

## 前端错误处理

### API 错误拦截

```typescript
// frontend/src/api/client.ts
apiClient.interceptors.response.use(
  response => response,
  error => {
    if (error.response?.status === 429) {
      // Rate limit - 显示等待提示
      return Promise.reject(new RateLimitError())
    }
    return Promise.reject(error)
  }
)
```

### 用户显示

| 错误 | UI 提示 |
|------|---------|
| 网络错误 | "网络连接失败，请检查网络" |
| Rate limit | "请求过快，请稍后再试" |
| Auth 错误 | "登录已过期，请重新登录" |
| 内部错误 | "服务暂时不可用" |