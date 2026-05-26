# 发布前内容优化系统设计

## 概述

为 XhsGrowthAgent 添加发布前内容优化功能，支持：
- 用户输入草稿文案和图片
- 与爆款笔记对比分析
- 生成多版本优化建议（A/B/C）
- 一键选择应用优化

---

## 工作流拓扑

### 新增节点

```
copywriter → viral_matcher → content_analyzer → version_generator → choice_gate → visual_designer
```

| 节点 | 职责 | 输入 | 输出 |
|------|------|------|------|
| `viral_matcher` | 匹配爆款笔记 | 用户指定的链接 + 自动搜索关键词 | 爆款笔记列表 |
| `content_analyzer` | 对比分析 | 草稿内容 + 爆款笔记 | 分析报告（差距、建议） |
| `version_generator` | 生成多版本 | 分析报告 + 草稿 | A/B/C 版本选项 |
| `choice_gate` | 用户选择 | 版本列表 | 选定版本 + 修改说明 |

### 条件路由

- 用户未提供草稿：`viral_matcher` 检测空草稿 → 直接跳转到 `visual_designer`
- 用户选择版本后：`choice_gate` → 更新 `copy_content` → 继续到 `visual_designer`

---

## 状态 Schema 扩展

### 新增字段

```python
# 用户草稿输入
draft_content: DraftContent

# 爆款对比数据
viral_posts: Annotated[list[ViralPost], _append_list]
user_viral_links: list[str]

# 分析结果
optimization_analysis: OptimizationAnalysis

# 版本选择
content_versions: Annotated[list[ContentVersion], _append_list]
selected_version: str
```

### 子状态模型

#### DraftContent

```python
class DraftContent(TypedDict):
    """用户原始草稿"""
    text: str  # 原始文案文本
    images: list[str]  # 图片路径或 URL
    title: str  # 原始标题（可选）
    hashtags: list[str]  # 原始标签（可选）
    provided_at: str  # 输入时间（启动时/节点注入时）
```

#### ViralPost

```python
class ViralPost(TypedDict):
    """爆款参考笔记"""
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
    visual_style: str  # minimal/vibrant/warm/editorial
    color_palette: dict  # RGB 主色/辅色
```

#### OptimizationAnalysis

```python
class OptimizationAnalysis(TypedDict):
    """优化分析报告"""
    gaps: list[GapItem]  # 发现的差距项
    suggestions: list[SuggestionItem]  # 优化建议
    viral_patterns: list[str]  # 爆款共有的成功模式

class GapItem(TypedDict):
    dimension: str  # title/body/visual/strategy
    description: str
    severity: str  # high/medium/low

class SuggestionItem(TypedDict):
    dimension: str
    action: str
    reasoning: str
    priority: int  # 1-5
```

#### ContentVersion

```python
class ContentVersion(TypedDict):
    """内容版本"""
    version_id: str  # "A", "B", "C"
    title: str  # 优化后的标题
    body: str  # 优化后的正文
    hashtags: list[str]  # 优化后的标签
    image_prompts: list[str]  # 图片生成建议
    style_suggestion: str  # 视觉风格建议
    changes_summary: str  # 改动摘要（vs 原草稿）
    predicted_score: float  # 预估优化效果
```

---

## Agent 与工具

### 新增 Agent

| Agent | Prompt 文件 | TaskType | 模型路由 |
|-------|-------------|----------|----------|
| `ViralMatcherAgent` | `viral_matcher.yaml` | `VIRAL_MATCHING` | `deepseek-chat` |
| `ContentAnalyzerAgent` | `content_analyzer.yaml` | `CONTENT_ANALYSIS` | `claude-sonnet-4-20250514` |
| `VersionGeneratorAgent` | `version_generator.yaml` | `VERSION_GEN` | `gpt-4o` |

### 新增工具

#### viral_matcher 工具

```python
fetch_note_detail(note_id: str) -> dict
    # 获取单篇笔记详情（复用 XHSClient.get_note_detail）

search_viral_posts(keyword: str, limit: int = 10) -> list[ViralPost]
    # 搜索爆款笔记，按互动量排序

extract_visual_patterns(image_urls: list[str]) -> dict
    # 提取视觉特征（复用 VisualDataExtractor）
```

#### content_analyzer 工具

```python
compare_titles(draft_title: str, viral_titles: list[str]) -> dict
    # 标题对比分析

compare_body_structure(draft_body: str, viral_bodies: list[str]) -> dict
    # 正文结构对比

compare_visual_style(draft_images: list[str], viral_images: list[str]) -> dict
    # 视觉风格对比

analyze_engagement_patterns(viral_posts: list[ViralPost]) -> dict
    # 互动模式分析
```

#### version_generator 工具

```python
generate_title_variants(base_title: str, patterns: list[str]) -> list[str]
    # 生成标题变体

rewrite_body(original: str, suggestions: list[SuggestionItem]) -> list[str]
    # 重写正文

generate_image_prompts(draft_images: list[str], target_style: str) -> list[str]
    # 生成图片提示词
```

### 工具注册

```python
_agent_tools = {
    "viral_matcher": ["fetch_note_detail", "search_viral_posts", "extract_visual_patterns"],
    "content_analyzer": [
        "compare_titles", "compare_body_structure",
        "compare_visual_style", "analyze_engagement_patterns"
    ],
    "version_generator": [
        "generate_title_variants", "rewrite_body", "generate_image_prompts",
        "ripple_predict_content_spread"  # 复用现有 Ripple 预测
    ],
}
```

---

## 前端集成

### 新增组件

| 组件 | 位置 | 功能 |
|------|------|------|
| `DraftInput.vue` | Dashboard 启动区域 | 上传草稿文案/图片 |
| `ViralSelector.vue` | 优化流程中 | 用户指定/选择爆款链接 |
| `VersionCompare.vue` | 优化流程中 | 展示 A/B/C 版本对比 |
| `OptimizationReport.vue` | 优化流程中 | 显示分析报告和建议 |

### 工作流视图更新

原有：
```
🔍 趋势发现 → 📋 策略规划 → ✍️ 文案创作 → 🎨 视觉设计 → ⏳ 审核 → 📤 发布
```

新增：
```
🔍 趋势发现 → 📋 策略规划 → ✍️ 文案创作 → 🔥 爆款匹配 → 📊 对比分析 → 🔄 版本生成 → ⭐ 版本选择 → 🎨 视觉设计 → ⏳ 审核 → 📤 发布
```

### 交互流程

1. 用户在 Dashboard 点击「上传草稿」或启动工作流时填写
2. 工作流到达 `viral_matcher` 时，弹窗询问是否指定爆款链接
3. 用户可选择「手动指定」或「自动匹配」
4. `version_generator` 完成后，展示 `VersionCompare` 卡片组
5. 用户点击选择版本，确认后继续到 `visual_designer`

### Store 扩展

```typescript
interface WorkflowStore {
  // 新增状态
  draftContent: DraftContent | null
  viralPosts: ViralPost[]
  optimizationAnalysis: OptimizationAnalysis | null
  contentVersions: ContentVersion[]
  selectedVersion: string | null

  // 新增 actions
  setDraftContent(content: DraftContent): void
  selectVersion(versionId: string): void
  fetchViralPosts(links: string[]): Promise<void>
}
```

---

## 边界处理

### 边界场景

| 场景 | 处理策略 |
|------|----------|
| 用户未提供草稿 | `viral_matcher` 检测空草稿 → 跳转到 `visual_designer` |
| 用户未指定爆款链接 | 自动匹配：基于 `trend_data` 或 `content_plan` 关键词搜索 |
| 爆款搜索无结果 | 使用 `VisualAnalysisService` 默认推荐 |
| 图片分析失败 | 降级为纯文案分析，视觉使用场景默认值 |
| 版本生成失败 | 保留原草稿，提示「暂无优化建议」继续流程 |
| 用户取消选择 | 默认选择版本 A 继续流程 |

### 重试与超时

| 操作 | 最大重试 | 超时 |
|------|----------|------|
| 爆款搜索 | 3 | 30s |
| 图片视觉分析 | 2 | 60s |
| 版本生成（LLM） | 2 | 90s |

### 性能优化

- **并行爆款搜索**：同时请求用户指定链接 + 自动搜索关键词
- **图片分析缓存**：相同图片 URL 结果缓存 24 小时
- **版本并行生成**：A/B/C 版本可并行生成

---

## 文件变更清单

### 新增文件

```
xhs_growth/agents/viral_matcher.py
xhs_growth/agents/content_analyzer.py
xhs_growth/agents/version_generator.py

xhs_growth/config/prompts/viral_matcher.yaml
xhs_growth/config/prompts/content_analyzer.yaml
xhs_growth/config/prompts/version_generator.yaml

xhs_growth/tools/optimization/__init__.py
xhs_growth/tools/optimization/viral_tools.py
xhs_growth/tools/optimization/analysis_tools.py
xhs_growth/tools/optimization/version_tools.py

xhs_growth/state/substates.py (扩展 DraftContent, ViralPost 等)

frontend/src/components/DraftInput.vue
frontend/src/components/ViralSelector.vue
frontend/src/components/VersionCompare.vue
frontend/src/components/OptimizationReport.vue

frontend/src/types/optimization.ts
```

### 修改文件

```
xhs_growth/graph/builder.py (添加新节点和边)
xhs_growth/graph/nodes/__init__.py (导出新节点)
xhs_growth/graph/routers.py (添加 choice_gate 路由)
xhs_growth/state/schema.py (添加新状态字段)
xhs_growth/config/models.py (添加新 TaskType)
xhs_growth/tools/registry.py (注册新工具)

frontend/src/views/Dashboard.vue (添加 DraftInput)
frontend/src/stores/workflow.ts (扩展状态和 actions)
frontend/src/router/index.ts (如需新路由)
```

---

## 实现优先级

1. **Phase 1**: 后端核心 - 状态扩展 + Agent + 工具
2. **Phase 2**: 工作流集成 - Graph 节点 + 路由
3. **Phase 3**: 前端组件 - DraftInput + VersionCompare
4. **Phase 4**: 端到端测试 - 完整流程验证

---

## 测试策略

### 单元测试

- `test_viral_matcher.py`: 爆款搜索和匹配逻辑
- `test_content_analyzer.py`: 对比分析逻辑
- `test_version_generator.py`: 版本生成逻辑
- `test_optimization_state.py`: 状态模型验证

### 集成测试

- `test_optimization_flow.py`: 从 draft_content 到 selected_version 的完整流程
- `test_optimization_edge_cases.py`: 边界场景处理

### 前端测试

- `DraftInput.spec.ts`: 草稿上传组件
- `VersionCompare.spec.ts`: 版本选择组件