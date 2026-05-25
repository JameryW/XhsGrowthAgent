---
name: backend-optimization
description: OpenAPI 契约优先的后端架构重构设计，解决前后端类型不一致、Agent/服务初始化、状态管理和 API 错误处理问题
---

# XHS Growth Agent 后端架构优化设计

## 概述

本设计采用 **OpenAPI 契约优先** 方法重构后端架构，解决以下核心问题：

1. **类型不匹配**：前端 TypeScript 与后端 Python 类型不一致，需要手动转换
2. **Agent/服务初始化**：单例模式不便于测试和扩展
3. **State Schema 复杂**：TypedDict 有太多可选字段，难以管理
4. **API 响应不规范**：缺少统一的错误处理和响应格式

**Why:** 近期修复（ContentStatus enum/string 不匹配）表明架构需要系统化改进，避免持续的手动同步问题。

**How to apply:** 按实施步骤逐步重构，先定义 OpenAPI 规范，再生成前后端类型，最后改造现有代码。

---

## 一、整体架构

```
xhs_growth/
├── api/
│   ├── spec/
│   │   └── openapi.yaml        # OpenAPI 3.1 规范（核心）
│   ├── generated/
│   │   ├── models.py           # 自动生成的 Pydantic 模型
│   │   └── routes.py           # 自动生成的路由骨架
│   ├── responses.py            # 统一响应封装
│   ├── errors.py               # 统一异常处理
│   ├── middleware.py           # 异常处理中间件
│   └── routes/
│   │   ├── workflow.py         # 路由实现
│   │   ├── review.py
│   │   ├── analytics.py
│   └── app.py                  # FastAPI 应用入口
│
├── state/
│   ├── schema.py               # 简化的内部状态 TypedDict
│   ├── substates.py            # 子状态模块化定义
│   ├── reducers.py             # 状态 reducers
│   └── enums.py                # 枚举定义（与 OpenAPI 同步）
│
├── agents/
│   ├── factory.py              # Agent 工厂 + 依赖注入
│   ├── base.py                 # Agent 基类
│   ├── orchestrator.py
│   ├── trend_scout.py
│   ├── content_strategist.py
│   ├── copywriter.py
│   ├── visual_designer.py
│   ├── publisher.py
│   ├── analyst.py
│   ├── engagement.py
│   └── __init__.py             # 自动注册所有 Agent
│
├── services/
│   ├── container.py            # 服务容器 (DI)
│   ├── xhs_api.py
│   ├── xhs_client.py
│   ├── xhs_publisher.py
│   ├── xhs_engagement.py
│   └── xhs_signature.py
│
├── core/
│   ├── di.py                   # 依赖注入框架
│   ├── config.py               # 配置管理
│   └── constants.py            # 常量定义
│
├── graph/
│   ├── builder.py              # StateGraph 构建
│   ├── nodes.py                # Agent 节点包装
│   ├── routers.py              # 条件路由
│   └── error_handling.py       # 错误处理策略
│
├── tools/                      # Agent 工具（保持现有结构）
│   ├── analysis/
│   ├── content/
│   ├── ripple/
│   ├── scheduling/
│   ├── xhs/
│   └── registry.py
│
├── models/
│   ├── router.py               # LLM 模型路由
│   ├── cost_tracker.py
│   └── visual_types.py         # 视觉分析类型
│
├── memory/
│   ├── store.py                # 长期记忆管理
│   └── manager.py
│
├── cli/                        # CLI 入口
│   └── main.py
│
├── config/
│   ├── prompts/                # Agent 提示词 YAML
│   ├── models.py               # TaskType 枚举
│   └── settings.py             # 应用配置
│
└── __init__.py

frontend/
├── src/
│   ├── api/
│   │   ├── generated/
│   │   │   ├── index.ts        # 导出入口
│   │   │   ├── models.ts       # 类型定义（自动生成）
│   │   │   ├── services.ts     # API 服务（自动生成）
│   │   │   └── request.ts      # 请求配置
│   │   ├── client.ts           # 自定义封装
│   │   └── index.ts
│   ├── types/
│   │   ├── state.ts            # 镜像后端 State（手动维护）
│   │   └── index.ts
│   ├── stores/
│   │   ├── workflow.ts         # 使用生成的 API 客户端
│   │   ├── review.ts
│   │   ├── analytics.ts
│   │   └── index.ts
│   ├── views/
│   ├── components/
│   └── App.vue

scripts/
├── generate_types.sh           # 类型生成脚本

tests/
├── conftest.py
├── unit/
│   ├── agents/
│   ├── state/
│   ├── api/
│   ├── core/
│   ├── models/
│   └── services/
│
├── integration/
│   ├── test_workflow_flow.py
│   ├── test_review_gate.py
│   ├── test_api_routes.py
│   └── test_frontend_contract.py
│
├── contract/
│   ├── test_openapi_spec.py
│   └── test_type_sync.py
```

---

## 二、OpenAPI 规范设计

### 2.1 核心结构

规范文件：`api/spec/openapi.yaml`

```yaml
openapi: 3.1.0
info:
  title: XHS Growth Engine API
  version: 1.0.0
  description: 小红书增长引擎 Agent API

servers:
  - url: /api
    description: Production server

tags:
  - name: workflow
    description: Workflow lifecycle management
  - name: review
    description: Human-in-the-loop content review
  - name: analytics
    description: Growth analytics and reporting

paths:
  # Workflow endpoints
  /workflow/start:
    post:
      tags: [workflow]
      operationId: startWorkflow
      summary: Start a new workflow
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/WorkflowStartRequest'
      responses:
        '200':
          description: Workflow started successfully
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ApiResponse_WorkflowResponse'
        '400':
          $ref: '#/components/responses/BadRequest'
        '500':
          $ref: '#/components/responses/InternalError'

  /workflow/status/{thread_id}:
    get:
      tags: [workflow]
      operationId: getWorkflowStatus
      summary: Get workflow status
      parameters:
        - name: thread_id
          in: path
          required: true
          schema:
            type: string
            description: Workflow thread ID
      responses:
        '200':
          description: Workflow state
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ApiResponse_WorkflowState'
        '404':
          $ref: '#/components/responses/NotFound'

  /workflow/pause/{thread_id}:
    post:
      tags: [workflow]
      operationId: pauseWorkflow
      parameters:
        - name: thread_id
          in: path
          required: true
          schema:
            type: string
      responses:
        '200':
          description: Workflow paused
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ApiResponse_WorkflowPauseResult'

  /workflow/resume/{thread_id}:
    post:
      tags: [workflow]
      operationId: resumeWorkflow
      parameters:
        - name: thread_id
          in: path
          required: true
          schema:
            type: string
      responses:
        '200':
          description: Workflow resumed
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ApiResponse_WorkflowResponse'

  # Review endpoints
  /review/pending/{thread_id}:
    get:
      tags: [review]
      operationId: getPendingReview
      summary: Get pending content for review
      parameters:
        - name: thread_id
          in: path
          required: true
          schema:
            type: string
      responses:
        '200':
          description: Pending review content
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ApiResponse_PendingReview'
        '400':
          $ref: '#/components/responses/BadRequest'

  /review/submit/{thread_id}:
    post:
      tags: [review]
      operationId: submitReview
      summary: Submit review decision
      parameters:
        - name: thread_id
          in: path
          required: true
          schema:
            type: string
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/ReviewDecisionRequest'
      responses:
        '200':
          description: Review submitted
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ApiResponse_ReviewSubmitResponse'
        '400':
          $ref: '#/components/responses/BadRequest'

  # Analytics endpoints
  /analytics/report/{account_id}:
    get:
      tags: [analytics]
      operationId: getGrowthReport
      parameters:
        - name: account_id
          in: path
          required: true
          schema:
            type: string
        - name: period
          in: query
          schema:
            type: string
            enum: [daily, weekly, monthly]
            default: weekly
      responses:
        '200':
          description: Growth report
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ApiResponse_GrowthReport'

  /analytics/performance/{account_id}:
    get:
      tags: [analytics]
      operationId: getPerformance
      parameters:
        - name: account_id
          in: path
          required: true
          schema:
            type: string
        - name: limit
          in: query
          schema:
            type: integer
            default: 20
            minimum: 1
            maximum: 100
      responses:
        '200':
          description: Performance data
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ApiResponse_PerformanceList'

  /analytics/costs:
    get:
      tags: [analytics]
      operationId: getCosts
      summary: Get LLM call costs
      responses:
        '200':
          description: Cost tracking data
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ApiResponse_CostReport'

components:
  schemas:
    # === 统一响应封装 ===
    ApiResponse:
      type: object
      required: [success, timestamp]
      properties:
        success:
          type: boolean
          description: Request success status
        data:
          type: object
          description: Response data (null on error)
        error:
          $ref: '#/components/schemas/ErrorDetail'
        timestamp:
          type: string
          format: date-time
          description: Response timestamp
        request_id:
          type: string
          description: Request tracking ID

    ErrorDetail:
      type: object
      required: [code, message]
      properties:
        code:
          type: string
          description: Error code (e.g., ERROR_WORKFLOW_NOT_FOUND)
        message:
          type: string
          description: Human-readable error message
        details:
          type: object
          additionalProperties: true
          description: Additional error context

    # === 泛型响应别名 ===
    ApiResponse_WorkflowResponse:
      allOf:
        - $ref: '#/components/schemas/ApiResponse'
        - type: object
          properties:
            data:
              $ref: '#/components/schemas/WorkflowResponse'

    ApiResponse_WorkflowState:
      allOf:
        - $ref: '#/components/schemas/ApiResponse'
        - type: object
          properties:
            data:
              $ref: '#/components/schemas/WorkflowState'

    ApiResponse_PendingReview:
      allOf:
        - $ref: '#/components/schemas/ApiResponse'
        - type: object
          properties:
            data:
              $ref: '#/components/schemas/PendingReview'

    ApiResponse_ReviewSubmitResponse:
      allOf:
        - $ref: '#/components/schemas/ApiResponse'
        - type: object
          properties:
            data:
              $ref: '#/components/schemas/ReviewSubmitResponse'

    ApiResponse_GrowthReport:
      allOf:
        - $ref: '#/components/schemas/ApiResponse'
        - type: object
          properties:
            data:
              $ref: '#/components/schemas/GrowthReport'

    ApiResponse_PerformanceList:
      allOf:
        - $ref: '#/components/schemas/ApiResponse'
        - type: object
          properties:
            data:
              type: array
              items:
                $ref: '#/components/schemas/PerformanceRecord'

    ApiResponse_CostReport:
      allOf:
        - $ref: '#/components/schemas/ApiResponse'
        - type: object
          properties:
            data:
              $ref: '#/components/schemas/CostReport'

    ApiResponse_WorkflowPauseResult:
      allOf:
        - $ref: '#/components/schemas/ApiResponse'
        - type: object
          properties:
            data:
              $ref: '#/components/schemas/WorkflowPauseResult'

    # === Enums ===
    WorkflowPhase:
      type: string
      enum:
        - idle
        - scouting
        - planning
        - creating
        - reviewing
        - publishing
        - analyzing
        - engaging
        - completed
        - error
      description: Workflow execution phase

    ContentStatus:
      type: string
      enum:
        - approved
        - needs_revision
        - rejected
        - draft
        - pending_review
        - published
        - failed
      description: Content review status

    ContentType:
      type: string
      enum:
        - note
        - video
        - carousel
      description: Content type

    Urgency:
      type: string
      enum:
        - low
        - medium
        - high
        - trending
      description: Content urgency level

    WorkflowStatus:
      type: string
      enum:
        - running
        - paused
        - completed
        - error
      description: Workflow overall status

    # === Workflow Types ===
    WorkflowStartRequest:
      type: object
      required: [account_id]
      properties:
        account_id:
          type: string
          minLength: 1
          description: Account identifier
        phase:
          $ref: '#/components/schemas/WorkflowPhase'
          default: scouting

    WorkflowResponse:
      type: object
      required: [thread_id, status, phase]
      properties:
        thread_id:
          type: string
          description: Workflow thread ID
        status:
          $ref: '#/components/schemas/WorkflowStatus'
        phase:
          $ref: '#/components/schemas/WorkflowPhase'

    WorkflowState:
      type: object
      required: [thread_id, phase]
      properties:
        thread_id:
          type: string
        phase:
          $ref: '#/components/schemas/WorkflowPhase'
        current_agent:
          type: string
        trend_data:
          $ref: '#/components/schemas/TrendData'
        content_plan:
          $ref: '#/components/schemas/ContentPlan'
        copy_content:
          $ref: '#/components/schemas/CopyContent'
        visual_plan:
          $ref: '#/components/schemas/VisualPlan'
        error:
          type: string
          nullable: true
        created_at:
          type: string
          format: date-time
        updated_at:
          type: string
          format: date-time

    WorkflowPauseResult:
      type: object
      required: [thread_id, status]
      properties:
        thread_id:
          type: string
        status:
          type: string
          enum: [paused]

    # === Review Types ===
    PendingReview:
      type: object
      required: [status]
      properties:
        status:
          type: string
          enum:
            - awaiting_review
            - no_pending_review
        content_plan:
          $ref: '#/components/schemas/ContentPlan'
        copy_content:
          $ref: '#/components/schemas/CopyContent'
        visual_plan:
          $ref: '#/components/schemas/VisualPlan'

    ReviewDecisionRequest:
      type: object
      required: [decision]
      properties:
        decision:
          $ref: '#/components/schemas/ContentStatus'
        comments:
          type: string
          default: ""
        revisions:
          type: array
          items:
            type: string
          default: []

    ReviewSubmitResponse:
      type: object
      required: [thread_id, status, decision, next_phase]
      properties:
        thread_id:
          type: string
        status:
          type: string
          enum: [resumed]
        decision:
          $ref: '#/components/schemas/ContentStatus'
        next_phase:
          type: string

    # === Analytics Types ===
    GrowthReport:
      type: object
      properties:
        account_id:
          type: string
        period:
          type: string
        metrics:
          $ref: '#/components/schemas/GrowthMetrics'
        insights:
          type: array
          items:
            type: string

    GrowthMetrics:
      type: object
      properties:
        total_views:
          type: integer
        total_likes:
          type: integer
        total_comments:
          type: integer
        engagement_rate:
          type: number
        growth_rate:
          type: number

    PerformanceRecord:
      type: object
      properties:
        post_id:
          type: string
        title:
          type: string
        views:
          type: integer
        likes:
          type: integer
        comments:
          type: integer
        published_at:
          type: string
          format: date-time

    CostReport:
      type: object
      properties:
        total_cost_usd:
          type: number
        today_cost_usd:
          type: number
        by_model:
          type: object
          additionalProperties:
            type: number
        circuit_open:
          type: boolean

    # === Sub-state Types ===
    NicheOpportunity:
      type: object
      properties:
        topic:
          type: string
          description: Niche topic identifier
        potential_score:
          type: number
          minimum: 0
          maximum: 100
          description: Opportunity potential score
        audience_match:
          type: string
          description: Target audience match level
        entry_barrier:
          type: string
          enum: [low, medium, high]
          description: Competition entry barrier

    TrendData:
      type: object
      properties:
        hot_topics:
          type: array
          items:
            $ref: '#/components/schemas/HotTopicItem'
        trending_keywords:
          type: array
          items:
            type: string
        competitor_posts:
          type: array
          items:
            $ref: '#/components/schemas/CompetitorPost'
        niche_opportunities:
          type: array
          items:
            $ref: '#/components/schemas/NicheOpportunity'
        timestamp:
          type: string
          format: date-time

    HotTopicItem:
      type: object
      required: [topic]
      properties:
        topic:
          type: string
        heat_score:
          type: number
          minimum: 0
          maximum: 100
        growth_rate:
          type: number
        related_keywords:
          type: array
          items:
            type: string

    CompetitorPost:
      type: object
      properties:
        title:
          type: string
        likes:
          type: integer
        comments:
          type: integer
        author:
          type: string

    ContentPlan:
      type: object
      properties:
        selected_topic:
          type: string
        content_angle:
          type: string
        content_type:
          $ref: '#/components/schemas/ContentType'
        target_audience:
          type: string
        key_points:
          type: array
          items:
            type: string
        suggested_timing:
          type: string
        hashtags:
          type: array
          items:
            type: string
        urgency:
          $ref: '#/components/schemas/Urgency'

    CopyContent:
      type: object
      properties:
        title_candidates:
          type: array
          items:
            type: string
          minItems: 3
          maxItems: 5
        selected_title:
          type: string
        body_text:
          type: string
        hashtags:
          type: array
          items:
            type: string
        cta:
          type: string
          description: Call-to-action text
        emoji_usage:
          type: array
          items:
            type: string
        tone:
          type: string
          description: Tone style (e.g., casual, professional)

    VisualPlan:
      type: object
      properties:
        cover_prompt:
          type: string
          description: Cover image generation prompt
        image_count:
          type: integer
          minimum: 1
          maximum: 9
        image_prompts:
          type: array
          items:
            type: string
        layout_style:
          type: string
        color_palette:
          type: array
          items:
            type: string
            pattern: '^#[A-Fa-f0-9]{6}$'
          description: Hex color codes
        font_suggestion:
          type: string
        brand_elements:
          type: array
          items:
            type: string

  responses:
    BadRequest:
      description: Bad request - validation error
      content:
        application/json:
          schema:
            $ref: '#/components/schemas/ApiResponse'
          example:
            success: false
            error:
              code: ERROR_VALIDATION
              message: Invalid request parameters
              details:
                field: account_id
                reason: Required field missing
            timestamp: "2026-05-25T10:00:00Z"

    NotFound:
      description: Resource not found
      content:
        application/json:
          schema:
            $ref: '#/components/schemas/ApiResponse'
          example:
            success: false
            error:
              code: ERROR_WORKFLOW_NOT_FOUND
              message: Workflow not found
              details:
                thread_id: "xhs_test_123"
            timestamp: "2026-05-25T10:00:00Z"

    InternalError:
      description: Internal server error
      content:
        application/json:
          schema:
            $ref: '#/components/schemas/ApiResponse'
          example:
            success: false
            error:
              code: ERROR_INTERNAL
              message: Internal server error
            timestamp: "2026-05-25T10:00:00Z"
```

### 2.2 规范维护原则

1. **单一类型源**：`openapi.yaml` 是所有 API 类型定义的唯一来源
2. **版本控制**：修改规范时创建新版本，保留兼容性
3. **自动生成**：使用工具自动生成前后端类型，避免手动同步
4. **契约测试**：CI 验证规范与生成的类型一致

---

## 三、内部状态 Schema 简化

### 3.1 状态设计原则

- **必需 vs 可选分离**：使用 `NotRequired` 明确标记可选字段
- **子状态模块化**：每个 TypedDict 定义在独立模块，职责清晰
- **枚举统一**：与 OpenAPI 定义完全一致
- **Reducer 集中**：所有 reducer 函数在 `reducers.py` 中定义

### 3.2 Schema 实现

```python
# state/enums.py - 枚举定义（与 OpenAPI 同步）

from enum import Enum

class WorkflowPhase(str, Enum):
    IDLE = "idle"
    SCOUTING = "scouting"
    PLANNING = "planning"
    CREATING = "creating"
    REVIEWING = "reviewing"
    PUBLISHING = "publishing"
    ANALYZING = "analyzing"
    ENGAGING = "engaging"
    COMPLETED = "completed"
    ERROR = "error"

class ContentStatus(str, Enum):
    APPROVED = "approved"
    NEEDS_REVISION = "needs_revision"
    REJECTED = "rejected"
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    PUBLISHED = "published"
    FAILED = "failed"

class ContentType(str, Enum):
    NOTE = "note"
    VIDEO = "video"
    CAROUSEL = "carousel"

class Urgency(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    TRENDING = "trending"

# state/substates.py - 子状态定义

from typing import TypedDict, NotRequired, Any
from xhs_growth.state.enums import ContentType, Urgency, ContentStatus

class HotTopicItem(TypedDict, total=False):
    topic: str
    heat_score: float
    growth_rate: float
    related_keywords: list[str]

class NicheOpportunity(TypedDict, total=False):
    topic: str
    potential_score: float
    audience_match: str
    entry_barrier: str  # low, medium, high

class TrendData(TypedDict, total=False):
    hot_topics: list[HotTopicItem]
    trending_keywords: list[str]
    competitor_posts: list[dict[str, Any]]
    niche_opportunities: list[NicheOpportunity]
    timestamp: str

class ContentPlan(TypedDict, total=False):
    selected_topic: str
    content_angle: str
    content_type: ContentType
    target_audience: str
    key_points: list[str]
    suggested_timing: str
    hashtags: list[str]
    urgency: Urgency

class CopyContent(TypedDict, total=False):
    title_candidates: list[str]
    selected_title: str
    body_text: str
    hashtags: list[str]
    cta: str
    emoji_usage: list[str]
    tone: str

class VisualPlan(TypedDict, total=False):
    cover_prompt: str
    image_count: int
    image_prompts: list[str]
    layout_style: str
    color_palette: list[str]
    font_suggestion: str
    brand_elements: list[str]

class PublishResult(TypedDict, total=False):
    post_id: str
    post_url: str
    published_at: str
    ab_variant: str | None
    status: ContentStatus

class AnalyticsSnapshot(TypedDict, total=False):
    post_id: str
    views: int
    likes: int
    collects: int
    comments: int
    shares: int
    engagement_rate: float
    reach_rate: float
    timestamp: str
    insights: list[str]
    recommendations: list[str]

class HumanFeedback(TypedDict, total=False):
    decision: ContentStatus
    comments: str
    revisions: list[str]
    reviewer: str

class EngagementAction(TypedDict, total=False):
    action_type: str
    target_id: str
    content: str
    timestamp: str

class RipplePrediction(TypedDict, total=False):
    job_id: str
    estimated_reach: int
    estimated_engagement: int
    viral_probability: float
    phase: str
    confidence: float
    key_influencers: list[dict[str, Any]]
    spread_path: list[dict[str, Any]]

class RipplePMFResult(TypedDict, total=False):
    job_id: str
    pmf_score: float
    risk_factors: list[str]
    improvement_strategies: list[str]
    market_segment: dict[str, Any]
    confidence: float

# state/schema.py - 主状态定义

from typing import Annotated, NotRequired
from langgraph.graph.message import add_messages
from xhs_growth.state.enums import WorkflowPhase, ContentStatus
from xhs_growth.state.substates import (
    TrendData, ContentPlan, CopyContent, VisualPlan,
    PublishResult, AnalyticsSnapshot, HumanFeedback,
    EngagementAction, RipplePrediction, RipplePMFResult
)
from xhs_growth.state.reducers import merge_dict, append_list

class XHSGrowthState(TypedDict):
    """小红书增长引擎全局状态"""

    # === 必需字段 ===
    phase: WorkflowPhase
    current_agent: str
    account_id: str
    session_id: str
    error: str | None
    retry_count: int
    created_at: str
    updated_at: str

    # === 消息历史（LangGraph reducer）===
    messages: Annotated[list, add_messages]

    # === 各阶段数据（可选）===
    trend_data: NotRequired[TrendData]
    content_plan: NotRequired[ContentPlan]
    copy_content: NotRequired[CopyContent]
    visual_plan: NotRequired[VisualPlan]
    publish_result: NotRequired[PublishResult]
    analytics: NotRequired[AnalyticsSnapshot]

    # === 人工审核 ===
    human_feedback: NotRequired[HumanFeedback]

    # === Ripple CAS（可选外部服务）===
    ripple_prediction: NotRequired[RipplePrediction]
    ripple_pmf: NotRequired[RipplePMFResult]
    ripple_job_ids: Annotated[list[str], append_list]

    # === 历史记录（带 reducer）===
    engagement_actions: Annotated[list[EngagementAction], append_list]
    content_history: Annotated[list[dict], append_list]
    performance_log: Annotated[list[dict], append_list]

# state/reducers.py - Reducer 函数

from typing import Any

def merge_dict(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    """Shallow merge dicts (right overrides left)"""
    return {**left, **right}

def append_list(left: list[Any], right: list[Any]) -> list[Any]:
    """Append right to left"""
    return left + right

def replace(_: Any, right: Any) -> Any:
    """Simple replacement"""
    return right

def max_value(left: int | float, right: int | float) -> int | float:
    """Keep larger value"""
    return max(left, right)
```

---

## 四、Agent/服务依赖注入

### 4.1 DI 容器设计

```python
# core/di.py - 依赖注入框架

from typing import TypeVar, Callable, Any, Protocol
import logging

T = TypeVar("T")
logger = logging.getLogger("xhs_growth.di")

class ServiceContainer:
    """轻量级依赖注入容器"""

    def __init__(self):
        self._services: dict[str, Any] = {}
        self._factories: dict[str, Callable[[], Any]] = {}

    def register_instance(self, name: str, instance: Any) -> None:
        """注册单例实例"""
        self._services[name] = instance
        logger.debug(f"Registered instance: {name}")

    def register_factory(self, name: str, factory: Callable[[], Any]) -> None:
        """注册工厂函数（延迟创建）"""
        self._factories[name] = factory
        logger.debug(f"Registered factory: {name}")

    def get(self, name: str) -> Any:
        """获取服务（工厂会缓存为单例）"""
        if name in self._services:
            return self._services[name]
        if name in self._factories:
            instance = self._factories[name]()
            self._services[name] = instance
            return instance
        raise KeyError(f"Service '{name}' not registered")

    def has(self, name: str) -> bool:
        """检查服务是否注册"""
        return name in self._services or name in self._factories

    def clear(self) -> None:
        """清空容器（测试用）"""
        self._services.clear()
        self._factories.clear()

# 全局容器
_container = ServiceContainer()

def get_container() -> ServiceContainer:
    return _container

def reset_container() -> None:
    """重置容器（测试用）"""
    global _container
    _container = ServiceContainer()
```

### 4.2 Agent 工厂设计

```python
# agents/factory.py - Agent 工厂

from typing import Type, Any, Protocol, runtime_checkable
from xhs_growth.core.di import get_container
from xhs_growth.state.schema import XHSGrowthState
from langgraph.store.base import BaseStore

@runtime_checkable
class AgentProtocol(Protocol):
    """Agent 协议"""
    agent_name: str
    task_type: Any  # TaskType

    async def execute(
        self,
        state: XHSGrowthState,
        store: BaseStore
    ) -> dict[str, Any]: ...

class AgentFactory:
    """Agent 工厂 - 创建和管理 Agent 实例"""

    _registry: dict[str, Type[AgentProtocol]] = {}

    @classmethod
    def register(cls, agent_class: Type[AgentProtocol]) -> None:
        """注册 Agent 类型"""
        cls._registry[agent_class.agent_name] = agent_class

    @classmethod
    def create(cls, agent_name: str, **kwargs: Any) -> AgentProtocol:
        """创建 Agent 实例（自动注入依赖）"""
        if agent_name not in cls._registry:
            raise ValueError(f"Agent '{agent_name}' not registered")

        agent_class = cls._registry[agent_name]
        container = get_container()

        # 自动注入已注册的依赖
        injected = {}
        inject_map = {
            'memory_manager': 'memory_manager',
            'model_router': 'model_router',
            'xhs_client': 'xhs_client',
        }

        for attr, service_name in inject_map.items():
            if container.has(service_name):
                injected[attr] = container.get(service_name)

        return agent_class(**{**injected, **kwargs})

    @classmethod
    def get_registered(cls) -> list[str]:
        """获取所有已注册 Agent 名称"""
        return list(cls._registry.keys())

    @classmethod
    def clear(cls) -> None:
        """清空注册（测试用）"""
        cls._registry.clear()
```

### 4.3 Base Agent 改进

```python
# agents/base.py - Agent 基类

from __future__ import annotations
import json
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import yaml
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.store.base import BaseStore

from xhs_growth.config.models import TaskType
from xhs_growth.models.router import ModelRouter
from xhs_growth.memory.manager import MemoryManager
from xhs_growth.state.schema import XHSGrowthState

logger = logging.getLogger("xhs_growth.agents")

class BaseAgent(ABC):
    """改进后的 Agent 基类 - 支持依赖注入"""

    task_type: TaskType
    agent_name: str
    prompt_file: str = ""

    # 注入标记
    _inject_memory: bool = True
    _inject_model: bool = True

    def __init__(
        self,
        memory_manager: MemoryManager | None = None,
        model_router: ModelRouter | None = None,
    ):
        self.memory_manager = memory_manager
        self._model_router = model_router
        self._prompt_cache: dict[str, str] | None = None

    @property
    def model(self) -> BaseChatModel:
        """获取 LLM 模型"""
        if self._model_router is None:
            from xhs_growth.models.router import ModelRouter
            self._model_router = ModelRouter()
        return self._model_router.get_model(self.task_type.value)

    @property
    def prompt_template(self) -> dict[str, str]:
        """加载提示词模板"""
        if self._prompt_cache is None:
            self._prompt_cache = self._load_prompt()
        return self._prompt_cache

    def _load_prompt(self) -> dict[str, str]:
        if not self.prompt_file:
            return {"system": "", "user_template": ""}
        path = Path(__file__).parent.parent / "config" / "prompts" / self.prompt_file
        if path.exists():
            with open(path) as f:
                data = yaml.safe_load(f)
            return {
                "system": data.get("system", ""),
                "user_template": data.get("user_template", "")
            }
        return {"system": "", "user_template": ""}

    async def _recall_memory(
        self,
        store: BaseStore,
        account_id: str,
        query: str,
        namespace: str,
        limit: int = 5
    ) -> list[dict]:
        """从长期记忆中检索"""
        if self.memory_manager is None:
            return []
        ns_map = {
            "content_history": self.memory_manager.content_history_ns,
            "audience_preferences": self.memory_manager.audience_ns,
            "performance_insights": self.memory_manager.insights_ns,
            "strategy_notes": self.memory_manager.strategy_ns,
        }
        ns = ns_map.get(namespace, self.memory_manager.insights_ns)
        items = await store.asearch(ns, query=query, limit=limit)
        return [item.value for item in items]

    def _parse_json_response(self, content: str) -> dict[str, Any]:
        """解析 LLM JSON 响应"""
        try:
            if "```json" in content:
                json_str = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                json_str = content.split("```")[1].split("```")[0].strip()
            else:
                json_str = content.strip()
            return json.loads(json_str)
        except (json.JSONDecodeError, IndexError):
            logger.warning(f"Failed to parse JSON from {self.agent_name}")
            return {"raw_content": content}

    @abstractmethod
    async def execute(
        self,
        state: XHSGrowthState,
        store: BaseStore
    ) -> dict[str, Any]:
        """执行 Agent 核心逻辑"""
        ...

    async def __call__(
        self,
        state: XHSGrowthState,
        *,
        store: BaseStore
    ) -> dict[str, Any]:
        """LangGraph node 入口点"""
        try:
            result = await self.execute(state, store)
            result["current_agent"] = self.agent_name
            return result
        except Exception as e:
            logger.error(f"Agent {self.agent_name} failed: {e}", exc_info=True)
            return {
                "error": f"{self.agent_name}: {type(e).__name__}: {e}",
                "phase": "error",
                "current_agent": self.agent_name,
            }
```

### 4.4 Agent 自动注册

```python
# agents/__init__.py - 自动注册所有 Agent

from xhs_growth.agents.factory import AgentFactory
from xhs_growth.agents.orchestrator import OrchestratorAgent
from xhs_growth.agents.trend_scout import TrendScoutAgent
from xhs_growth.agents.content_strategist import ContentStrategistAgent
from xhs_growth.agents.copywriter import CopywriterAgent
from xhs_growth.agents.visual_designer import VisualDesignerAgent
from xhs_growth.agents.publisher import PublisherAgent
from xhs_growth.agents.analyst import AnalystAgent
from xhs_growth.agents.engagement import EngagementAgent

# 自动注册
AgentFactory.register(OrchestratorAgent)
AgentFactory.register(TrendScoutAgent)
AgentFactory.register(ContentStrategistAgent)
AgentFactory.register(CopywriterAgent)
AgentFactory.register(VisualDesignerAgent)
AgentFactory.register(PublisherAgent)
AgentFactory.register(AnalystAgent)
AgentFactory.register(EngagementAgent)

__all__ = [
    "AgentFactory",
    "OrchestratorAgent",
    "TrendScoutAgent",
    "ContentStrategistAgent",
    "CopywriterAgent",
    "VisualDesignerAgent",
    "PublisherAgent",
    "AnalystAgent",
    "EngagementAgent",
]
```

---

## 五、API 响应与错误处理

### 5.1 统一响应封装

```python
# api/responses.py - 统一响应

from datetime import datetime, timezone
from typing import Any, Generic, TypeVar
from pydantic import BaseModel

T = TypeVar("T")

class ApiResponse(BaseModel, Generic[T]):
    """统一 API 响应格式"""
    success: bool
    data: T | None = None
    error: ErrorDetail | None = None
    timestamp: datetime = datetime.now(timezone.utc)
    request_id: str | None = None

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }

class ErrorDetail(BaseModel):
    """错误详情"""
    code: str
    message: str
    details: dict[str, Any] | None = None

def success(data: Any, request_id: str | None = None) -> ApiResponse:
    """成功响应"""
    return ApiResponse(success=True, data=data, request_id=request_id)

def error(
    code: str,
    message: str,
    details: dict | None = None,
    request_id: str | None = None
) -> ApiResponse:
    """错误响应"""
    return ApiResponse(
        success=False,
        error=ErrorDetail(code=code, message=message, details=details),
        request_id=request_id
    )
```

### 5.2 错误码定义

```python
# api/errors.py - 错误定义

from enum import Enum

class ErrorCode(str, Enum):
    """错误码枚举"""

    # Workflow 错误
    WORKFLOW_NOT_FOUND = "ERROR_WORKFLOW_NOT_FOUND"
    WORKFLOW_ALREADY_RUNNING = "ERROR_WORKFLOW_ALREADY_RUNNING"
    WORKFLOW_PHASE_INVALID = "ERROR_WORKFLOW_PHASE_INVALID"
    WORKFLOW_STATE_CORRUPT = "ERROR_WORKFLOW_STATE_CORRUPT"

    # Review 错误
    REVIEW_NOT_PENDING = "ERROR_REVIEW_NOT_PENDING"
    REVIEW_DECISION_INVALID = "ERROR_REVIEW_DECISION_INVALID"

    # Account 错误
    ACCOUNT_NOT_FOUND = "ERROR_ACCOUNT_NOT_FOUND"
    ACCOUNT_AUTH_FAILED = "ERROR_ACCOUNT_AUTH_FAILED"

    # Agent 错误
    AGENT_EXECUTION_FAILED = "ERROR_AGENT_EXECUTION_FAILED"
    AGENT_TIMEOUT = "ERROR_AGENT_TIMEOUT"

    # 服务错误
    SERVICE_UNAVAILABLE = "ERROR_SERVICE_UNAVAILABLE"
    XHS_API_ERROR = "ERROR_XHS_API_ERROR"

    # 通用错误
    INTERNAL_ERROR = "ERROR_INTERNAL"
    VALIDATION_ERROR = "ERROR_VALIDATION"
    RATE_LIMIT_EXCEEDED = "ERROR_RATE_LIMIT"

class APIError(Exception):
    """API 异常基类"""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        details: dict | None = None,
        status_code: int = 400
    ):
        self.code = code
        self.message = message
        self.details = details
        self.status_code = status_code
        super().__init__(message)

    def to_response(self, request_id: str | None = None) -> ApiResponse:
        """转换为 API 响应"""
        from xhs_growth.api.responses import error
        return error(
            code=self.code.value,
            message=self.message,
            details=self.details,
            request_id=request_id
        )

# 具体异常类
class WorkflowNotFoundError(APIError):
    def __init__(self, thread_id: str):
        super().__init__(
            code=ErrorCode.WORKFLOW_NOT_FOUND,
            message=f"Workflow '{thread_id}' not found",
            details={"thread_id": thread_id},
            status_code=404
        )

class ReviewNotPendingError(APIError):
    def __init__(self, thread_id: str, current_phase: str):
        super().__init__(
            code=ErrorCode.REVIEW_NOT_PENDING,
            message="No pending review for this workflow",
            details={"thread_id": thread_id, "current_phase": current_phase},
            status_code=400
        )

class ValidationError(APIError):
    def __init__(self, field: str, reason: str):
        super().__init__(
            code=ErrorCode.VALIDATION_ERROR,
            message=f"Validation failed: {field}",
            details={"field": field, "reason": reason},
            status_code=400
        )
```

### 5.3 异常处理中间件

```python
# api/middleware.py - 异常处理

import uuid
import logging
from fastapi import Request, Response
from fastapi.responses import JSONResponse

from xhs_growth.api.errors import APIError, ErrorCode
from xhs_growth.api.responses import error

logger = logging.getLogger("xhs_growth.api")

async def error_handler_middleware(request: Request, call_next) -> Response:
    """统一异常处理中间件"""
    request_id = str(uuid.uuid4())[:8]

    try:
        response = await call_next(request)
        return response

    except APIError as e:
        logger.warning(f"API Error: {e.code.value} - {e.message}")
        return JSONResponse(
            status_code=e.status_code,
            content=e.to_response(request_id).model_dump(mode='json')
        )

    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        return JSONResponse(
            status_code=500,
            content=error(
                code=ErrorCode.INTERNAL_ERROR.value,
                message="Internal server error",
                details={"exception": str(e)},
                request_id=request_id
            ).model_dump(mode='json')
        )
```

### 5.4 路由改造示例

```python
# api/routes/workflow.py - 改造后的路由

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Request

from xhs_growth.api.responses import success
from xhs_growth.api.errors import WorkflowNotFoundError, ValidationError
from xhs_growth.api.generated.models import (
    WorkflowStartRequest,
    WorkflowResponse,
    WorkflowState,
)

router = APIRouter()

@router.post("/start")
async def start_workflow(req: WorkflowStartRequest, request: Request):
    """启动工作流"""
    if not req.account_id:
        raise ValidationError("account_id", "account_id is required")

    graph = request.app.state.graph
    thread_id = f"xhs_{req.account_id}_{uuid.uuid4().hex[:8]}"

    initial_state = {
        "phase": req.phase.value if req.phase else "scouting",
        "current_agent": "orchestrator",
        "account_id": req.account_id,
        "session_id": thread_id,
        "error": None,
        "retry_count": 0,
        "messages": [],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    config = {"configurable": {"thread_id": thread_id}}
    result = await graph.ainvoke(initial_state, config)

    return success(
        data=WorkflowResponse(
            thread_id=thread_id,
            status="running",
            phase=result.get("phase", "unknown")
        )
    )

@router.get("/status/{thread_id}")
async def get_workflow_status(thread_id: str, request: Request):
    """获取工作流状态"""
    graph = request.app.state.graph
    config = {"configurable": {"thread_id": thread_id}}

    state = await graph.aget_state(config)

    if not state.values:
        raise WorkflowNotFoundError(thread_id)

    values = state.values

    return success(
        data=WorkflowState(
            thread_id=thread_id,
            phase=values.get("phase", "idle"),
            current_agent=values.get("current_agent", ""),
            trend_data=values.get("trend_data"),
            content_plan=values.get("content_plan"),
            copy_content=values.get("copy_content"),
            visual_plan=values.get("visual_plan"),
            error=values.get("error"),
            created_at=values.get("created_at"),
            updated_at=values.get("updated_at"),
        )
    )
```

---

## 六、类型生成与同步流程

### 6.1 生成工具选择

- **后端**: `datamodel-code-generator` → Pydantic v2 模型
- **前端**: `openapi-ts` → TypeScript 类型 + Fetch 客户端

### 6.2 生成脚本

```bash
# scripts/generate_types.sh

#!/bin/bash
set -e

echo "=== Generating types from OpenAPI spec ==="

# 后端：Pydantic 模型
echo "Generating Python Pydantic models..."
datamodel-codegen \
  --input api/spec/openapi.yaml \
  --output xhs_growth/api/generated/models.py \
  --output-model-type pydantic-v2.BaseModel \
  --field-constraints \
  --use-annotated \
  --strict-types \
  --snake-case-field \
  --capitalize-enum-members \
  --use-double-quotes

# 前端：TypeScript 类型 + API 客户端
echo "Generating TypeScript types and client..."
openapi-ts \
  --input api/spec/openapi.yaml \
  --output frontend/src/api/generated \
  --client fetch \
  --name XhsGrowthClient \
  --use-enums \
  --use-date-type \
  --indent 2

echo "=== Generation complete ==="
```

### 6.3 Makefile 集成

```makefile
# Makefile

.PHONY: gen-types gen-python gen-ts lint lint-types test

# 类型生成
gen-types: gen-python gen-ts

gen-python:
	datamodel-codegen \
		--input api/spec/openapi.yaml \
		--output xhs_growth/api/generated/models.py \
		--output-model-type pydantic-v2.BaseModel \
		--strict-types

gen-ts:
	cd frontend && npm run gen-api  # 调用前端脚本

# Lint
lint:
	ruff check xhs_growth
	ruff format xhs_growth --check

lint-types:
	ruff check xhs_growth/api/generated/models.py
	cd frontend && npm run type-check

# 测试
test:
	pytest tests/ -v

test-unit:
	pytest tests/unit/ -v

test-integration:
	pytest tests/integration/ -v

test-contract:
	pytest tests/contract/ -v
```

### 6.4 CI 契约检查

```yaml
# .github/workflows/api-types.yml

name: API Types Check

on:
  push:
    paths:
      - 'api/spec/openapi.yaml'
  pull_request:
    paths:
      - 'api/spec/openapi.yaml'

jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Setup Node.js
        uses: actions/setup-node@v4
        with:
          node-version: '20'

      - name: Install tools
        run: |
          pip install datamodel-code-generator ruff
          cd frontend && npm install

      - name: Generate types
        run: make gen-types

      - name: Check for uncommitted changes
        run: |
          git diff --exit-code xhs_growth/api/generated/models.py
          git diff --exit-code frontend/src/api/generated/

      - name: Lint generated code
        run: make lint-types

      - name: Run contract tests
        run: pytest tests/contract/ -v
```

### 6.5 前端使用示例

```typescript
// frontend/src/api/client.ts

import { XhsGrowthClient } from './generated'

const client = new XhsGrowthClient({
  baseUrl: '/api',
})

export const workflowApi = client.workflow
export const reviewApi = client.review
export const analyticsApi = client.analytics

export default client

// frontend/src/stores/workflow.ts

import { defineStore } from 'pinia'
import { ref } from 'vue'
import { workflowApi } from '@/api/client'
import type { WorkflowResponse, WorkflowState } from '@/api/generated/models'

export const useWorkflowStore = defineStore('workflow', () => {
  const currentThreadId = ref<string | null>(null)
  const workflowState = ref<WorkflowState | null>(null)

  async function startWorkflow(accountId: string) {
    const response = await workflowApi.start({
      account_id: accountId,
      phase: 'scouting'
    })

    if (response.success && response.data) {
      currentThreadId.value = response.data.thread_id
      return response.data
    }

    throw new Error(response.error?.message || 'Failed to start workflow')
  }

  async function refreshStatus() {
    if (!currentThreadId.value) return

    const response = await workflowApi.getStatus(currentThreadId.value)

    if (response.success && response.data) {
      workflowState.value = response.data
    }
  }

  return {
    currentThreadId,
    workflowState,
    startWorkflow,
    refreshStatus,
  }
})
```

---

## 七、测试策略

### 7.1 测试分层

```
tests/
├── unit/           # 单元测试（隔离测试单个模块）
├── integration/    # 集成测试（测试模块间交互）
├── contract/       # 契约测试（验证前后端类型同步）
```

### 7.2 单元测试覆盖

- DI 容器：注册/获取/清空
- Agent 工厂：注册/创建
- Base Agent：模型加载、JSON 解析
- 响应封装：success/error 序列化
- 错误类：转换响应

### 7.3 集成测试覆盖

- API 路由：完整请求/响应流程
- 工作流执行：LangGraph 图运行
- 人工审核：review_gate 流程

### 7.4 契约测试覆盖

- OpenAPI 规范有效
- 枚举同步：Python ↔ OpenAPI ↔ TypeScript
- 生成的类型文件存在

---

## 八、实施步骤

### Phase 1: 基础架构搭建（优先级：高）

1. 创建 `api/spec/openapi.yaml` 规范文件
2. 设置类型生成工具和脚本
3. 创建 DI 容器和 Agent 工厂
4. 定义统一响应和错误处理

### Phase 2: 状态 Schema 重构（优先级：高）

1. 创建 `state/enums.py` 统一枚举
2. 创建 `state/substates.py` 子状态模块
3. 简化 `state/schema.py` 主状态
4. 更现有 reducers

### Phase 3: API 路由改造（优先级：中）

1. 生成 Pydantic 模型
2. 改造 workflow 路由
3. 改造 review 路由
4. 改造 analytics 路由
5. 添加异常处理中间件

### Phase 4: Agent 改造（优先级：中）

1. 改造 BaseAgent 支持依赖注入
2. 更新各 Agent 实现
3. 自动注册所有 Agent
4. 更新 graph/nodes.py 使用工厂

### Phase 5: 前端同步（优先级：高）

1. 生成 TypeScript 类型和客户端
2. 更新 frontend stores 使用生成 API
3. 更新 components 类型引用
4. 删除手动定义的类型文件

### Phase 6: 测试与验证（优先级：高）

1. 编写单元测试
2. 编写集成测试
3. 编写契约测试
4. CI 配置契约检查

---

## 九、风险与缓解

| 风险 | 缓解措施 |
|------|----------|
| OpenAPI 规范维护复杂 | 使用 Swagger Editor 验证，CI 自动检查 |
| 生成的类型不满足需求 | 在 schemas.py 添加自定义补充模型 |
| DI 容器引入复杂性 | 保持容器轻量，提供 clear() 测试支持 |
| Agent 改造影响现有逻辑 | 逐步迁移，保持 execute 方法签名不变 |
| 前端改造范围大 | 先生成类型，逐步替换手动定义 |

---

## 十、验收标准

1. **类型一致性**: OpenAPI ↔ Python ↔ TypeScript 枚举完全同步
2. **API 规范**: 所有响应遵循 ApiResponse 格式
3. **错误处理**: 所有异常返回标准化 ErrorDetail
4. **DI 可测性**: 所有 Agent/服务可通过容器注入和清空
5. **测试覆盖**: 单元/集成/契约测试全部通过
6. **CI 通过**: 契约检查 workflow 无报错

---

## 相关文档

- [[openapi-best-practices]] - OpenAPI 规范最佳实践（待补充）
- [[di-patterns]] - Python 依赖注入模式（待补充）