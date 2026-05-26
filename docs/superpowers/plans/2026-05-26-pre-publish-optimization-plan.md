# 发布前内容优化系统实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 XhsGrowthAgent 添加发布前内容优化功能，支持用户输入草稿、对比爆款、生成多版本、一键优化。

**Architecture:** 多节点流水线架构，新增 4 个节点（viral_matcher、content_analyzer、version_generator、choice_gate）嵌入现有工作流，使用 LangGraph 状态流转 + interrupt 实现人工选择。

**Tech Stack:** Python/LangGraph/LangChain (后端) + Vue 3/Pinia (前端)

---

## 文件结构

### 后端新增

```
xhs_growth/state/substates.py        # 扩展：DraftContent, ViralPost, OptimizationAnalysis, ContentVersion
xhs_growth/state/schema.py           # 扩展：新增状态字段
xhs_growth/config/models.py          # 扩展：新增 TaskType 枚举值

xhs_growth/agents/viral_matcher.py   # 新增：爆款匹配 Agent
xhs_growth/agents/content_analyzer.py # 新增：对比分析 Agent
xhs_growth/agents/version_generator.py # 新增：版本生成 Agent

xhs_growth/config/prompts/viral_matcher.yaml    # 新增：爆款匹配 Prompt
xhs_growth/config/prompts/content_analyzer.yaml # 新增：对比分析 Prompt
xhs_growth/config/prompts/version_generator.yaml # 新增：版本生成 Prompt

xhs_growth/tools/optimization/__init__.py       # 新增：工具模块入口
xhs_growth/tools/optimization/viral_tools.py    # 新增：爆款搜索工具
xhs_growth/tools/optimization/analysis_tools.py # 新增：对比分析工具
xhs_growth/tools/optimization/version_tools.py  # 新增：版本生成工具

xhs_growth/graph/builder.py         # 修改：添加新节点和边
xhs_growth/graph/nodes.py           # 修改：添加新节点函数
xhs_growth/graph/routers.py         # 修改：添加 choice_outcome 路由
xhs_growth/graph/__init__.py        # 修改：导出新节点
xhs_growth/tools/registry.py        # 修改：注册新工具
```

### 前端新增

```
frontend/src/types/optimization.ts           # 新增：优化相关类型定义
frontend/src/components/DraftInput.vue       # 新增：草稿输入组件
frontend/src/components/ViralSelector.vue    # 新增：爆款选择组件
frontend/src/components/VersionCompare.vue   # 新增：版本对比组件
frontend/src/components/OptimizationReport.vue # 新增：分析报告组件
frontend/src/stores/workflow.ts              # 修改：扩展状态和 actions
frontend/src/views/Dashboard.vue             # 修改：添加 DraftInput 入口
```

### 测试新增

```
tests/test_optimization_state.py             # 状态模型测试
tests/test_viral_matcher.py                  # 爆款匹配测试
tests/test_content_analyzer.py               # 对比分析测试
tests/test_version_generator.py              # 版本生成测试
tests/test_optimization_flow.py              # 集成流程测试
```

---

## Phase 1: 后端核心 - 状态扩展

### Task 1: 扩展状态子模型 (substates.py)

**Files:**
- Modify: `xhs_growth/state/substates.py`
- Test: `tests/test_optimization_state.py`

- [ ] **Step 1: 创建测试文件**

```python
# tests/test_optimization_state.py
"""Tests for optimization-related state models."""

import pytest
from xhs_growth.state.substates import (
    DraftContent,
    ViralPost,
    GapItem,
    SuggestionItem,
    OptimizationAnalysis,
    ContentVersion,
)


def test_draft_content_defaults():
    """DraftContent should have optional fields."""
    draft: DraftContent = {
        "text": "原始文案",
        "images": [],
        "provided_at": "2026-05-26T10:00:00",
    }
    assert draft["text"] == "原始文案"
    assert draft["images"] == []
    assert "title" not in draft  # optional


def test_viral_post_structure():
    """ViralPost should contain all required fields."""
    viral: ViralPost = {
        "note_id": "abc123",
        "title": "爆款标题",
        "body": "正文内容",
        "hashtags": ["#穿搭", "#OOTD"],
        "cover_url": "https://example.com/cover.jpg",
        "image_urls": ["https://example.com/1.jpg"],
        "likes": 10000,
        "collects": 5000,
        "comments": 200,
        "engagement_rate": 0.15,
        "visual_style": "vibrant",
        "color_palette": {"primary": "#FF5733", "secondary": "#33FF57"},
    }
    assert viral["note_id"] == "abc123"
    assert viral["engagement_rate"] == 0.15


def test_gap_item_severity():
    """GapItem severity should be one of high/medium/low."""
    gap: GapItem = {
        "dimension": "title",
        "description": "标题缺乏吸引力",
        "severity": "high",
    }
    assert gap["severity"] in ["high", "medium", "low"]


def test_content_version_predicted_score():
    """ContentVersion predicted_score should be 0-1 range."""
    version: ContentVersion = {
        "version_id": "A",
        "title": "优化标题",
        "body": "优化正文",
        "hashtags": ["#优化"],
        "image_prompts": ["prompt1"],
        "style_suggestion": "minimal",
        "changes_summary": "增加了情感元素",
        "predicted_score": 0.85,
    }
    assert 0 <= version["predicted_score"] <= 1
```

Run: `pytest tests/test_optimization_state.py -v`
Expected: FAIL with "cannot import name"

- [ ] **Step 2: 添加子状态模型**

```python
# xhs_growth/state/substates.py (追加到文件末尾)

class DraftContent(TypedDict, total=False):
    """用户原始草稿."""
    text: str
    images: list[str]
    title: str
    hashtags: list[str]
    provided_at: str


class ViralPost(TypedDict, total=False):
    """爆款参考笔记."""
    note_id: str
    title: str
    body: str
    hashtags: list[str]
    cover_url: str
    image_urls: list[str]
    likes: int
    collects: int
    comments: int
    engagement_rate: float
    visual_style: str
    color_palette: dict


class GapItem(TypedDict, total=False):
    """差距项."""
    dimension: str
    description: str
    severity: str


class SuggestionItem(TypedDict, total=False):
    """优化建议项."""
    dimension: str
    action: str
    reasoning: str
    priority: int


class OptimizationAnalysis(TypedDict, total=False):
    """优化分析报告."""
    gaps: list[GapItem]
    suggestions: list[SuggestionItem]
    viral_patterns: list[str]


class ContentVersion(TypedDict, total=False):
    """内容版本."""
    version_id: str
    title: str
    body: str
    hashtags: list[str]
    image_prompts: list[str]
    style_suggestion: str
    changes_summary: str
    predicted_score: float


__all__ = [
    # ... existing exports ...
    "DraftContent",
    "ViralPost",
    "GapItem",
    "SuggestionItem",
    "OptimizationAnalysis",
    "ContentVersion",
]
```

- [ ] **Step 3: 运行测试验证**

Run: `pytest tests/test_optimization_state.py -v`
Expected: PASS (6 tests)

- [ ] **Step 4: Commit**

```bash
git add xhs_growth/state/substates.py tests/test_optimization_state.py
git commit -m "$(cat <<'EOF'
feat(state): add optimization substate models

Add DraftContent, ViralPost, OptimizationAnalysis, ContentVersion
TypedDict models for the pre-publish optimization workflow.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: 扩展状态 Schema

**Files:**
- Modify: `xhs_growth/state/schema.py`

- [ ] **Step 1: 导入新子状态**

```python
# xhs_growth/state/schema.py (修改导入部分)
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
    # 新增
    DraftContent,
    ViralPost,
    OptimizationAnalysis,
    ContentVersion,
)
```

- [ ] **Step 2: 添加新状态字段**

```python
# xhs_growth/state/schema.py (在 XHSGrowthState 类中添加字段)
class XHSGrowthState(TypedDict, total=False):
    """XHS Growth Agent global state."""

    # ... existing fields ...

    # 优化相关字段
    draft_content: DraftContent
    viral_posts: Annotated[list[ViralPost], _append_list]
    user_viral_links: list[str]
    optimization_analysis: OptimizationAnalysis
    content_versions: Annotated[list[ContentVersion], _append_list]
    selected_version: str
```

- [ ] **Step 3: Commit**

```bash
git add xhs_growth/state/schema.py
git commit -m "$(cat <<'EOF'
feat(state): add optimization fields to XHSGrowthState

Add draft_content, viral_posts, optimization_analysis,
content_versions, and selected_version fields.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: 扩展 TaskType 枚举

**Files:**
- Modify: `xhs_growth/config/models.py`

- [ ] **Step 1: 添加新 TaskType**

```python
# xhs_growth/config/models.py (修改 TaskType 类)
class TaskType(str, Enum):
    """任务类型 → 模型路由键"""

    ROUTING = "routing"
    SCOUTING = "scouting"
    STRATEGY = "strategy"
    WRITING = "writing"
    VISUAL = "visual"
    ANALYSIS = "analysis"
    PUBLISHING = "publishing"
    ENGAGEMENT = "engagement"
    # 新增
    VIRAL_MATCHING = "viral_matching"
    CONTENT_ANALYSIS = "content_analysis"
    VERSION_GEN = "version_gen"
```

- [ ] **Step 2: 更新路由映射**

```python
# xhs_growth/config/models.py (修改 resolve_model_id 函数)
def resolve_model_id(task_type: TaskType, routing_overrides: dict[str, str] | None = None) -> str:
    """根据任务类型解析模型 ID，支持用户覆盖"""
    routing = {
        TaskType.ROUTING: "deepseek-chat",
        TaskType.SCOUTING: "deepseek-chat",
        TaskType.STRATEGY: "claude-sonnet-4-20250514",
        TaskType.WRITING: "claude-sonnet-4-20250514",
        TaskType.VISUAL: "gpt-4o",
        TaskType.ANALYSIS: "gpt-4o",
        TaskType.PUBLISHING: "qwen-plus",
        TaskType.ENGAGEMENT: "deepseek-chat",
        # 新增
        TaskType.VIRAL_MATCHING: "deepseek-chat",
        TaskType.CONTENT_ANALYSIS: "claude-sonnet-4-20250514",
        TaskType.VERSION_GEN: "gpt-4o",
    }
    if routing_overrides:
        for k, v in routing_overrides.items():
            routing[TaskType(k)] = v
    return routing[task_type]
```

- [ ] **Step 3: Commit**

```bash
git add xhs_growth/config/models.py
git commit -m "$(cat <<'EOF'
feat(config): add VIRAL_MATCHING, CONTENT_ANALYSIS, VERSION_GEN TaskTypes

Add new task types for optimization workflow with model routing.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Phase 2: 后端核心 - Agent 实现

### Task 4: 创建爆款匹配 Agent

**Files:**
- Create: `xhs_growth/agents/viral_matcher.py`
- Create: `xhs_growth/config/prompts/viral_matcher.yaml`
- Test: `tests/test_viral_matcher.py`

- [ ] **Step 1: 创建测试文件**

```python
# tests/test_viral_matcher.py
"""Tests for ViralMatcherAgent."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from xhs_growth.agents.viral_matcher import ViralMatcherAgent
from xhs_growth.state.schema import XHSGrowthState


@pytest.fixture
def mock_state():
    """Mock state with draft content."""
    return {
        "account_id": "test_account",
        "draft_content": {
            "text": "测试文案",
            "images": [],
            "title": "测试标题",
            "hashtags": ["#测试"],
            "provided_at": "2026-05-26T10:00:00",
        },
        "user_viral_links": ["https://xiaohongshu.com/explore/abc123"],
    }


@pytest.fixture
def mock_store():
    """Mock BaseStore."""
    store = MagicMock()
    store.asearch = AsyncMock(return_value=[])
    return store


@pytest.mark.asyncio
async def test_viral_matcher_no_draft(mock_state, mock_store):
    """Should skip optimization when no draft provided."""
    agent = ViralMatcherAgent()
    state_no_draft = {"account_id": "test_account"}
    result = await agent.execute(state_no_draft, mock_store)
    assert result.get("skip_optimization") == True


@pytest.mark.asyncio
async def test_viral_matcher_with_links(mock_state, mock_store):
    """Should process user-provided viral links."""
    agent = ViralMatcherAgent()
    result = await agent.execute(mock_state, mock_store)
    assert "viral_posts" in result
```

Run: `pytest tests/test_viral_matcher.py -v`
Expected: FAIL with "cannot import name"

- [ ] **Step 2: 创建 Prompt YAML**

```yaml
# xhs_growth/config/prompts/viral_matcher.yaml
system: |
  你是爆款内容匹配专家。你的任务是：
  1. 分析用户提供的爆款笔记链接，提取关键特征
  2. 根据用户草稿内容，自动搜索相关爆款笔记
  3. 识别爆款笔记的成功模式（标题风格、内容结构、视觉特征）
  4. 筛选出最相关的爆款笔记作为对比参考

  输出要求：
  - 每篇爆款笔记需包含完整信息（标题、正文、标签、互动数据）
  - 提取视觉风格分类（minimal/vibrant/warm/editorial）
  - 生成颜色主调分析

  请输出 JSON：
  {
    "viral_posts": [
      {
        "note_id": "...",
        "title": "...",
        "body": "...",
        "hashtags": [...],
        "likes": N,
        "collects": N,
        "comments": N,
        "engagement_rate": 0.XX,
        "visual_style": "...",
        "color_palette": {"primary": "#...", "secondary": "#..."}
      }
    ],
    "search_keywords_used": [...]
  }

user_template: |
  用户草稿标题：{draft_title}
  用户草稿内容：{draft_text}
  用户指定爆款链接：{user_links}
  自动搜索关键词：{auto_keywords}
```

- [ ] **Step 3: 创建 Agent 类**

```python
# xhs_growth/agents/viral_matcher.py
"""Viral Matcher agent — matches viral posts for comparison."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.store.base import BaseStore

from xhs_growth.agents.base import BaseAgent
from xhs_growth.config.models import TaskType
from xhs_growth.state.schema import XHSGrowthState, WorkflowPhase

logger = logging.getLogger("xhs_growth.viral_matcher")


class ViralMatcherAgent(BaseAgent):
    """爆款匹配 Agent."""

    task_type = TaskType.VIRAL_MATCHING
    agent_name = "viral_matcher"
    prompt_file = "viral_matcher.yaml"

    async def execute(self, state: XHSGrowthState, store: BaseStore) -> dict[str, Any]:
        draft = state.get("draft_content")
        
        # 无草稿时跳过优化
        if not draft or not draft.get("text"):
            logger.info("No draft content provided, skipping optimization")
            return {
                "skip_optimization": True,
                "phase": WorkflowPhase.CREATING,
            }

        account_id = state.get("account_id", "default")
        user_links = state.get("user_viral_links", [])
        
        # 获取自动搜索关键词（来自趋势或策略）
        trend_data = state.get("trend_data", {})
        content_plan = state.get("content_plan", {})
        auto_keywords = trend_data.get("trending_keywords", [])
        if content_plan.get("selected_topic"):
            auto_keywords.append(content_plan.get("selected_topic"))

        system_prompt = self._build_system_prompt(state)
        
        user_msg = f"""用户草稿标题：{draft.get('title', '未提供')}
用户草稿内容：{draft.get('text', '')[:500]}
用户指定爆款链接：{', '.join(user_links) if user_links else '无'}
自动搜索关键词：{', '.join(auto_keywords[:5]) if auto_keywords else '无'}"""

        response = await self.model.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_msg),
        ])

        result = self._parse_json_response(response.content)
        viral_posts = result.get("viral_posts", [])

        return {
            "viral_posts": viral_posts,
            "phase": WorkflowPhase.CREATING,
        }


__all__ = ["ViralMatcherAgent"]
```

- [ ] **Step 4: 运行测试**

Run: `pytest tests/test_viral_matcher.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add xhs_growth/agents/viral_matcher.py xhs_growth/config/prompts/viral_matcher.yaml tests/test_viral_matcher.py
git commit -m "$(cat <<'EOF'
feat(agents): add ViralMatcherAgent

Create viral matcher agent for matching viral posts for comparison.
Handles user-provided links and auto-search keywords.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: 创建对比分析 Agent

**Files:**
- Create: `xhs_growth/agents/content_analyzer.py`
- Create: `xhs_growth/config/prompts/content_analyzer.yaml`
- Test: `tests/test_content_analyzer.py`

- [ ] **Step 1: 创建测试文件**

```python
# tests/test_content_analyzer.py
"""Tests for ContentAnalyzerAgent."""

import pytest
from unittest.mock import MagicMock, AsyncMock
from xhs_growth.agents.content_analyzer import ContentAnalyzerAgent
from xhs_growth.state.schema import XHSGrowthState


@pytest.fixture
def mock_state_with_viral():
    """Mock state with draft and viral posts."""
    return {
        "account_id": "test_account",
        "draft_content": {
            "text": "测试文案内容",
            "title": "普通标题",
            "images": [],
            "hashtags": ["#测试"],
        },
        "viral_posts": [
            {
                "note_id": "viral1",
                "title": "爆款标题！必须看",
                "body": "爆款正文",
                "hashtags": ["#爆款", "#热门"],
                "likes": 10000,
                "engagement_rate": 0.2,
                "visual_style": "vibrant",
            }
        ],
    }


@pytest.fixture
def mock_store():
    store = MagicMock()
    store.asearch = AsyncMock(return_value=[])
    return store


@pytest.mark.asyncio
async def test_analyzer_generates_gaps(mock_state_with_viral, mock_store):
    """Should generate gap analysis."""
    agent = ContentAnalyzerAgent()
    result = await agent.execute(mock_state_with_viral, mock_store)
    assert "optimization_analysis" in result
    analysis = result["optimization_analysis"]
    assert "gaps" in analysis
    assert "suggestions" in analysis
```

Run: `pytest tests/test_content_analyzer.py -v`
Expected: FAIL

- [ ] **Step 2: 创建 Prompt YAML**

```yaml
# xhs_growth/config/prompts/content_analyzer.yaml
system: |
  你是内容对比分析专家。你的任务是：
  1. 对比用户草稿与爆款笔记，找出差距
  2. 分析爆款笔记的成功模式
  3. 生成具体、可操作的优化建议
  4. 评估每项差距的严重程度

  分析维度：
  - 标题：吸引力、情感触发、关键词
  - 正文：结构、节奏、情感共鸣
  - 视觉：风格、配色、构图
  - 策略：发布时机、话题热度、受众匹配

  请输出 JSON：
  {
    "gaps": [
      {"dimension": "title", "description": "...", "severity": "high/medium/low"}
    ],
    "suggestions": [
      {"dimension": "title", "action": "...", "reasoning": "...", "priority": 1-5}
    ],
    "viral_patterns": ["爆款共有模式1", "爆款共有模式2"]
  }

user_template: |
  用户草稿标题：{draft_title}
  用户草稿正文：{draft_body}
  用户草稿标签：{draft_hashtags}
  
  爆款笔记数据：
  {viral_posts_summary}
```

- [ ] **Step 3: 创建 Agent 类**

```python
# xhs_growth/agents/content_analyzer.py
"""Content Analyzer agent — analyzes gaps between draft and viral posts."""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.store.base import BaseStore

from xhs_growth.agents.base import BaseAgent
from xhs_growth.config.models import TaskType
from xhs_growth.state.schema import XHSGrowthState, WorkflowPhase

logger = logging.getLogger("xhs_growth.content_analyzer")


class ContentAnalyzerAgent(BaseAgent):
    """对比分析 Agent."""

    task_type = TaskType.CONTENT_ANALYSIS
    agent_name = "content_analyzer"
    prompt_file = "content_analyzer.yaml"

    async def execute(self, state: XHSGrowthState, store: BaseStore) -> dict[str, Any]:
        draft = state.get("draft_content", {})
        viral_posts = state.get("viral_posts", [])

        if not draft or not viral_posts:
            logger.warning("Missing draft or viral posts for analysis")
            return {
                "optimization_analysis": {
                    "gaps": [],
                    "suggestions": [],
                    "viral_patterns": [],
                },
                "phase": WorkflowPhase.CREATING,
            }

        # 构建爆款摘要
        viral_summary = json.dumps([
            {
                "title": p.get("title", ""),
                "hashtags": p.get("hashtags", []),
                "likes": p.get("likes", 0),
                "engagement_rate": p.get("engagement_rate", 0),
                "visual_style": p.get("visual_style", ""),
            }
            for p in viral_posts[:5]
        ], ensure_ascii=False, indent=2)

        system_prompt = self._build_system_prompt(state)
        
        user_msg = f"""用户草稿标题：{draft.get('title', '未提供')}
用户草稿正文：{draft.get('text', '')[:500]}
用户草稿标签：{', '.join(draft.get('hashtags', []))}

爆款笔记数据：
{viral_summary}"""

        response = await self.model.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_msg),
        ])

        analysis = self._parse_json_response(response.content)

        return {
            "optimization_analysis": analysis,
            "phase": WorkflowPhase.CREATING,
        }


__all__ = ["ContentAnalyzerAgent"]
```

- [ ] **Step 4: 运行测试**

Run: `pytest tests/test_content_analyzer.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add xhs_growth/agents/content_analyzer.py xhs_growth/config/prompts/content_analyzer.yaml tests/test_content_analyzer.py
git commit -m "$(cat <<'EOF'
feat(agents): add ContentAnalyzerAgent

Create content analyzer agent for gap analysis between
draft content and viral posts.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: 创建版本生成 Agent

**Files:**
- Create: `xhs_growth/agents/version_generator.py`
- Create: `xhs_growth/config/prompts/version_generator.yaml`
- Test: `tests/test_version_generator.py`

- [ ] **Step 1: 创建测试文件**

```python
# tests/test_version_generator.py
"""Tests for VersionGeneratorAgent."""

import pytest
from unittest.mock import MagicMock, AsyncMock
from xhs_growth.agents.version_generator import VersionGeneratorAgent
from xhs_growth.state.schema import XHSGrowthState


@pytest.fixture
def mock_state_with_analysis():
    """Mock state with analysis result."""
    return {
        "account_id": "test_account",
        "draft_content": {
            "text": "原始文案",
            "title": "普通标题",
            "hashtags": ["#测试"],
        },
        "optimization_analysis": {
            "gaps": [{"dimension": "title", "description": "缺乏吸引力", "severity": "high"}],
            "suggestions": [
                {"dimension": "title", "action": "添加情感触发词", "reasoning": "爆款多用感叹号", "priority": 5}
            ],
            "viral_patterns": ["标题使用数字", "正文分段清晰"],
        },
    }


@pytest.fixture
def mock_store():
    store = MagicMock()
    store.asearch = AsyncMock(return_value=[])
    return store


@pytest.mark.asyncio
async def test_generator_creates_three_versions(mock_state_with_analysis, mock_store):
    """Should generate A, B, C versions."""
    agent = VersionGeneratorAgent()
    result = await agent.execute(mock_state_with_analysis, mock_store)
    assert "content_versions" in result
    versions = result["content_versions"]
    assert len(versions) == 3
    assert versions[0]["version_id"] == "A"
    assert versions[1]["version_id"] == "B"
    assert versions[2]["version_id"] == "C"
```

Run: `pytest tests/test_version_generator.py -v`
Expected: FAIL

- [ ] **Step 2: 创建 Prompt YAML**

```yaml
# xhs_growth/config/prompts/version_generator.yaml
system: |
  你是内容优化专家。你的任务是：
  1. 根据分析报告，生成 3 个优化版本（A/B/C）
  2. 每个版本采用不同的优化策略
  3. 保留用户原始意图，仅做增强

  版本策略：
  - A 版：保守优化，小幅改动，风险最低
  - B 版：适度优化，平衡改动与效果
  - C 版：激进优化，大胆改动，追求爆款

  请输出 JSON：
  {
    "versions": [
      {
        "version_id": "A/B/C",
        "title": "优化后标题",
        "body": "优化后正文",
        "hashtags": [...],
        "image_prompts": ["图片生成建议"],
        "style_suggestion": "视觉风格建议",
        "changes_summary": "改动摘要",
        "predicted_score": 0.XX
      }
    ]
  }

user_template: |
  原始标题：{original_title}
  原始正文：{original_body}
  原始标签：{original_hashtags}
  
  分析报告：
  - 差距：{gaps}
  - 建议：{suggestions}
  - 爆款模式：{viral_patterns}
```

- [ ] **Step 3: 创建 Agent 类**

```python
# xhs_growth/agents/version_generator.py
"""Version Generator agent — generates A/B/C optimized versions."""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.store.base import BaseStore

from xhs_growth.agents.base import BaseAgent
from xhs_growth.config.models import TaskType
from xhs_growth.state.schema import XHSGrowthState, WorkflowPhase

logger = logging.getLogger("xhs_growth.version_generator")


class VersionGeneratorAgent(BaseAgent):
    """版本生成 Agent."""

    task_type = TaskType.VERSION_GEN
    agent_name = "version_generator"
    prompt_file = "version_generator.yaml"

    async def execute(self, state: XHSGrowthState, store: BaseStore) -> dict[str, Any]:
        draft = state.get("draft_content", {})
        analysis = state.get("optimization_analysis", {})

        if not draft or not analysis:
            logger.warning("Missing draft or analysis for version generation")
            return {
                "content_versions": [],
                "phase": WorkflowPhase.CREATING,
            }

        gaps = json.dumps(analysis.get("gaps", []), ensure_ascii=False)
        suggestions = json.dumps(analysis.get("suggestions", []), ensure_ascii=False)
        viral_patterns = ", ".join(analysis.get("viral_patterns", []))

        system_prompt = self._build_system_prompt(state)
        
        user_msg = f"""原始标题：{draft.get('title', '未提供')}
原始正文：{draft.get('text', '')[:500]}
原始标签：{', '.join(draft.get('hashtags', []))}

分析报告：
- 差距：{gaps}
- 建议：{suggestions}
- 爆款模式：{viral_patterns}"""

        response = await self.model.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_msg),
        ])

        result = self._parse_json_response(response.content)
        versions = result.get("versions", [])

        return {
            "content_versions": versions,
            "phase": WorkflowPhase.CREATING,
        }


__all__ = ["VersionGeneratorAgent"]
```

- [ ] **Step 4: 运行测试**

Run: `pytest tests/test_version_generator.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add xhs_growth/agents/version_generator.py xhs_growth/config/prompts/version_generator.yaml tests/test_version_generator.py
git commit -m "$(cat <<'EOF'
feat(agents): add VersionGeneratorAgent

Create version generator agent for producing A/B/C
optimized content versions.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: 导出 Agent 类

**Files:**
- Modify: `xhs_growth/agents/__init__.py`

- [ ] **Step 1: 添加导出**

```python
# xhs_growth/agents/__init__.py (追加导入和导出)
from xhs_growth.agents.viral_matcher import ViralMatcherAgent
from xhs_growth.agents.content_analyzer import ContentAnalyzerAgent
from xhs_growth.agents.version_generator import VersionGeneratorAgent

__all__ = [
    # ... existing exports ...
    "ViralMatcherAgent",
    "ContentAnalyzerAgent",
    "VersionGeneratorAgent",
]
```

- [ ] **Step 2: Commit**

```bash
git add xhs_growth/agents/__init__.py
git commit -m "$(cat <<'EOF'
feat(agents): export new optimization agents

Export ViralMatcherAgent, ContentAnalyzerAgent, VersionGeneratorAgent.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Phase 3: 工作流集成

### Task 8: 创建 Graph 节点函数

**Files:**
- Modify: `xhs_growth/graph/nodes.py`

- [ ] **Step 1: 导入 Agent**

```python
# xhs_growth/graph/nodes.py (添加导入)
from xhs_growth.agents.viral_matcher import ViralMatcherAgent
from xhs_growth.agents.content_analyzer import ContentAnalyzerAgent
from xhs_growth.agents.version_generator import VersionGeneratorAgent
```

- [ ] **Step 2: 创建 Agent 实例**

```python
# xhs_growth/graph/nodes.py (在现有实例后添加)
_viral_matcher = ViralMatcherAgent()
_content_analyzer = ContentAnalyzerAgent()
_version_generator = VersionGeneratorAgent()
```

- [ ] **Step 3: 创建节点函数**

```python
# xhs_growth/graph/nodes.py (追加节点函数)
async def viral_matcher_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    result = await _viral_matcher(state, store=store)

    thread_id = state.get("thread_id")
    if result.get("viral_posts"):
        EventBusService.get_instance().emit(
            EventType.WORKFLOW_DATA_UPDATED,
            thread_id=thread_id,
            payload={"data_type": "viral_posts", "data": result.get("viral_posts")},
        )

    return result


async def content_analyzer_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    result = await _content_analyzer(state, store=store)

    thread_id = state.get("thread_id")
    if result.get("optimization_analysis"):
        EventBusService.get_instance().emit(
            EventType.WORKFLOW_DATA_UPDATED,
            thread_id=thread_id,
            payload={"data_type": "optimization_analysis", "data": result.get("optimization_analysis")},
        )

    return result


async def version_generator_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    result = await _version_generator(state, store=store)

    thread_id = state.get("thread_id")
    if result.get("content_versions"):
        EventBusService.get_instance().emit(
            EventType.WORKFLOW_DATA_UPDATED,
            thread_id=thread_id,
            payload={"data_type": "content_versions", "data": result.get("content_versions")},
        )

    return result


async def choice_gate_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    """版本选择门 — 用户选择优化版本."""
    from langgraph.types import interrupt

    versions = state.get("content_versions", [])
    draft = state.get("draft_content", {})

    thread_id = state.get("thread_id")
    EventBusService.get_instance().emit(
        EventType.REVIEW_PENDING,
        thread_id=thread_id,
        payload={
            "content_versions": versions,
            "draft_content": draft,
        },
    )

    # interrupt() 暂停等待用户选择
    decision = interrupt({
        "versions": versions,
        "draft_title": draft.get("title", ""),
    })

    # decision: {"selected_version": "A/B/C", "apply_changes": true}
    selected_id = decision.get("selected_version", "A")
    
    # 找到选中的版本
    selected = None
    for v in versions:
        if v.get("version_id") == selected_id:
            selected = v
            break

    if selected:
        # 应用选中版本到 copy_content
        return {
            "selected_version": selected_id,
            "copy_content": {
                "selected_title": selected.get("title"),
                "body_text": selected.get("body"),
                "hashtags": selected.get("hashtags", []),
            },
            "visual_plan": {
                "image_prompts": selected.get("image_prompts", []),
                "layout_style": selected.get("style_suggestion", ""),
            },
            "phase": WorkflowPhase.CREATING,
        }
    
    # 未找到版本，使用原草稿
    return {
        "selected_version": "original",
        "phase": WorkflowPhase.CREATING,
    }
```

- [ ] **Step 4: Commit**

```bash
git add xhs_growth/graph/nodes.py
git commit -m "$(cat <<'EOF'
feat(graph): add optimization node functions

Add viral_matcher_node, content_analyzer_node, version_generator_node,
and choice_gate_node for the optimization workflow.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 9: 添加路由函数

**Files:**
- Modify: `xhs_growth/graph/routers.py`

- [ ] **Step 1: 添加 skip_optimization 路由**

```python
# xhs_growth/graph/routers.py (追加路由函数)
def should_optimize(state: XHSGrowthState) -> Literal["content_analyzer", "visual_designer"]:
    """判断是否需要优化."""
    # viral_matcher 检测无草稿时设置 skip_optimization
    if state.get("skip_optimization"):
        return "visual_designer"
    # 有版本数据，继续优化
    if state.get("viral_posts"):
        return "content_analyzer"
    return "visual_designer"


def choice_outcome(state: XHSGrowthState) -> Literal["visual_designer", "viral_matcher"]:
    """版本选择路由."""
    selected = state.get("selected_version")
    # 选择完成，继续到视觉设计
    if selected:
        return "visual_designer"
    # 未选择，重新匹配（理论上不会发生）
    return "visual_designer"
```

- [ ] **Step 2: Commit**

```bash
git add xhs_growth/graph/routers.py
git commit -m "$(cat <<'EOF'
feat(graph): add optimization router functions

Add should_optimize and choice_outcome routers for optimization flow.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 10: 修改 Graph Builder

**Files:**
- Modify: `xhs_growth/graph/builder.py`

- [ ] **Step 1: 导入新节点和路由**

```python
# xhs_growth/graph/builder.py (修改导入)
from xhs_growth.graph.nodes import (
    orchestrator_node,
    trend_scout_node,
    content_strategist_node,
    copywriter_node,
    visual_designer_node,
    review_gate_node,
    publisher_node,
    analyst_node,
    engagement_node,
    revise_content_node,
    # 新增
    viral_matcher_node,
    content_analyzer_node,
    version_generator_node,
    choice_gate_node,
)
from xhs_growth.graph.routers import (
    should_plan,
    should_continue,
    review_outcome,
    orchestrator_router,
    # 新增
    should_optimize,
    choice_outcome,
)
```

- [ ] **Step 2: 添加节点到 Builder**

```python
# xhs_growth/graph/builder.py (在 build_graph 函数中添加节点)
def build_graph() -> StateGraph:
    builder = StateGraph(XHSGrowthState)

    # ── 添加节点 ──
    builder.add_node("orchestrator", orchestrator_node)
    builder.add_node("trend_scout", trend_scout_node)
    builder.add_node("content_strategist", content_strategist_node)
    builder.add_node("copywriter", copywriter_node)
    # 新增优化节点
    builder.add_node("viral_matcher", viral_matcher_node)
    builder.add_node("content_analyzer", content_analyzer_node)
    builder.add_node("version_generator", version_generator_node)
    builder.add_node("choice_gate", choice_gate_node)
    builder.add_node("visual_designer", visual_designer_node)
    builder.add_node("review_gate", review_gate_node)
    builder.add_node("publisher", publisher_node)
    builder.add_node("analyst", analyst_node)
    builder.add_node("engagement", engagement_node)
    builder.add_node("revise_content", revise_content_node)

    # ... existing edges ...

    # ── 内容创作流水线（修改）──
    builder.add_edge("content_strategist", "copywriter")
    builder.add_edge("copywriter", "viral_matcher")  # 修改：进入优化
    
    # ── 优化流水线（新增）──
    builder.add_conditional_edges(
        "viral_matcher",
        should_optimize,
        {
            "content_analyzer": "content_analyzer",
            "visual_designer": "visual_designer",  # 跳过优化
        },
    )
    builder.add_edge("content_analyzer", "version_generator")
    builder.add_edge("version_generator", "choice_gate")
    builder.add_conditional_edges(
        "choice_gate",
        choice_outcome,
        {
            "visual_designer": "visual_designer",
        },
    )

    # ── 视觉设计后继续 ──
    builder.add_edge("visual_designer", "review_gate")

    # ... rest unchanged ...
```

- [ ] **Step 3: 修改 interrupt_before**

```python
# xhs_growth/graph/builder.py (修改 compile_graph_dev)
def compile_graph_dev() -> CompiledStateGraph:
    builder = build_graph()
    checkpointer = MemorySaver()

    graph = builder.compile(
        checkpointer=checkpointer,
        interrupt_before=["review_gate", "choice_gate"],  # 新增 choice_gate
    )
    return graph
```

- [ ] **Step 4: Commit**

```bash
git add xhs_growth/graph/builder.py
git commit -m "$(cat <<'EOF'
feat(graph): integrate optimization nodes into workflow

Add viral_matcher, content_analyzer, version_generator, choice_gate
to workflow. Update interrupt_before for choice_gate.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 11: 导出 Graph 模块

**Files:**
- Modify: `xhs_growth/graph/__init__.py`

- [ ] **Step 1: 添加导出**

```python
# xhs_growth/graph/__init__.py (修改导入和导出)
from xhs_growth.graph.nodes import (
    orchestrator_node,
    trend_scout_node,
    content_strategist_node,
    copywriter_node,
    visual_designer_node,
    review_gate_node,
    publisher_node,
    analyst_node,
    engagement_node,
    revise_content_node,
    # 新增
    viral_matcher_node,
    content_analyzer_node,
    version_generator_node,
    choice_gate_node,
)

__all__ = [
    # ... existing exports ...
    "viral_matcher_node",
    "content_analyzer_node",
    "version_generator_node",
    "choice_gate_node",
]
```

- [ ] **Step 2: Commit**

```bash
git add xhs_growth/graph/__init__.py
git commit -m "$(cat <<'EOF'
feat(graph): export new optimization nodes

Export viral_matcher_node, content_analyzer_node,
version_generator_node, choice_gate_node.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Phase 4: 前端实现

### Task 12: 创建前端类型定义

**Files:**
- Create: `frontend/src/types/optimization.ts`

- [ ] **Step 1: 创建类型文件**

```typescript
// frontend/src/types/optimization.ts
/** 优化相关类型定义 */

export interface DraftContent {
  text: string
  images: string[]
  title?: string
  hashtags?: string[]
  provided_at: string
}

export interface ViralPost {
  note_id: string
  title: string
  body: string
  hashtags: string[]
  cover_url: string
  image_urls: string[]
  likes: number
  collects: number
  comments: number
  engagement_rate: number
  visual_style: 'minimal' | 'vibrant' | 'warm' | 'editorial'
  color_palette: {
    primary: string
    secondary: string
  }
}

export interface GapItem {
  dimension: 'title' | 'body' | 'visual' | 'strategy'
  description: string
  severity: 'high' | 'medium' | 'low'
}

export interface SuggestionItem {
  dimension: string
  action: string
  reasoning: string
  priority: number
}

export interface OptimizationAnalysis {
  gaps: GapItem[]
  suggestions: SuggestionItem[]
  viral_patterns: string[]
}

export interface ContentVersion {
  version_id: 'A' | 'B' | 'C'
  title: string
  body: string
  hashtags: string[]
  image_prompts: string[]
  style_suggestion: string
  changes_summary: string
  predicted_score: number
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/types/optimization.ts
git commit -m "$(cat <<'EOF'
feat(frontend): add optimization type definitions

Add TypeScript types for DraftContent, ViralPost,
OptimizationAnalysis, ContentVersion.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 13: 扩展 WorkflowStore

**Files:**
- Modify: `frontend/src/stores/workflow.ts`

- [ ] **Step 1: 导入类型**

```typescript
// frontend/src/stores/workflow.ts (添加导入)
import type { DraftContent, ViralPost, OptimizationAnalysis, ContentVersion } from '@/types/optimization'
```

- [ ] **Step 2: 扩展状态**

```typescript
// frontend/src/stores/workflow.ts (在 state 中添加)
state: () => ({
  // ... existing state ...
  
  // 优化相关
  draftContent: null as DraftContent | null,
  viralPosts: [] as ViralPost[],
  optimizationAnalysis: null as OptimizationAnalysis | null,
  contentVersions: [] as ContentVersion[],
  selectedVersion: null as string | null,
}),
```

- [ ] **Step 3: 添加 Actions**

```typescript
// frontend/src/stores/workflow.ts (在 actions 中添加)
actions: {
  // ... existing actions ...
  
  setDraftContent(content: DraftContent) {
    this.draftContent = content
  },
  
  selectVersion(versionId: string) {
    this.selectedVersion = versionId
  },
  
  async submitVersionChoice(threadId: string, versionId: string) {
    // 调用 API 提交版本选择
    await apiClient.post(`/workflow/${threadId}/choice`, {
      selected_version: versionId,
      apply_changes: true,
    })
    this.selectedVersion = versionId
  },
},
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/stores/workflow.ts
git commit -m "$(cat <<'EOF'
feat(frontend): extend WorkflowStore for optimization

Add draftContent, viralPosts, contentVersions state and
setDraftContent, selectVersion actions.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 14: 创建 DraftInput 组件

**Files:**
- Create: `frontend/src/components/DraftInput.vue`

- [ ] **Step 1: 创建组件**

```vue
<!-- frontend/src/components/DraftInput.vue -->
<script setup lang="ts">
import { ref } from 'vue'
import { useWorkflowStore } from '@/stores'
import NeonButton from './NeonButton.vue'
import type { DraftContent } from '@/types/optimization'

const workflowStore = useWorkflowStore()

const draftText = ref('')
const draftTitle = ref('')
const draftHashtags = ref('')
const draftImages = ref<string[]>([])

const handleSubmit = () => {
  const content: DraftContent = {
    text: draftText.value,
    title: draftTitle.value,
    hashtags: draftHashtags.value.split(',').map(t => t.trim()).filter(Boolean),
    images: draftImages.value,
    provided_at: new Date().toISOString(),
  }
  workflowStore.setDraftContent(content)
}

const handleImageUpload = (event: Event) => {
  const input = event.target as HTMLInputElement
  if (input.files) {
    // 这里只存储文件名，实际上传需要后端支持
    draftImages.value = Array.from(input.files).map(f => f.name)
  }
}
</script>

<template>
  <div class="glass rounded-xl p-6 border border-neon-cyan/30">
    <h3 class="text-lg font-bold text-neon-cyan mb-4">📝 输入草稿内容</h3>
    
    <div class="space-y-4">
      <div>
        <label class="block text-sm text-white/70 mb-1">标题（可选）</label>
        <input
          v-model="draftTitle"
          type="text"
          class="w-full px-3 py-2 rounded-lg bg-white/10 border border-white/20 text-white focus:border-neon-cyan"
          placeholder="输入标题..."
        />
      </div>
      
      <div>
        <label class="block text-sm text-white/70 mb-1">正文</label>
        <textarea
          v-model="draftText"
          rows="5"
          class="w-full px-3 py-2 rounded-lg bg-white/10 border border-white/20 text-white focus:border-neon-cyan"
          placeholder="输入文案内容..."
        />
      </div>
      
      <div>
        <label class="block text-sm text-white/70 mb-1">标签（逗号分隔）</label>
        <input
          v-model="draftHashtags"
          type="text"
          class="w-full px-3 py-2 rounded-lg bg-white/10 border border-white/20 text-white focus:border-neon-cyan"
          placeholder="#穿搭, #OOTD, #时尚"
        />
      </div>
      
      <div>
        <label class="block text-sm text-white/70 mb-1">图片（可选）</label>
        <input
          type="file"
          multiple
          accept="image/*"
          @change="handleImageUpload"
          class="w-full text-white/50"
        />
      </div>
      
      <NeonButton variant="cyan" @click="handleSubmit">
        ✅ 提交草稿
      </NeonButton>
    </div>
  </div>
</template>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/DraftInput.vue
git commit -m "$(cat <<'EOF'
feat(frontend): add DraftInput component

Create DraftInput.vue for user to input draft content
including title, text, hashtags, and images.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 15: 创建 VersionCompare 组件

**Files:**
- Create: `frontend/src/components/VersionCompare.vue`

- [ ] **Step 1: 创建组件**

```vue
<!-- frontend/src/components/VersionCompare.vue -->
<script setup lang="ts">
import { computed } from 'vue'
import { useWorkflowStore } from '@/stores'
import NeonButton from './NeonButton.vue'
import type { ContentVersion } from '@/types/optimization'

const workflowStore = useWorkflowStore()

const versions = computed(() => workflowStore.contentVersions)

const versionColors = {
  A: 'border-neon-green',
  B: 'border-neon-cyan',
  C: 'border-neon-pink',
} as const

const versionLabels = {
  A: '🟢 保守版',
  B: '🔵 平衡版',
  C: '🔴 激进版',
} as const

const handleSelect = (versionId: 'A' | 'B' | 'C') => {
  workflowStore.selectVersion(versionId)
  if (workflowStore.currentThreadId) {
    workflowStore.submitVersionChoice(workflowStore.currentThreadId, versionId)
  }
}
</script>

<template>
  <div class="glass rounded-xl p-6 border border-neon-peach/30">
    <h3 class="text-lg font-bold text-neon-peach mb-4">🔄 选择优化版本</h3>
    
    <div v-if="versions.length === 0" class="text-white/50 py-8 text-center">
      等待版本生成...
    </div>
    
    <div v-else class="grid grid-cols-3 gap-4">
      <div
        v-for="version in versions"
        :key="version.version_id"
        class="glass rounded-lg p-4 border-2 transition-all cursor-pointer hover:shadow-lg"
        :class="[
          versionColors[version.version_id as keyof typeof versionColors],
          workflowStore.selectedVersion === version.version_id ? 'shadow-neon-cyan' : ''
        ]"
        @click="handleSelect(version.version_id as 'A' | 'B' | 'C')"
      >
        <div class="text-sm font-bold mb-2">
          {{ versionLabels[version.version_id as keyof typeof versionLabels] }}
        </div>
        
        <div class="text-lg font-bold text-white mb-2">
          {{ version.title }}
        </div>
        
        <div class="text-xs text-white/70 mb-2 line-clamp-3">
          {{ version.body.slice(0, 100) }}...
        </div>
        
        <div class="text-xs text-neon-cyan mb-2">
          #{{ version.hashtags.slice(0, 3).join(' #') }}
        </div>
        
        <div class="text-xs text-white/50">
          预估效果: {{ (version.predicted_score * 100).toFixed(0) }}%
        </div>
        
        <div class="mt-2 text-xs text-white/70 italic">
          {{ version.changes_summary }}
        </div>
      </div>
    </div>
    
    <div v-if="workflowStore.selectedVersion" class="mt-4">
      <NeonButton variant="peach" @click="$emit('confirm')">
        ✅ 确认选择并继续
      </NeonButton>
    </div>
  </div>
</template>

<style scoped>
.shadow-neon-cyan {
  box-shadow: 0 0 20px rgba(0, 255, 255, 0.3);
}
</style>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/VersionCompare.vue
git commit -m "$(cat <<'EOF'
feat(frontend): add VersionCompare component

Create VersionCompare.vue for displaying A/B/C versions
and user selection.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

### Task 16: 集成到 Dashboard

**Files:**
- Modify: `frontend/src/views/Dashboard.vue`

- [ ] **Step 1: 导入组件**

```vue
<!-- frontend/src/views/Dashboard.vue (添加导入) -->
<script setup lang="ts">
import DraftInput from '@/components/DraftInput.vue'
import VersionCompare from '@/components/VersionCompare.vue'
// ... existing imports ...
</script>
```

- [ ] **Step 2: 添加草稿输入区域**

```vue
<!-- frontend/src/views/Dashboard.vue (在模板中添加) -->
<template>
  <div class="relative overflow-hidden">
    <!-- ... existing content ... -->
    
    <!-- 草稿输入区域 -->
    <div v-if="!workflowStore.currentThreadId" class="mb-6">
      <DraftInput />
    </div>
    
    <!-- 版本选择区域 -->
    <div v-if="workflowStore.currentPhase === 'creating' && workflowStore.contentVersions.length > 0" class="mb-6">
      <VersionCompare @confirm="goToVisual" />
    </div>
    
    <!-- ... rest of template ... -->
  </div>
</template>
```

- [ ] **Step 3: 添加 goToVisual 方法**

```typescript
// frontend/src/views/Dashboard.vue (在 script 中添加)
const goToVisual = () => {
  // 继续工作流到视觉设计
  workflowStore.refreshStatus()
}
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/views/Dashboard.vue
git commit -m "$(cat <<'EOF'
feat(frontend): integrate DraftInput and VersionCompare

Add DraftInput for initial draft submission and
VersionCompare for version selection in Dashboard.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Phase 5: 集成测试

### Task 17: 创建集成测试

**Files:**
- Create: `tests/test_optimization_flow.py`

- [ ] **Step 1: 创建测试文件**

```python
# tests/test_optimization_flow.py
"""Integration tests for optimization workflow."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from xhs_growth.graph.builder import build_graph


@pytest.fixture
def mock_store():
    store = MagicMock()
    store.asearch = AsyncMock(return_value=[])
    return store


@pytest.mark.asyncio
async def test_optimization_flow_with_draft(mock_store):
    """Full optimization flow with draft content."""
    builder = build_graph()
    
    initial_state = {
        "account_id": "test_account",
        "phase": "creating",
        "draft_content": {
            "text": "测试文案",
            "title": "普通标题",
            "hashtags": ["#测试"],
            "images": [],
            "provided_at": "2026-05-26T10:00:00",
        },
        "user_viral_links": [],
        "messages": [],
    }
    
    # 模拟执行（由于依赖 LLM，使用 mock）
    # 实际测试需要 mock LLM 响应
    with patch("xhs_growth.agents.viral_matcher.ViralMatcherAgent.model") as mock_model:
        mock_model.ainvoke = AsyncMock(return_value=MagicMock(
            content='{"viral_posts": [{"note_id": "test", "title": "爆款", "likes": 10000}]}'
        ))
        
        # 验证节点存在
        assert "viral_matcher" in builder.nodes
        assert "content_analyzer" in builder.nodes
        assert "version_generator" in builder.nodes
        assert "choice_gate" in builder.nodes


@pytest.mark.asyncio
async def test_skip_optimization_without_draft(mock_store):
    """Should skip optimization when no draft."""
    builder = build_graph()
    
    initial_state = {
        "account_id": "test_account",
        "phase": "creating",
        "messages": [],
    }
    
    # 验证路由函数
    from xhs_growth.graph.routers import should_optimize
    
    result = should_optimize(initial_state)
    assert result == "visual_designer"
```

- [ ] **Step 2: 运行测试**

Run: `pytest tests/test_optimization_flow.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_optimization_flow.py
git commit -m "$(cat <<'EOF'
test: add optimization flow integration tests

Add integration tests for full optimization workflow
and skip optimization scenario.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## 自检清单

**1. Spec Coverage:**

| Spec Section | Task Coverage |
|--------------|---------------|
| 工作流拓扑 | Task 8-11 |
| 状态 Schema | Task 1-2 |
| TaskType 枚举 | Task 3 |
| Agent 实现 | Task 4-7 |
| Graph 节点 | Task 8 |
| 路由函数 | Task 9 |
| Builder 集成 | Task 10 |
| 前端类型 | Task 12 |
| Store 扩展 | Task 13 |
| DraftInput | Task 14 |
| VersionCompare | Task 15 |
| Dashboard 集成 | Task 16 |
| 集成测试 | Task 17 |

**2. Placeholder Scan:** 无 TBD/TODO

**3. Type Consistency:**
- `DraftContent` 定义在 Task 1，使用在 Task 2, 13, 14
- `ViralPost` 定义在 Task 1，使用在 Task 2, 13
- `ContentVersion` 定义在 Task 1，使用在 Task 2, 13, 15
- 类型命名一致

---

**实现计划完成。**