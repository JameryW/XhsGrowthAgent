# Backend Architecture Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 重构后端架构为 OpenAPI 契约优先设计，实现前后端类型自动同步、Agent/服务依赖注入、统一 API 响应格式。

**Architecture:** OpenAPI YAML 作为唯一类型源，自动生成 Python Pydantic 模型和 TypeScript 类型；轻量级 DI 容器管理 Agent/服务；TypedDict 简化内部状态，子状态模块化。

**Tech Stack:** Python 3.12 + FastAPI + Pydantic v2 + LangGraph; TypeScript + Vue 3 + Pinia; datamodel-code-generator + openapi-ts

---

## File Structure Map

### 新建文件
```
api/spec/openapi.yaml           # OpenAPI 3.1 规范（核心）
xhs_growth/core/__init__.py     # core 模块导出
xhs_growth/core/di.py           # 依赖注入容器
xhs_growth/state/enums.py       # 统一枚举定义
xhs_growth/state/substates.py   # 子状态模块
xhs_growth/agents/factory.py    # Agent 工厂
xhs_growth/api/responses.py     # 统一响应封装
xhs_growth/api/errors.py        # 错误码和异常类
xhs_growth/api/middleware.py    # 异常处理中间件
xhs_growth/api/generated/       # 生成的 Pydantic 模型目录
scripts/generate_types.sh       # 类型生成脚本
tests/unit/core/test_di.py      # DI 容器测试
tests/unit/api/test_responses.py # 响应封装测试
tests/unit/api/test_errors.py   # 错误处理测试
tests/contract/test_openapi_spec.py # 契约测试
tests/contract/test_type_sync.py   # 类型同步测试
```

### 修改文件
```
xhs_growth/state/schema.py      # 简化主状态，引用 substates
xhs_growth/state/reducers.py    # 保持现有，添加导出
xhs_growth/agents/base.py       # 支持 DI 参数注入
xhs_growth/agents/__init__.py   # 添加 AgentFactory 注册
xhs_growth/graph/nodes.py       # 使用 AgentFactory 创建节点
xhs_growth/api/app.py           # 添加中间件，更新路由导入
xhs_growth/api/routes/workflow.py # 改用统一响应
xhs_growth/api/routes/review.py   # 改用统一响应
xhs_growth/api/routes/analytics.py # 改用统一响应
frontend/src/api/client.ts      # 使用生成的客户端
frontend/src/stores/workflow.ts # 使用生成类型
frontend/src/stores/review.ts   # 使用生成类型
pyproject.toml                  # 添加生成工具依赖
Makefile                        # 添加类型生成命令
```

---

## Phase 1: 基础架构搭建

### Task 1: 创建 OpenAPI 规范文件

**Files:**
- Create: `api/spec/openapi.yaml`

- [ ] **Step 1: 创建规范目录和基础结构**

```bash
mkdir -p api/spec
```

- [ ] **Step 2: 编写 OpenAPI 规范（完整版）**

```yaml
# api/spec/openapi.yaml

openapi: 3.1.0
info:
  title: XHS Growth Engine API
  version: 1.0.0
  description: 小红书增长引擎 Agent API - OpenAPI 契约优先设计

servers:
  - url: /api
    description: API server

tags:
  - name: workflow
    description: Workflow lifecycle management
  - name: review
    description: Human-in-the-loop content review
  - name: analytics
    description: Growth analytics and reporting

paths:
  # === Workflow ===
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
          description: Workflow started
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

  # === Review ===
  /review/pending/{thread_id}:
    get:
      tags: [review]
      operationId: getPendingReview
      summary: Get pending review content
      parameters:
        - name: thread_id
          in: path
          required: true
          schema:
            type: string
      responses:
        '200':
          description: Pending review
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

  # === Analytics ===
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
      summary: Get LLM costs
      responses:
        '200':
          description: Cost report
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ApiResponse_CostReport'

components:
  schemas:
    # === 统一响应 ===
    ApiResponse:
      type: object
      required: [success, timestamp]
      properties:
        success:
          type: boolean
        data:
          type: object
        error:
          $ref: '#/components/schemas/ErrorDetail'
        timestamp:
          type: string
          format: date-time
        request_id:
          type: string

    ErrorDetail:
      type: object
      required: [code, message]
      properties:
        code:
          type: string
        message:
          type: string
        details:
          type: object
          additionalProperties: true

    # === 泛型响应 ===
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
      enum: [idle, scouting, planning, creating, reviewing, publishing, analyzing, engaging, completed, error]

    ContentStatus:
      type: string
      enum: [approved, needs_revision, rejected, draft, pending_review, published, failed]

    ContentType:
      type: string
      enum: [note, video, carousel]

    Urgency:
      type: string
      enum: [low, medium, high, trending]

    WorkflowStatus:
      type: string
      enum: [running, paused, completed, error]

    # === Workflow ===
    WorkflowStartRequest:
      type: object
      required: [account_id]
      properties:
        account_id:
          type: string
          minLength: 1
        phase:
          $ref: '#/components/schemas/WorkflowPhase'

    WorkflowResponse:
      type: object
      required: [thread_id, status, phase]
      properties:
        thread_id:
          type: string
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

    # === Review ===
    PendingReview:
      type: object
      required: [status]
      properties:
        status:
          type: string
          enum: [awaiting_review, no_pending_review]
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

    # === Analytics ===
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

    # === Sub-states ===
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

    NicheOpportunity:
      type: object
      properties:
        topic:
          type: string
        potential_score:
          type: number
          minimum: 0
          maximum: 100
        audience_match:
          type: string
        entry_barrier:
          type: string
          enum: [low, medium, high]

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
        emoji_usage:
          type: array
          items:
            type: string
        tone:
          type: string

    VisualPlan:
      type: object
      properties:
        cover_prompt:
          type: string
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
        font_suggestion:
          type: string
        brand_elements:
          type: array
          items:
            type: string

  responses:
    BadRequest:
      description: Bad request
      content:
        application/json:
          schema:
            $ref: '#/components/schemas/ApiResponse'
          example:
            success: false
            error:
              code: ERROR_VALIDATION
              message: Invalid request
            timestamp: "2026-05-25T00:00:00Z"

    NotFound:
      description: Not found
      content:
        application/json:
          schema:
            $ref: '#/components/schemas/ApiResponse'
          example:
            success: false
            error:
              code: ERROR_WORKFLOW_NOT_FOUND
              message: Workflow not found
            timestamp: "2026-05-25T00:00:00Z"

    InternalError:
      description: Internal error
      content:
        application/json:
          schema:
            $ref: '#/components/schemas/ApiResponse'
          example:
            success: false
            error:
              code: ERROR_INTERNAL
              message: Internal server error
            timestamp: "2026-05-25T00:00:00Z"
```

- [ ] **Step 3: 提交 OpenAPI 规范**

```bash
git add api/spec/openapi.yaml
git commit -m "feat: add OpenAPI 3.1 specification for XHS Growth Engine API"
```

---

### Task 2: 创建依赖注入容器

**Files:**
- Create: `xhs_growth/core/__init__.py`
- Create: `xhs_growth/core/di.py`
- Create: `tests/unit/core/__init__.py`
- Create: `tests/unit/core/test_di.py`

- [ ] **Step 1: 编写 DI 容器测试**

```python
# tests/unit/core/test_di.py

import pytest
from xhs_growth.core.di import ServiceContainer, get_container, reset_container

class MockService:
    def __init__(self, value: str = "default"):
        self.value = value

def setup_function():
    reset_container()

def test_container_register_instance():
    """测试注册实例"""
    container = ServiceContainer()
    service = MockService("instance")
    container.register_instance("mock", service)

    result = container.get("mock")
    assert result.value == "instance"
    assert result is service

def test_container_register_factory():
    """测试注册工厂"""
    container = ServiceContainer()
    container.register_factory("mock", lambda: MockService("factory"))

    result1 = container.get("mock")
    result2 = container.get("mock")

    assert result1.value == "factory"
    assert result1 is result2  # 缓存为单例

def test_container_not_found():
    """测试服务未注册"""
    container = ServiceContainer()
    with pytest.raises(KeyError, match="Service 'unknown' not registered"):
        container.get("unknown")

def test_container_has():
    """测试检查服务存在"""
    container = ServiceContainer()
    assert container.has("unknown") is False

    container.register_instance("mock", MockService())
    assert container.has("mock") is True

def test_container_clear():
    """测试清空容器"""
    container = ServiceContainer()
    container.register_instance("mock", MockService())
    container.clear()

    with pytest.raises(KeyError):
        container.get("mock")

def test_get_container():
    """测试获取全局容器"""
    container = get_container()
    assert isinstance(container, ServiceContainer)

def test_reset_container():
    """测试重置全局容器"""
    container1 = get_container()
    container1.register_instance("test", MockService())

    reset_container()
    container2 = get_container()

    with pytest.raises(KeyError):
        container2.get("test")
```

- [ ] **Step 2: 运行测试验证失败**

```bash
pytest tests/unit/core/test_di.py -v
```

Expected: FAIL (module not found)

- [ ] **Step 3: 创建 core 模块目录**

```bash
mkdir -p xhs_growth/core tests/unit/core
```

- [ ] **Step 4: 实现 DI 容器**

```python
# xhs_growth/core/di.py

"""Dependency Injection container for service management."""

from typing import Callable, Any
import logging

logger = logging.getLogger("xhs_growth.di")


class ServiceContainer:
    """Lightweight dependency injection container."""

    def __init__(self):
        self._services: dict[str, Any] = {}
        self._factories: dict[str, Callable[[], Any]] = {}

    def register_instance(self, name: str, instance: Any) -> None:
        """Register a singleton instance."""
        self._services[name] = instance
        logger.debug(f"Registered instance: {name}")

    def register_factory(self, name: str, factory: Callable[[], Any]) -> None:
        """Register a factory function (lazy creation, cached as singleton)."""
        self._factories[name] = factory
        logger.debug(f"Registered factory: {name}")

    def get(self, name: str) -> Any:
        """Get service by name (factory results are cached)."""
        if name in self._services:
            return self._services[name]
        if name in self._factories:
            instance = self._factories[name]()
            self._services[name] = instance
            logger.debug(f"Created service from factory: {name}")
            return instance
        raise KeyError(f"Service '{name}' not registered")

    def has(self, name: str) -> bool:
        """Check if service is registered."""
        return name in self._services or name in self._factories

    def clear(self) -> None:
        """Clear all registrations (for testing)."""
        self._services.clear()
        self._factories.clear()
        logger.debug("Container cleared")


# Global container instance
_container: ServiceContainer | None = None


def get_container() -> ServiceContainer:
    """Get the global container instance."""
    global _container
    if _container is None:
        _container = ServiceContainer()
    return _container


def reset_container() -> None:
    """Reset the global container (for testing)."""
    global _container
    _container = ServiceContainer()
```

- [ ] **Step 5: 创建 core 模块导出**

```python
# xhs_growth/core/__init__.py

"""Core utilities - dependency injection and configuration."""

from xhs_growth.core.di import ServiceContainer, get_container, reset_container

__all__ = ["ServiceContainer", "get_container", "reset_container"]
```

- [ ] **Step 6: 创建测试目录导出**

```python
# tests/unit/core/__init__.py
```

- [ ] **Step 7: 运行测试验证通过**

```bash
pytest tests/unit/core/test_di.py -v
```

Expected: PASS

- [ ] **Step 8: 提交 DI 容器**

```bash
git add xhs_growth/core tests/unit/core
git commit -m "feat: add lightweight DI container with factory and instance support"
```

---

### Task 3: 创建统一响应和错误处理

**Files:**
- Create: `xhs_growth/api/responses.py`
- Create: `xhs_growth/api/errors.py`
- Create: `xhs_growth/api/middleware.py`
- Create: `tests/unit/api/__init__.py`
- Create: `tests/unit/api/test_responses.py`
- Create: `tests/unit/api/test_errors.py`

- [ ] **Step 1: 编写响应封装测试**

```python
# tests/unit/api/test_responses.py

import pytest
from datetime import datetime
from xhs_growth.api.responses import ApiResponse, success, error, ErrorDetail

def test_success_response():
    """测试成功响应"""
    response = success({"thread_id": "test123"})

    assert response.success is True
    assert response.data == {"thread_id": "test123"}
    assert response.error is None
    assert isinstance(response.timestamp, datetime)

def test_error_response():
    """测试错误响应"""
    response = error(
        code="ERROR_WORKFLOW_NOT_FOUND",
        message="Workflow not found",
        details={"thread_id": "test123"}
    )

    assert response.success is False
    assert response.data is None
    assert response.error.code == "ERROR_WORKFLOW_NOT_FOUND"
    assert response.error.message == "Workflow not found"
    assert response.error.details == {"thread_id": "test123"}

def test_api_response_serialization():
    """测试响应序列化"""
    response = ApiResponse(
        success=True,
        data={"phase": "scouting"},
        timestamp=datetime.now()
    )

    json_data = response.model_dump(mode="json")
    assert "success" in json_data
    assert "data" in json_data
    assert "timestamp" in json_data

def test_error_detail_str():
    """测试错误详情字符串"""
    detail = ErrorDetail(code="ERROR_TEST", message="Test error")
    assert str(detail) == "[ERROR_TEST] Test error"
```

- [ ] **Step 2: 编写错误处理测试**

```python
# tests/unit/api/test_errors.py

import pytest
from xhs_growth.api.errors import (
    ErrorCode, APIError,
    WorkflowNotFoundError, ValidationError, ReviewNotPendingError
)

def test_error_code_enum():
    """测试错误码枚举"""
    assert ErrorCode.WORKFLOW_NOT_FOUND.value == "ERROR_WORKFLOW_NOT_FOUND"
    assert ErrorCode.VALIDATION_ERROR.value == "ERROR_VALIDATION"

def test_workflow_not_found_error():
    """测试工作流未找到异常"""
    exc = WorkflowNotFoundError("test123")

    assert exc.code == ErrorCode.WORKFLOW_NOT_FOUND
    assert exc.status_code == 404
    assert "test123" in exc.message
    assert exc.details["thread_id"] == "test123"

def test_validation_error():
    """测试验证错误"""
    exc = ValidationError("account_id", "is required")

    assert exc.code == ErrorCode.VALIDATION_ERROR
    assert exc.status_code == 400
    assert exc.details["field"] == "account_id"

def test_api_error_to_response():
    """测试异常转换为响应"""
    exc = WorkflowNotFoundError("test123")
    response = exc.to_response("req001")

    assert response.success is False
    assert response.request_id == "req001"
    assert response.error.code == ErrorCode.WORKFLOW_NOT_FOUND.value
```

- [ ] **Step 3: 运行测试验证失败**

```bash
pytest tests/unit/api/test_responses.py tests/unit/api/test_errors.py -v
```

Expected: FAIL (module not found)

- [ ] **Step 4: 创建测试目录**

```bash
mkdir -p tests/unit/api
```

- [ ] **Step 5: 实现响应封装**

```python
# xhs_growth/api/responses.py

"""Unified API response format."""

from datetime import datetime, timezone
from typing import Any, Generic, TypeVar
from pydantic import BaseModel

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """Unified API response envelope."""

    success: bool
    data: T | None = None
    error: ErrorDetail | None = None
    timestamp: datetime = datetime.now(timezone.utc)
    request_id: str | None = None


class ErrorDetail(BaseModel):
    """Error detail structure."""

    code: str
    message: str
    details: dict[str, Any] | None = None

    def __str__(self) -> str:
        return f"[{self.code}] {self.message}"


def success(data: Any, request_id: str | None = None) -> ApiResponse:
    """Create success response."""
    return ApiResponse(success=True, data=data, request_id=request_id)


def error(
    code: str,
    message: str,
    details: dict | None = None,
    request_id: str | None = None,
) -> ApiResponse:
    """Create error response."""
    return ApiResponse(
        success=False,
        error=ErrorDetail(code=code, message=message, details=details),
        request_id=request_id,
    )
```

- [ ] **Step 6: 实现错误定义**

```python
# xhs_growth/api/errors.py

"""Standardized error codes and exception classes."""

from enum import Enum

from xhs_growth.api.responses import error, ApiResponse


class ErrorCode(str, Enum):
    """Standard error codes."""

    # Workflow errors
    WORKFLOW_NOT_FOUND = "ERROR_WORKFLOW_NOT_FOUND"
    WORKFLOW_ALREADY_RUNNING = "ERROR_WORKFLOW_ALREADY_RUNNING"
    WORKFLOW_PHASE_INVALID = "ERROR_WORKFLOW_PHASE_INVALID"
    WORKFLOW_STATE_CORRUPT = "ERROR_WORKFLOW_STATE_CORRUPT"

    # Review errors
    REVIEW_NOT_PENDING = "ERROR_REVIEW_NOT_PENDING"
    REVIEW_DECISION_INVALID = "ERROR_REVIEW_DECISION_INVALID"

    # Account errors
    ACCOUNT_NOT_FOUND = "ERROR_ACCOUNT_NOT_FOUND"
    ACCOUNT_AUTH_FAILED = "ERROR_ACCOUNT_AUTH_FAILED"

    # Agent errors
    AGENT_EXECUTION_FAILED = "ERROR_AGENT_EXECUTION_FAILED"
    AGENT_TIMEOUT = "ERROR_AGENT_TIMEOUT"

    # Service errors
    SERVICE_UNAVAILABLE = "ERROR_SERVICE_UNAVAILABLE"
    XHS_API_ERROR = "ERROR_XHS_API_ERROR"

    # General errors
    INTERNAL_ERROR = "ERROR_INTERNAL"
    VALIDATION_ERROR = "ERROR_VALIDATION"
    RATE_LIMIT_EXCEEDED = "ERROR_RATE_LIMIT"


class APIError(Exception):
    """Base API exception."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        details: dict | None = None,
        status_code: int = 400,
    ):
        self.code = code
        self.message = message
        self.details = details
        self.status_code = status_code
        super().__init__(message)

    def to_response(self, request_id: str | None = None) -> ApiResponse:
        """Convert to API response."""
        return error(
            code=self.code.value,
            message=self.message,
            details=self.details,
            request_id=request_id,
        )


class WorkflowNotFoundError(APIError):
    """Workflow not found exception."""

    def __init__(self, thread_id: str):
        super().__init__(
            code=ErrorCode.WORKFLOW_NOT_FOUND,
            message=f"Workflow '{thread_id}' not found",
            details={"thread_id": thread_id},
            status_code=404,
        )


class ReviewNotPendingError(APIError):
    """No pending review exception."""

    def __init__(self, thread_id: str, current_phase: str):
        super().__init__(
            code=ErrorCode.REVIEW_NOT_PENDING,
            message="No pending review for this workflow",
            details={"thread_id": thread_id, "current_phase": current_phase},
            status_code=400,
        )


class ValidationError(APIError):
    """Validation error exception."""

    def __init__(self, field: str, reason: str):
        super().__init__(
            code=ErrorCode.VALIDATION_ERROR,
            message=f"Validation failed: {field}",
            details={"field": field, "reason": reason},
            status_code=400,
        )
```

- [ ] **Step 7: 实现异常处理中间件**

```python
# xhs_growth/api/middleware.py

"""Exception handling middleware."""

import uuid
import logging
from fastapi import Request, Response
from fastapi.responses import JSONResponse

from xhs_growth.api.errors import APIError, ErrorCode
from xhs_growth.api.responses import error

logger = logging.getLogger("xhs_growth.api")


async def error_handler_middleware(request: Request, call_next) -> Response:
    """Unified exception handling middleware."""
    request_id = str(uuid.uuid4())[:8]

    try:
        response = await call_next(request)
        return response

    except APIError as e:
        logger.warning(f"API Error [{request_id}]: {e.code.value} - {e.message}")
        return JSONResponse(
            status_code=e.status_code,
            content=e.to_response(request_id).model_dump(mode="json"),
        )

    except Exception as e:
        logger.exception(f"Unexpected error [{request_id}]: {e}")
        return JSONResponse(
            status_code=500,
            content=error(
                code=ErrorCode.INTERNAL_ERROR.value,
                message="Internal server error",
                details={"exception": str(e)},
                request_id=request_id,
            ).model_dump(mode="json"),
        )
```

- [ ] **Step 8: 创建测试导出**

```python
# tests/unit/api/__init__.py
```

- [ ] **Step 9: 运行测试验证通过**

```bash
pytest tests/unit/api/ -v
```

Expected: PASS

- [ ] **Step 10: 提交响应和错误处理**

```bash
git add xhs_growth/api/responses.py xhs_growth/api/errors.py xhs_growth/api/middleware.py tests/unit/api
git commit -m "feat: add unified API response format and error handling"
```

---

## Phase 2: State Schema 重构

### Task 4: 创建统一枚举定义

**Files:**
- Create: `xhs_growth/state/enums.py`
- Modify: `xhs_growth/state/__init__.py`
- Create: `tests/unit/state/__init__.py`
- Create: `tests/unit/state/test_enums.py`

- [ ] **Step 1: 编写枚举测试**

```python
# tests/unit/state/test_enums.py

import pytest
from xhs_growth.state.enums import WorkflowPhase, ContentStatus, ContentType, Urgency

def test_workflow_phase_values():
    """测试 WorkflowPhase 枚举值"""
    assert WorkflowPhase.IDLE.value == "idle"
    assert WorkflowPhase.SCOUTING.value == "scouting"
    assert WorkflowPhase.COMPLETED.value == "completed"
    assert WorkflowPhase.ERROR.value == "error"

def test_content_status_values():
    """测试 ContentStatus 枚举值"""
    assert ContentStatus.APPROVED.value == "approved"
    assert ContentStatus.NEEDS_REVISION.value == "needs_revision"
    assert ContentStatus.REJECTED.value == "rejected"

def test_enum_string_conversion():
    """测试枚举字符串转换"""
    phase = WorkflowPhase.SCOUTING
    assert str(phase) == "scouting"
    assert phase == "scouting"  # str enum 特性

def test_enum_from_string():
    """测试从字符串创建枚举"""
    status = ContentStatus("approved")
    assert status == ContentStatus.APPROVED
```

- [ ] **Step 2: 运行测试验证失败**

```bash
pytest tests/unit/state/test_enums.py -v
```

Expected: FAIL (module not found)

- [ ] **Step 3: 创建测试目录**

```bash
mkdir -p tests/unit/state
```

- [ ] **Step 4: 实现枚举定义**

```python
# xhs_growth/state/enums.py

"""Unified enum definitions - synced with OpenAPI specification."""

from enum import Enum


class WorkflowPhase(str, Enum):
    """Workflow execution phase."""

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
    """Content review status."""

    APPROVED = "approved"
    NEEDS_REVISION = "needs_revision"
    REJECTED = "rejected"
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    PUBLISHED = "published"
    FAILED = "failed"


class ContentType(str, Enum):
    """Content type."""

    NOTE = "note"
    VIDEO = "video"
    CAROUSEL = "carousel"


class Urgency(str, Enum):
    """Content urgency level."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    TRENDING = "trending"
```

- [ ] **Step 5: 创建测试导出**

```python
# tests/unit/state/__init__.py
```

- [ ] **Step 6: 更新 state 模块导出**

```python
# xhs_growth/state/__init__.py

"""State management module."""

from xhs_growth.state.schema import XHSGrowthState
from xhs_growth.state.enums import WorkflowPhase, ContentStatus, ContentType, Urgency
from xhs_growth.state.reducers import merge_dict, append_list, replace, max_value

__all__ = [
    "XHSGrowthState",
    "WorkflowPhase",
    "ContentStatus",
    "ContentType",
    "Urgency",
    "merge_dict",
    "append_list",
    "replace",
    "max_value",
]
```

- [ ] **Step 7: 运行测试验证通过**

```bash
pytest tests/unit/state/test_enums.py -v
```

Expected: PASS

- [ ] **Step 8: 提交枚举定义**

```bash
git add xhs_growth/state/enums.py xhs_growth/state/__init__.py tests/unit/state
git commit -m "feat: add unified enum definitions synced with OpenAPI"
```

---

### Task 5: 创建子状态模块

**Files:**
- Create: `xhs_growth/state/substates.py`
- Modify: `xhs_growth/state/schema.py`

- [ ] **Step 1: 创建子状态定义**

```python
# xhs_growth/state/substates.py

"""Sub-state TypedDict definitions for modular state management."""

from typing import TypedDict, Any
from xhs_growth.state.enums import ContentType, Urgency, ContentStatus


class HotTopicItem(TypedDict, total=False):
    """Hot topic item."""
    topic: str
    heat_score: float
    growth_rate: float
    related_keywords: list[str]


class NicheOpportunity(TypedDict, total=False):
    """Niche opportunity."""
    topic: str
    potential_score: float
    audience_match: str
    entry_barrier: str


class CompetitorPost(TypedDict, total=False):
    """Competitor post."""
    title: str
    likes: int
    comments: int
    author: str


class TrendData(TypedDict, total=False):
    """Trend scouting result."""
    hot_topics: list[HotTopicItem]
    trending_keywords: list[str]
    competitor_posts: list[CompetitorPost]
    niche_opportunities: list[NicheOpportunity]
    timestamp: str


class ContentPlan(TypedDict, total=False):
    """Content strategy plan."""
    selected_topic: str
    content_angle: str
    content_type: ContentType
    target_audience: str
    key_points: list[str]
    suggested_timing: str
    hashtags: list[str]
    urgency: Urgency


class CopyContent(TypedDict, total=False):
    """Copy content."""
    title_candidates: list[str]
    selected_title: str
    body_text: str
    hashtags: list[str]
    cta: str
    emoji_usage: list[str]
    tone: str


class VisualPlan(TypedDict, total=False):
    """Visual design plan."""
    cover_prompt: str
    image_count: int
    image_prompts: list[str]
    layout_style: str
    color_palette: list[str]
    font_suggestion: str
    brand_elements: list[str]


class PublishResult(TypedDict, total=False):
    """Publish result."""
    post_id: str
    post_url: str
    published_at: str
    ab_variant: str | None
    status: ContentStatus


class AnalyticsSnapshot(TypedDict, total=False):
    """Analytics snapshot."""
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
    """Human review feedback."""
    decision: ContentStatus
    comments: str
    revisions: list[str]
    reviewer: str


class EngagementAction(TypedDict, total=False):
    """Engagement action."""
    action_type: str
    target_id: str
    content: str
    timestamp: str


class RipplePrediction(TypedDict, total=False):
    """Ripple CAS prediction result."""
    job_id: str
    estimated_reach: int
    estimated_engagement: int
    viral_probability: float
    phase: str
    confidence: float
    key_influencers: list[dict[str, Any]]
    spread_path: list[dict[str, Any]]


class RipplePMFResult(TypedDict, total=False):
    """Ripple PMF validation result."""
    job_id: str
    pmf_score: float
    risk_factors: list[str]
    improvement_strategies: list[str]
    market_segment: dict[str, Any]
    confidence: float


__all__ = [
    "HotTopicItem",
    "NicheOpportunity",
    "CompetitorPost",
    "TrendData",
    "ContentPlan",
    "CopyContent",
    "VisualPlan",
    "PublishResult",
    "AnalyticsSnapshot",
    "HumanFeedback",
    "EngagementAction",
    "RipplePrediction",
    "RipplePMFResult",
]
```

- [ ] **Step 2: 简化主状态 Schema**

```python
# xhs_growth/state/schema.py

"""Main state schema - simplified with modular sub-states."""

from typing import Annotated, NotRequired
from langgraph.graph.message import add_messages

from xhs_growth.state.enums import WorkflowPhase
from xhs_growth.state.substates import (
    TrendData,
    ContentPlan,
    CopyContent,
    VisualPlan,
    PublishResult,
    AnalyticsSnapshot,
    HumanFeedback,
    EngagementAction,
    RipplePrediction,
    RipplePMFResult,
)
from xhs_growth.state.reducers import append_list


class XHSGrowthState(TypedDict):
    """XHS Growth Engine global state."""

    # === Required fields ===
    phase: WorkflowPhase
    current_agent: str
    account_id: str
    session_id: str
    error: str | None
    retry_count: int
    created_at: str
    updated_at: str

    # === Message history (LangGraph reducer) ===
    messages: Annotated[list, add_messages]

    # === Stage data (optional) ===
    trend_data: NotRequired[TrendData]
    content_plan: NotRequired[ContentPlan]
    copy_content: NotRequired[CopyContent]
    visual_plan: NotRequired[VisualPlan]
    publish_result: NotRequired[PublishResult]
    analytics: NotRequired[AnalyticsSnapshot]

    # === Human review ===
    human_feedback: NotRequired[HumanFeedback]

    # === Ripple CAS (optional external service) ===
    ripple_prediction: NotRequired[RipplePrediction]
    ripple_pmf: NotRequired[RipplePMFResult]
    ripple_job_ids: Annotated[list[str], append_list]

    # === History (with reducers) ===
    engagement_actions: Annotated[list[EngagementAction], append_list]
    content_history: Annotated[list[dict], append_list]
    performance_log: Annotated[list[dict], append_list]


__all__ = ["XHSGrowthState"]
```

- [ ] **Step 3: 提交子状态模块**

```bash
git add xhs_growth/state/substates.py xhs_growth/state/schema.py
git commit -m "refactor: modularize state schema with substates"
```

---

## Phase 3: 类型生成与同步

### Task 6: 设置类型生成工具

**Files:**
- Modify: `pyproject.toml`
- Create: `scripts/generate_types.sh`
- Create: `Makefile`

- [ ] **Step 1: 添加生成工具依赖**

```toml
# pyproject.toml - 添加到 [project.optional-dependencies]

[project.optional-dependencies]
dev = [
    "pytest>=7.0",
    "pytest-asyncio>=0.21",
    "ruff>=0.1.0",
    "mypy>=1.0",
    "datamodel-code-generator>=0.25.0",  # 新增
]
```

- [ ] **Step 2: 创建类型生成脚本**

```bash
# scripts/generate_types.sh

#!/bin/bash
set -e

echo "=== Generating types from OpenAPI spec ==="

# Backend: Pydantic models
echo "Generating Python Pydantic models..."
mkdir -p xhs_growth/api/generated

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

# Add __init__.py for generated module
cat > xhs_growth/api/generated/__init__.py << 'EOF'
"""Auto-generated Pydantic models from OpenAPI spec."""

from xhs_growth.api.generated.models import *

__all__ = [
    "ApiResponse",
    "ErrorDetail",
    "WorkflowPhase",
    "ContentStatus",
    "WorkflowStartRequest",
    "WorkflowResponse",
    "WorkflowState",
    "PendingReview",
    "ReviewDecisionRequest",
    "ReviewSubmitResponse",
]
EOF

echo "=== Generation complete ==="
```

- [ ] **Step 3: 创建 Makefile**

```makefile
# Makefile

.PHONY: gen-types gen-python lint test test-unit test-integration install-dev

# Type generation
gen-types: gen-python
	@echo "Types generated successfully"

gen-python:
	datamodel-codegen \
		--input api/spec/openapi.yaml \
		--output xhs_growth/api/generated/models.py \
		--output-model-type pydantic-v2.BaseModel \
		--strict-types \
		--capitalize-enum-members

# Lint
lint:
	ruff check xhs_growth
	ruff format xhs_growth --check

# Tests
test:
	pytest tests/ -v

test-unit:
	pytest tests/unit/ -v

test-integration:
	pytest tests/integration/ -v

test-contract:
	pytest tests/contract/ -v

# Install dev dependencies
install-dev:
	pip install -e ".[dev]"
```

- [ ] **Step 4: 安装生成工具并运行**

```bash
pip install datamodel-code-generator
chmod +x scripts/generate_types.sh
make gen-types
```

- [ ] **Step 5: 验证生成的模型**

```bash
python -c "from xhs_growth.api.generated.models import WorkflowPhase, ContentStatus; print(WorkflowPhase.SCOUTING)"
```

Expected: `scouting`

- [ ] **Step 6: 提交类型生成配置**

```bash
git add pyproject.toml scripts/generate_types.sh Makefile xhs_growth/api/generated
git commit -m "feat: add type generation tools and generated Pydantic models"
```

---

### Task 7: 创建契约测试

**Files:**
- Create: `tests/contract/__init__.py`
- Create: `tests/contract/test_openapi_spec.py`
- Create: `tests/contract/test_type_sync.py`

- [ ] **Step 1: 创建契约测试目录**

```bash
mkdir -p tests/contract
```

- [ ] **Step 2: 编写 OpenAPI 规范验证测试**

```python
# tests/contract/test_openapi_spec.py

"""Contract tests for OpenAPI specification."""

import pytest
import yaml
from pathlib import Path


def test_openapi_spec_exists():
    """Test OpenAPI spec file exists."""
    spec_path = Path("api/spec/openapi.yaml")
    assert spec_path.exists()


def test_openapi_spec_valid():
    """Test OpenAPI spec is valid YAML."""
    spec_path = Path("api/spec/openapi.yaml")

    with open(spec_path) as f:
        spec = yaml.safe_load(f)

    assert spec["openapi"] == "3.1.0"
    assert "info" in spec
    assert "paths" in spec
    assert "components" in spec


def test_openapi_has_required_endpoints():
    """Test OpenAPI has required endpoints."""
    spec_path = Path("api/spec/openapi.yaml")

    with open(spec_path) as f:
        spec = yaml.safe_load(f)

    paths = spec["paths"]

    # Workflow endpoints
    assert "/workflow/start" in paths
    assert "/workflow/status/{thread_id}" in paths
    assert "/workflow/pause/{thread_id}" in paths
    assert "/workflow/resume/{thread_id}" in paths

    # Review endpoints
    assert "/review/pending/{thread_id}" in paths
    assert "/review/submit/{thread_id}" in paths

    # Analytics endpoints
    assert "/analytics/report/{account_id}" in paths
    assert "/analytics/performance/{account_id}" in paths
    assert "/analytics/costs" in paths


def test_openapi_has_unified_response():
    """Test OpenAPI has unified ApiResponse schema."""
    spec_path = Path("api/spec/openapi.yaml")

    with open(spec_path) as f:
        spec = yaml.safe_load(f)

    schemas = spec["components"]["schemas"]

    assert "ApiResponse" in schemas
    assert "ErrorDetail" in schemas

    # ApiResponse required fields
    api_response = schemas["ApiResponse"]
    assert "success" in api_response["required"]
    assert "timestamp" in api_response["required"]
```

- [ ] **Step 3: 编写类型同步测试**

```python
# tests/contract/test_type_sync.py

"""Contract tests for type synchronization."""

import pytest
import yaml
from pathlib import Path

from xhs_growth.state.enums import WorkflowPhase, ContentStatus


def test_workflow_phase_sync():
    """Test WorkflowPhase enum sync with OpenAPI."""
    spec_path = Path("api/spec/openapi.yaml")

    with open(spec_path) as f:
        spec = yaml.safe_load(f)

    openapi_phases = spec["components"]["schemas"]["WorkflowPhase"]["enum"]
    backend_phases = [e.value for e in WorkflowPhase]

    assert set(openapi_phases) == set(backend_phases)


def test_content_status_sync():
    """Test ContentStatus enum sync with OpenAPI."""
    spec_path = Path("api/spec/openapi.yaml")

    with open(spec_path) as f:
        spec = yaml.safe_load(f)

    openapi_statuses = spec["components"]["schemas"]["ContentStatus"]["enum"]
    backend_statuses = [e.value for e in ContentStatus]

    assert set(openapi_statuses) == set(backend_statuses)


def test_generated_models_exist():
    """Test generated Pydantic models exist."""
    models_path = Path("xhs_growth/api/generated/models.py")
    assert models_path.exists()

    content = models_path.read_text()

    # Key models should exist
    assert "WorkflowPhase" in content
    assert "ContentStatus" in content
    assert "ApiResponse" in content
    assert "WorkflowResponse" in content


def test_generated_enums_match_backend():
    """Test generated enums match backend enums."""
    from xhs_growth.api.generated.models import (
        WorkflowPhase as GeneratedWorkflowPhase,
        ContentStatus as GeneratedContentStatus,
    )

    # Values should match
    backend_phases = {e.value for e in WorkflowPhase}
    generated_phases = {e.value for e in GeneratedWorkflowPhase}

    assert backend_phases == generated_phases

    backend_statuses = {e.value for e in ContentStatus}
    generated_statuses = {e.value for e in GeneratedContentStatus}

    assert backend_statuses == generated_statuses
```

- [ ] **Step 4: 创建导出**

```python
# tests/contract/__init__.py
```

- [ ] **Step 5: 运行契约测试**

```bash
pytest tests/contract/ -v
```

Expected: PASS

- [ ] **Step 6: 提交契约测试**

```bash
git add tests/contract
git commit -m "test: add contract tests for OpenAPI spec and type sync"
```

---

## Phase 4: API 路由改造

### Task 8: 更新 FastAPI 应用配置

**Files:**
- Modify: `xhs_growth/api/app.py`

- [ ] **Step 1: 更新应用入口添加中间件**

```python
# xhs_growth/api/app.py

"""FastAPI application - XHS Growth Engine API."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from xhs_growth.graph.builder import compile_graph_dev
from xhs_growth.api.middleware import error_handler_middleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - compile graph on startup."""
    app.state.graph = compile_graph_dev()
    yield


app = FastAPI(
    title="小红书增长引擎",
    description="XHS Growth Engine Agent API",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Error handling middleware
app.middleware("http")(error_handler_middleware)

# Import routes after app is created
from xhs_growth.api.routes import workflow, review, analytics  # noqa: E402, F401

app.include_router(workflow.router, prefix="/api/workflow", tags=["workflow"])
app.include_router(review.router, prefix="/api/review", tags=["review"])
app.include_router(analytics.router, prefix="/api/analytics", tags=["analytics"])


@app.get("/health")
async def health():
    """Health check endpoint."""
    from xhs_growth.api.responses import success
    return success(data={"status": "ok", "version": "1.0.0"})


# Static frontend hosting (production)
import os
from pathlib import Path

frontend_dist = Path(__file__).parent.parent.parent / "frontend" / "dist"
if frontend_dist.exists():
    from fastapi.staticfiles import StaticFiles
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")
```

- [ ] **Step 2: 提交应用配置**

```bash
git add xhs_growth/api/app.py
git commit -m "refactor: add error handler middleware to FastAPI app"
```

---

### Task 9: 改造 Workflow 路由

**Files:**
- Modify: `xhs_growth/api/routes/workflow.py`

- [ ] **Step 1: 改造 workflow 路由使用统一响应**

```python
# xhs_growth/api/routes/workflow.py

"""Workflow API routes - start/pause/resume/list workflows."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Request

from xhs_growth.api.responses import success
from xhs_growth.api.errors import WorkflowNotFoundError, ValidationError
from xhs_growth.state.enums import WorkflowPhase

router = APIRouter()


@router.post("/start")
async def start_workflow(req: dict, request: Request):
    """Start a new workflow."""
    account_id = req.get("account_id")
    if not account_id:
        raise ValidationError("account_id", "account_id is required")

    graph = request.app.state.graph
    thread_id = f"xhs_{account_id}_{uuid.uuid4().hex[:8]}"

    phase_str = req.get("phase", "scouting")
    try:
        phase = WorkflowPhase(phase_str)
    except ValueError:
        phase = WorkflowPhase.SCOUTING

    initial_state = {
        "phase": phase,
        "current_agent": "orchestrator",
        "error": None,
        "retry_count": 0,
        "messages": [],
        "account_id": account_id,
        "session_id": thread_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    config = {"configurable": {"thread_id": thread_id}}

    result = await graph.ainvoke(initial_state, config)

    return success(
        data={
            "thread_id": thread_id,
            "status": "running",
            "phase": result.get("phase", "unknown"),
        }
    )


@router.get("/status/{thread_id}")
async def get_workflow_status(thread_id: str, request: Request):
    """Get workflow status."""
    graph = request.app.state.graph
    config = {"configurable": {"thread_id": thread_id}}

    state = await graph.aget_state(config)

    if not state.values:
        raise WorkflowNotFoundError(thread_id)

    values = state.values

    return success(
        data={
            "thread_id": thread_id,
            "phase": values.get("phase", "idle"),
            "current_agent": values.get("current_agent", ""),
            "trend_data": values.get("trend_data", {}),
            "content_plan": values.get("content_plan", {}),
            "copy_content": values.get("copy_content", {}),
            "visual_plan": values.get("visual_plan", {}),
            "error": values.get("error"),
            "created_at": values.get("created_at"),
            "updated_at": values.get("updated_at"),
        }
    )


@router.post("/pause/{thread_id}")
async def pause_workflow(thread_id: str, request: Request):
    """Pause workflow."""
    return success(data={"thread_id": thread_id, "status": "paused"})


@router.post("/resume/{thread_id}")
async def resume_workflow(thread_id: str, request: Request):
    """Resume workflow."""
    graph = request.app.state.graph
    config = {"configurable": {"thread_id": thread_id}}

    state = await graph.aget_state(config)
    if state.next:
        result = await graph.ainvoke(None, config)
        return success(
            data={
                "thread_id": thread_id,
                "status": "running",
                "phase": result.get("phase", "unknown"),
            }
        )
    return success(data={"thread_id": thread_id, "status": "completed"})
```

- [ ] **Step 2: 提交 workflow 路由**

```bash
git add xhs_growth/api/routes/workflow.py
git commit -m "refactor: update workflow routes to use unified response format"
```

---

### Task 10: 改造 Review 路由

**Files:**
- Modify: `xhs_growth/api/routes/review.py`

- [ ] **Step 1: 改造 review 路由使用统一响应**

```python
# xhs_growth/api/routes/review.py

"""Review API routes - human-in-the-loop content review."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel
from langgraph.types import Command

from xhs_growth.api.responses import success
from xhs_growth.api.errors import ReviewNotPendingError
from xhs_growth.state.enums import ContentStatus

router = APIRouter()


class ReviewDecision(BaseModel):
    """Review decision request."""
    decision: str  # approved, needs_revision, rejected
    comments: str = ""
    revisions: list[str] = []


@router.get("/pending/{thread_id}")
async def get_pending_review(thread_id: str, request: Request):
    """Get pending review content."""
    graph = request.app.state.graph
    config = {"configurable": {"thread_id": thread_id}}

    state = await graph.aget_state(config)

    # Check if waiting at review_gate
    if "review_gate" in state.next:
        values = state.values
        return success(
            data={
                "status": "awaiting_review",
                "content_plan": values.get("content_plan", {}),
                "copy_content": values.get("copy_content", {}),
                "visual_plan": values.get("visual_plan", {}),
            }
        )
    return success(data={"status": "no_pending_review"})


@router.post("/submit/{thread_id}")
async def submit_review(thread_id: str, decision: ReviewDecision, request: Request):
    """Submit review decision."""
    graph = request.app.state.graph
    config = {"configurable": {"thread_id": thread_id}}

    # Validate decision
    valid_decisions = ["approved", "needs_revision", "rejected"]
    if decision.decision not in valid_decisions:
        raise ReviewNotPendingError(thread_id, "invalid_decision")

    # Resume graph with decision
    decision_dict = {
        "decision": decision.decision,
        "comments": decision.comments,
        "revisions": decision.revisions,
    }

    result = await graph.ainvoke(Command(resume=decision_dict), config)

    return success(
        data={
            "thread_id": thread_id,
            "status": "resumed",
            "decision": decision.decision,
            "next_phase": result.get("phase", "unknown") if result else "unknown",
        }
    )
```

- [ ] **Step 2: 提交 review 路由**

```bash
git add xhs_growth/api/routes/review.py
git commit -m "refactor: update review routes to use unified response format"
```

---

### Task 11: 改造 Analytics 路由

**Files:**
- Modify: `xhs_growth/api/routes/analytics.py`

- [ ] **Step 1: 改造 analytics 路由使用统一响应**

```python
# xhs_growth/api/routes/analytics.py

"""Analytics API routes - growth reports and performance data."""

from __future__ import annotations

from fastapi import APIRouter

from xhs_growth.api.responses import success

router = APIRouter()


@router.get("/report/{account_id}")
async def get_growth_report(account_id: str, period: str = "weekly"):
    """Get growth report."""
    # TODO: Implement actual report generation
    return success(
        data={
            "account_id": account_id,
            "period": period,
            "metrics": {
                "total_views": 0,
                "total_likes": 0,
                "total_comments": 0,
                "engagement_rate": 0.0,
                "growth_rate": 0.0,
            },
            "insights": ["暂无数据"],
        }
    )


@router.get("/performance/{account_id}")
async def get_performance(account_id: str, limit: int = 20):
    """Get recent post performance."""
    # TODO: Implement actual performance query
    return success(
        data={
            "account_id": account_id,
            "posts": [],
        }
    )


@router.get("/costs")
async def get_costs():
    """Get LLM call costs."""
    # TODO: Integrate with CostTracker
    return success(
        data={
            "total_cost_usd": 0.0,
            "today_cost_usd": 0.0,
            "by_model": {},
            "circuit_open": False,
        }
    )
```

- [ ] **Step 2: 提交 analytics 路由**

```bash
git add xhs_growth/api/routes/analytics.py
git commit -m "refactor: update analytics routes to use unified response format"
```

---

## Phase 5: 前端类型同步

### Task 12: 更新前端 API 配置

**Files:**
- Create: `frontend/package.json` 更新（添加 openapi-ts）
- Modify: `frontend/src/api/client.ts`

- [ ] **Step 1: 添加前端类型生成配置**

检查前端 package.json 是否有 openapi-ts 或类似工具，如果没有需要添加。

```bash
cd frontend && npm list openapi-ts || npm install --save-dev openapi-ts
```

- [ ] **Step 2: 创建前端 API 客户端封装**

```typescript
// frontend/src/api/client.ts

import axios, { AxiosInstance, AxiosError } from 'axios'

// 创建 axios 实例
const client: AxiosInstance = axios.create({
  baseURL: '/api',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// 请求拦截器
client.interceptors.request.use(
  (config) => config,
  (error) => Promise.reject(error)
)

// 响应拦截器 - 处理统一响应格式
client.interceptors.response.use(
  (response) => {
    // ApiResponse 格式: { success, data, error, timestamp, request_id }
    const apiResponse = response.data
    if (apiResponse.success) {
      return apiResponse.data
    }
    // 业务错误
    const error = new Error(apiResponse.error?.message || 'Unknown error')
    ;(error as any).code = apiResponse.error?.code
    ;(error as any).details = apiResponse.error?.details
    return Promise.reject(error)
  },
  (error: AxiosError) => {
    console.error('API Error:', error.message)
    return Promise.reject(error)
  }
)

export default client
```

- [ ] **Step 3: 更新前端类型定义匹配后端**

```typescript
// frontend/src/types/workflow.ts

// Workflow phase enum - synced with backend
export type WorkflowPhase =
  | 'idle'
  | 'scouting'
  | 'planning'
  | 'creating'
  | 'reviewing'
  | 'publishing'
  | 'analyzing'
  | 'engaging'
  | 'completed'
  | 'error'

// Content status enum - synced with backend
export type ContentStatus =
  | 'approved'
  | 'needs_revision'
  | 'rejected'
  | 'draft'
  | 'pending_review'
  | 'published'
  | 'failed'

// Workflow status
export type WorkflowStatus = 'running' | 'paused' | 'completed' | 'error'

// Workflow start request
export interface WorkflowStartRequest {
  account_id: string
  phase?: WorkflowPhase
}

// Workflow response
export interface WorkflowResponse {
  thread_id: string
  status: WorkflowStatus
  phase: WorkflowPhase
}

// Workflow state
export interface WorkflowState {
  thread_id: string
  phase: WorkflowPhase
  current_agent: string
  trend_data?: Record<string, any>
  content_plan?: Record<string, any>
  copy_content?: Record<string, any>
  visual_plan?: Record<string, any>
  error?: string | null
  created_at?: string
  updated_at?: string
}
```

```typescript
// frontend/src/types/review.ts

// Pending review
export interface PendingReview {
  status: 'awaiting_review' | 'no_pending_review'
  content_plan?: Record<string, any>
  copy_content?: Record<string, any>
  visual_plan?: Record<string, any>
}

// Review decision
export interface ReviewDecision {
  decision: ContentStatus
  comments?: string
  revisions?: string[]
}

// Review submit response
export interface ReviewSubmitResponse {
  thread_id: string
  status: 'resumed'
  decision: ContentStatus
  next_phase: string
}

// Import ContentStatus from workflow
import type { ContentStatus } from './workflow'
```

- [ ] **Step 4: 更新前端 API 模块**

```typescript
// frontend/src/api/workflow.ts

import client from './client'
import type { WorkflowStartRequest, WorkflowResponse, WorkflowState } from '@/types/workflow'

// 启动工作流
export async function startWorkflow(req: WorkflowStartRequest): Promise<WorkflowResponse> {
  return client.post('/workflow/start', req)
}

// 获取工作流状态
export async function getWorkflowStatus(threadId: string): Promise<WorkflowState> {
  return client.get(`/workflow/status/${threadId}`)
}

// 暂停工作流
export async function pauseWorkflow(threadId: string): Promise<{ thread_id: string; status: string }> {
  return client.post(`/workflow/pause/${threadId}`)
}

// 恢复工作流
export async function resumeWorkflow(threadId: string): Promise<WorkflowResponse> {
  return client.post(`/workflow/resume/${threadId}`)
}
```

```typescript
// frontend/src/api/review.ts

import client from './client'
import type { PendingReview, ReviewDecision, ReviewSubmitResponse } from '@/types/review'

// 获取待审核内容
export async function getPendingReview(threadId: string): Promise<PendingReview> {
  return client.get(`/review/pending/${threadId}`)
}

// 提交审核决定
export async function submitReview(
  threadId: string,
  decision: ReviewDecision
): Promise<ReviewSubmitResponse> {
  return client.post(`/review/submit/${threadId}`, decision)
}
```

- [ ] **Step 5: 提交前端更新**

```bash
git add frontend/src/api frontend/src/types
git commit -m "feat: update frontend API client for unified response format"
```

---

## Phase 6: 验收测试

### Task 13: 创建集成测试

**Files:**
- Create: `tests/integration/__init__.py`
- Create: `tests/integration/test_api_routes.py`

- [ ] **Step 1: 创建集成测试目录**

```bash
mkdir -p tests/integration
```

- [ ] **Step 2: 编写 API 路由集成测试**

```python
# tests/integration/test_api_routes.py

"""Integration tests for API routes."""

import pytest
from fastapi.testclient import TestClient

from xhs_growth.api.app import app


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


class TestWorkflowRoutes:
    """Workflow API integration tests."""

    def test_start_workflow_success(self, client):
        """Test start workflow returns success response."""
        response = client.post("/api/workflow/start", json={
            "account_id": "test_account",
            "phase": "scouting"
        })

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "thread_id" in data["data"]
        assert data["data"]["status"] == "running"

    def test_start_workflow_missing_account(self, client):
        """Test start workflow with missing account_id."""
        response = client.post("/api/workflow/start", json={
            "phase": "scouting"
        })

        assert response.status_code == 400
        data = response.json()
        assert data["success"] is False
        assert data["error"]["code"] == "ERROR_VALIDATION"

    def test_get_workflow_status_not_found(self, client):
        """Test get status for nonexistent workflow."""
        response = client.get("/api/workflow/status/nonexistent_thread")

        assert response.status_code == 404
        data = response.json()
        assert data["success"] is False
        assert data["error"]["code"] == "ERROR_WORKFLOW_NOT_FOUND"

    def test_health_check(self, client):
        """Test health check endpoint."""
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["status"] == "ok"


class TestReviewRoutes:
    """Review API integration tests."""

    def test_get_pending_review(self, client):
        """Test get pending review."""
        response = client.get("/api/review/pending/nonexistent")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["data"]["status"] == "no_pending_review"


class TestAnalyticsRoutes:
    """Analytics API integration tests."""

    def test_get_costs(self, client):
        """Test get costs endpoint."""
        response = client.get("/api/analytics/costs")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "total_cost_usd" in data["data"]

    def test_get_performance(self, client):
        """Test get performance endpoint."""
        response = client.get("/api/analytics/performance/test_account?limit=10")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
```

- [ ] **Step 3: 创建导出**

```python
# tests/integration/__init__.py
```

- [ ] **Step 4: 运行集成测试**

```bash
pytest tests/integration/ -v
```

Expected: PASS

- [ ] **Step 5: 提交集成测试**

```bash
git add tests/integration
git commit -m "test: add integration tests for API routes"
```

---

### Task 14: 最终验收

- [ ] **Step 1: 运行所有测试**

```bash
pytest tests/ -v
```

Expected: All tests pass

- [ ] **Step 2: 验证类型同步**

```bash
# 验证后端枚举与 OpenAPI 一致
python -c "
from xhs_growth.state.enums import WorkflowPhase
from xhs_growth.api.generated.models import WorkflowPhase as GenPhase
backend = set(e.value for e in WorkflowPhase)
generated = set(e.value for e in GenPhase)
assert backend == generated, f'Mismatch: {backend} vs {generated}'
print('Enum sync verified')
"
```

- [ ] **Step 3: 验证 API 响应格式**

```bash
# 启动服务器并测试
python -c "
from fastapi.testclient import TestClient
from xhs_growth.api.app import app
client = TestClient(app)
response = client.get('/health')
assert response.json()['success'] is True
print('API response format verified')
"
```

- [ ] **Step 4: 创建最终提交**

```bash
git status
git add -A
git commit -m "feat: complete backend architecture optimization with OpenAPI-first design

- Add OpenAPI 3.1 specification as single type source
- Implement lightweight DI container for service management
- Add unified ApiResponse format and error handling
- Modularize state schema with substates
- Generate Pydantic models from OpenAPI
- Update API routes to use unified responses
- Add contract tests for type synchronization
- Update frontend API client for new response format"
```

- [ ] **Step 5: 推送到远程**

```bash
git push origin backend-optimization
```

---

## Acceptance Criteria

| Criterion | Verification |
|-----------|--------------|
| OpenAPI 规范有效 | `pytest tests/contract/test_openapi_spec.py` |
| 枚举三方同步 | `pytest tests/contract/test_type_sync.py` |
| API 响应统一格式 | `pytest tests/integration/test_api_routes.py` |
| DI 容器可测试 | `pytest tests/unit/core/test_di.py` |
| 所有测试通过 | `pytest tests/ -v` |

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| OpenAPI 规范变更导致类型不匹配 | CI 契约测试强制验证 |
| DI 容器影响现有 Agent | 保持 Agent execute 签名不变 |
| 前端改造范围大 | 逐步替换，保留兼容层 |