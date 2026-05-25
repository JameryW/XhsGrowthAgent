# Error Handling Guide

本文档说明 XHS Growth Agent 的错误处理策略。

## 错误类型

### API 错误 (xhs_growth/api/errors.py)

| 错误类 | HTTP 状态码 | 说明 |
|--------|-------------|------|
| `ValidationError` | 400 | 参数验证失败 |
| `NotFoundError` | 404 | 资源不存在 |
| `WorkflowError` | 500 | 工作流执行错误 |
| `AuthenticationError` | 401 | 认证失败 |
| `RateLimitError` | 429 | 请求频率限制 |
| `InternalError` | 500 | 内部服务器错误 |

### XHS 平台错误 (xhs_growth/services/xhs_client.py)

| 错误类 | 说明 | 处理方式 |
|--------|------|----------|
| `XHSRateLimitError` | 小红书 API 限流 | 等待后重试 |
| `XHSAuthError` | Cookie 过期或无效 | 通知用户刷新 |
| `XHSPublishError` | 发布失败 | 检查内容合规性 |
| `XHSApiError` | 一般 API 错误 | 记录日志，降级处理 |

### LLM 错误

| 错误类型 | 说明 | 处理方式 |
|----------|------|----------|
| `TimeoutError` | LLM 响应超时 | 使用 fallback |
| `RateLimitError` | API 额度耗尽 | 切换备用模型 |
| `InvalidResponseError` | 返回无效 JSON | 使用算法降级 |

---

## 重试策略

### graph/error_handling.py 配置

```python
# 重试策略
MAX_RETRIES = 3              # 最大重试次数
RETRY_DELAY_BASE = 1.0       # 基础延迟（秒）
RETRY_DELAY_MULTIPLIER = 2   # 延迟倍数（指数退避）

# 示例重试序列
第1次失败 → 等待 1s → 重试
第2次失败 → 等待 2s → 重试
第3次失败 → 等待 4s → 重试
第4次失败 → 进入 ERROR 阶段
```

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

以下错误需要用户干预:

| 错误 | 用户操作 |
|------|----------|
| `XHSAuthError` | 重新获取 Cookie |
| `ContentRejected` | 修改内容后重新审核 |
| `PublishFailed` | 检查内容合规性，调整发布 |

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