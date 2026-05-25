# API Reference

本文档详细说明 XHS Growth Agent 的所有 API 端点。

## Base URL

```
http://localhost:8000/api
```

## 认证

当前版本无认证机制（内部工具）。生产部署建议添加 JWT 认证。

---

## Workflow Endpoints

### POST /workflow/start

启动新的工作流实例。

**Request:**
```json
{
  "account_id": "string",
  "phase": "scouting | planning | creating | reviewing | publishing | analyzing",
  "dry_run": false
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "thread_id": "string",
    "status": "running",
    "phase": "string"
  },
  "error": null,
  "meta": {
    "timestamp": "ISO8601"
  }
}
```

**Status Codes:**
- `200` - 工作流启动成功
- `400` - 参数验证失败
- `500` - 内部错误

---

### GET /workflow/{thread_id}/status

获取工作流状态。

**Parameters:**
- `thread_id` (path) - 工作流实例 ID

**Response:**
```json
{
  "success": true,
  "data": {
    "thread_id": "string",
    "phase": "string",
    "current_agent": "string",
    "next_nodes": ["string"],
    "error": "string | null",
    "retry_count": 0
  }
}
```

**Status Codes:**
- `200` - 状态查询成功
- `404` - thread_id 不存在

---

### POST /workflow/{thread_id}/resume

恢复中断的工作流（审核后继续）。

**Parameters:**
- `thread_id` (path) - 工作流实例 ID

**Request:**
```json
{
  "decision": "approved | needs_revision | rejected",
  "comments": "string",
  "revisions": ["string"]
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "phase": "string",
    "status": "running"
  }
}
```

---

## Review Endpoints

### GET /review/{thread_id}

获取待审核内容。

**Parameters:**
- `thread_id` (path) - 工作流实例 ID

**Response:**
```json
{
  "success": true,
  "data": {
    "topic": "string",
    "titles": ["string"],
    "body_preview": "string",
    "cover_prompt": "string",
    "hashtags": ["string"]
  }
}
```

---

### POST /review/{thread_id}/submit

提交审核决策。

**Request:**
```json
{
  "decision": "approved | needs_revision | rejected",
  "comments": "string",
  "revisions": [
    {
      "field": "title | body | hashtags | cover",
      "suggestion": "string"
    }
  ]
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "status": "accepted",
    "next_phase": "publishing"
  }
}
```

---

## Analytics Endpoints

### GET /analytics/{thread_id}

获取工作流分析数据。

**Parameters:**
- `thread_id` (path) - 工作流实例 ID

**Response:**
```json
{
  "success": true,
  "data": {
    "views": 0,
    "likes": 0,
    "comments": 0,
    "shares": 0,
    "engagement_rate": 0.0,
    "insights": ["string"]
  }
}
```

---

### GET /analytics/dashboard

获取整体分析仪表盘数据。

**Query Parameters:**
- `account_id` (optional) - 账号 ID 过滤
- `period` (optional) - 时间范围 (day | week | month)

**Response:**
```json
{
  "success": true,
  "data": {
    "total_posts": 0,
    "total_engagement": 0,
    "top_topics": ["string"],
    "performance_trend": [
      {"date": "ISO8601", "engagement": 0}
    ]
  }
}
```

---

## Health Check

### GET /health

服务健康检查。

**Response:**
```json
{
  "status": "healthy",
  "version": "string",
  "uptime": 0
}
```

---

## Error Response Format

所有错误响应遵循统一格式:

```json
{
  "success": false,
  "data": null,
  "error": {
    "code": "ERROR_CODE",
    "message": "Human readable message",
    "details": {}
  },
  "meta": {
    "timestamp": "ISO8601"
  }
}
```

**Error Codes:**

| Code | Description |
|------|-------------|
| `VALIDATION_ERROR` | 参数验证失败 |
| `NOT_FOUND` | 资源不存在 |
| `WORKFLOW_ERROR` | 工作流执行错误 |
| `AUTH_ERROR` | 认证失败 |
| `RATE_LIMIT` | 请求频率限制 |
| `INTERNAL_ERROR` | 内部服务器错误 |

---

## Rate Limits

当前无限制。生产部署建议:
- `/workflow/*`: 60 requests/minute
- `/analytics/*`: 120 requests/minute