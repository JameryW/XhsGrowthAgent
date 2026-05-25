---
title: Visual Design Tools Enhancement Design
date: 2026-05-23
status: approved
type: feature-design
---

# Visual Design Tools Enhancement Design

## Overview

完善 XhsGrowthAgent 的视觉设计工具（`layout_recommender` 和 `style_library`），从 placeholder 实现升级为基于小红书真实数据的智能推荐系统。

## Requirements Summary

### User Requirements

- **优先完善方向**: 视觉设计工具
- **数据来源**: 接入小红书真实数据，分析热门笔记的视觉特征
- **分析维度**: 全维度（视觉风格、布局结构、视觉元素、垂直领域趋势）
- **成功标准**: 提供多个备选方案供用户选择，比较优劣
- **性能要求**: 无性能要求，重点在准确性
- **实现顺序**: 按场景优先（美食 → 穿搭 → 旅行 → 护肤 → 其他）

### Current State

- `layout_recommender`: Placeholder 实现，返回模拟数据
- `style_library`: Placeholder 实现，返回预定义风格
- 缺少真实数据分析能力
- 缺少多备选方案支持
- 缺少优劣分析功能

## Architecture Design

### System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                   Visual Designer Agent                      │
│                  (调用工具层)                                 │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                     Tool Layer                               │
│  ┌──────────────────────┐  ┌──────────────────────┐         │
│  │ layout_recommender   │  │ style_library        │         │
│  │  - 获取布局方案       │  │  - 获取风格列表       │         │
│  │  - 返回多个备选       │  │  - 返回多个备选       │         │
│  └──────────────────────┘  └──────────────────────┘         │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                  Service Layer                               │
│  ┌──────────────────────────────────────────────────────┐   │
│  │        VisualAnalysisService                          │   │
│  │  - 分析小红书热门笔记                                  │   │
│  │  - 提取视觉特征（风格、布局、元素）                    │   │
│  │  - 按场景分类                                          │   │
│  │  - 提供多个备选方案                                    │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                  Data Collection Layer                       │
│  ┌──────────────────────────────────────────────────────┐   │
│  │        XHSClient (已有)                                │   │
│  │  - search_posts(keyword)                               │   │
│  │  - get_trending()                                      │   │
│  │  - 监控关键词热度                                       │   │
│  └──────────────────────────────────────────────────────┐   │
│  ┌──────────────────────────────────────────────────────┐   │
│  │        VisualDataExtractor (新增)                     │   │
│  │  - extract_color_palette(images)                       │   │
│  │  - detect_layout_type(images)                          │   │
│  │  - identify_visual_elements(images)                    │   │
│  │  - classify_visual_style(images)                       │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                  Storage Layer                               │
│  ┌──────────────────────────────────────────────────────┐   │
│  │        Memory Store (已有)                             │   │
│  │  - 缓存分析结果                                        │   │
│  │  - 存储场景数据                                        │   │
│  └──────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────┐   │
│  │        Scene Database (新增)                           │   │
│  │  - 美食场景数据                                        │   │
│  │  - 穿搭场景数据                                        │   │
│  │  - 旅行场景数据                                        │   │
│  │  - 其他场景数据                                        │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### Design Principles

- 分层架构，职责清晰
- 工具层只负责接口，逻辑在服务层
- 数据采集与业务逻辑分离
- 支持按场景优先实现

## Core Components

### 1. VisualAnalysisService

**职责**: 统一管理视觉分析逻辑，为工具层提供服务接口

**Location**: `xhs_growth/services/visual_analysis.py`

**核心方法**:

```python
class VisualAnalysisService:
    """视觉分析服务 - 分析小红书热门笔记的视觉特征"""

    async def analyze_scene(scene: str, limit: int = 50) -> SceneAnalysisResult:
        """分析特定场景的热门笔记

        Args:
            scene: 场景名称（美食/穿搭/旅行/护肤等）
            limit: 分析笔记数量

        Returns:
            SceneAnalysisResult: 包含风格分布、布局分布、元素统计等
        """

    async def get_layout_recommendations(
        scene: str,
        content_type: str,
        image_count: int,
        style_preference: str = None
    ) -> list[LayoutOption]:
        """获取布局推荐方案（多个备选）

        Args:
            scene: 场景名称
            content_type: 内容类型（图文/轮播/视频）
            image_count: 图片数量
            style_preference: 风格偏好

        Returns:
            list[LayoutOption]: 多个布局备选方案，包含优劣分析
        """

    async def get_style_recommendations(
        scene: str,
        content_type: str,
        trending_threshold: float = 0.7
    ) -> list[StyleOption]:
        """获取风格推荐方案（多个备选）

        Args:
            scene: 场景名称
            content_type: 内容类型
            trending_threshold: 热门阈值

        Returns:
            list[StyleOption]: 多个风格备选方案，包含热度、适用场景等
        """
```

**数据结构**:

```python
@dataclass
class ColorPalette:
    """色彩方案"""
    primary_colors: list[str]  # 主色调 ["#FFFFFF", "#F5F5F5"]
    secondary_colors: list[str]  # 辅助色 ["#FFE4E1", "#FFDAB9"]
    color_ratios: dict[str, float]  # 配色比例 {"#FFFFFF": 0.6, "#F5F5F5": 0.3}

@dataclass
class LayoutType:
    """布局类型枚举"""
    UPPER_LOWER = "上下结构"
    GRID = "网格布局"
    LEFT_RIGHT = "左右结构"
    FULL_IMAGE_TEXT_END = "全图+文末"

@dataclass
class SceneAnalysisResult:
    """场景分析结果"""
    scene: str
    sample_size: int

    # 视觉风格分布
    style_distribution: dict[str, float]  # {"现代简约": 0.35, "温暖治愈": 0.25, ...}

    # 布局类型分布
    layout_distribution: dict[str, float]  # {"上下结构": 0.4, "网格布局": 0.3, ...}

    # 色彩方案统计
    color_palettes: list[ColorPalette]

    # 视觉元素统计
    visual_elements: dict[str, int]  # {"贴纸": 45, "滤镜": 30, "字体": 20, ...}

    # 趋势指标
    trending_styles: list[str]
    trending_layouts: list[str]

    # 时间窗口
    analyzed_at: datetime

@dataclass
class LayoutOption:
    """布局方案"""
    layout_type: str  # 上下结构/网格布局/左右结构等
    description: str
    suitable_for: list[str]  # 适用场景
    image_sequence_strategy: str
    text_position: str

    # 数据支持
    popularity_score: float  # 基于热门笔记统计
    avg_engagement: float  # 平均互动率

    # 优劣分析
    pros: list[str]
    cons: list[str]

    # 参考
    reference_posts: list[dict]  # 热门笔记示例

@dataclass
class StyleOption:
    """风格方案"""
    style_name: str
    description: str
    color_palette: list[str]
    suitable_for: list[str]

    # 数据支持
    trending_score: float
    usage_rate: float  # 使用率
    avg_engagement: float

    # 优劣分析
    pros: list[str]
    cons: list[str]

    # 参考
    reference_posts: list[dict]
```

### 2. VisualDataExtractor

**职责**: 从图像数据中提取视觉特征（风格、布局、色彩、元素）

**Location**: `xhs_growth/services/visual_extractor.py`

**核心方法**:

```python
class VisualDataExtractor:
    """视觉数据提取器 - 从图像提取视觉特征"""

    async def extract_color_palette(images: list[str]) -> ColorPalette:
        """提取色彩方案

        Args:
            images: 图片URL列表

        Returns:
            ColorPalette: 主色调、辅助色、配色比例
        """

    async def detect_layout_type(images: list[str]) -> LayoutType:
        """检测布局类型

        Args:
            images: 图片URL列表

        Returns:
            LayoutType: 布局类型（上下结构/网格布局/左右结构等）
        """

    async def identify_visual_elements(images: list[str]) -> dict[str, int]:
        """识别视觉元素

        Args:
            images: 图片URL列表

        Returns:
            dict: 视觉元素统计（贴纸、滤镜、字体、图标等）
        """

    async def classify_visual_style(images: list[str]) -> str:
        """分类视觉风格

        Args:
            images: 图片URL列表

        Returns:
            str: 风格名称（现代简约/温暖治愈/高冷高级等）
        """
```

**实现策略**:
- 初期使用简化算法（基于图像像素分析）
- 后期可接入专业图像识别服务（如 OpenAI Vision API）

### 3. SceneDatabase

**职责**: 管理场景数据存储和查询

**Location**: `xhs_growth/memory/scene_database.py`

**核心方法**:

```python
class SceneDatabase:
    """场景数据库 - 存储场景分析结果"""

    async def save_scene_analysis(result: SceneAnalysisResult) -> None:
        """保存场景分析结果"""

    async def get_scene_analysis(scene: str) -> SceneAnalysisResult | None:
        """获取场景分析结果"""

    async def get_layout_templates(scene: str) -> list[LayoutOption]:
        """获取场景布局模板"""

    async def get_style_templates(scene: str) -> list[StyleOption]:
        """获取场景风格模板"""

    async def update_trending_data(scene: str, data: dict) -> None:
        """更新趋势数据"""
```

**存储策略**:
- 初期使用 JSON 文件存储（`config/scenes/*.json`）
- 后期可迁移到 Memory Store 或数据库

## Data Flow

### Complete Data Flow

```
用户请求 → Visual Designer Agent → 工具调用 → 服务层 → 数据采集 → 存储
```

**详细流程**:

1. **Visual Designer Agent 调用工具**
   - Agent 从 state 获取场景信息
   - 调用 `layout_recommender` 和 `style_library`

2. **VisualAnalysisService 处理请求**
   - 检查缓存（SceneDatabase）
   - 缓存命中：返回缓存结果
   - 缓存未命中：获取热门笔记（XHSClient）
   - 提取视觉特征（VisualDataExtractor）
   - 生成分析结果（SceneAnalysisResult）
   - 保存缓存
   - 返回结果

3. **生成多个备选方案**
   - 从分析结果中提取前3个热门布局
   - 为每个布局生成详细方案（包含优劣分析）
   - 返回多个备选方案

### Scene Priority Implementation

```
Phase 1: 美食场景
  - 实现 VisualAnalysisService 核心逻辑
  - 实现 VisualDataExtractor 基础功能
  - 美食场景数据采集和存储
  - layout_recommender 美食场景支持
  - style_library 美食场景支持

Phase 2: 穿搭场景
  - 扩展 VisualDataExtractor 穿搭特征识别
  - 穿搭场景数据采集和存储
  - 工具支持穿搭场景

Phase 3: 旅行场景
  - 扩展旅行特征识别
  - 旅行场景数据采集

Phase 4: 护肤场景
  - 扩展护肤特征识别
  - 护肤场景数据采集

Phase 5: 其他场景
  - 支持更多垂直领域
```

## Error Handling

### Layered Error Handling

**工具层**: 捕获所有异常，返回降级方案

```python
def get_default_layouts() -> list[dict]:
    """获取默认布局方案（降级）"""
    return [
        {
            "layout_type": "上下结构",
            "description": "简单易用的上下布局",
            "popularity_score": 0.5,
            "pros": ["简单易用", "适合新手"],
            "cons": ["缺少个性化"],
        },
        {
            "layout_type": "网格布局",
            "description": "多图网格展示",
            "popularity_score": 0.5,
            "pros": ["适合多图", "视觉丰富"],
            "cons": ["需要设计技巧"],
        },
    ]

@tool
async def layout_recommender(...) -> list[dict]:
    try:
        service = VisualAnalysisService()
        options = await service.get_layout_recommendations(...)
        return [option.to_dict() for option in options]
    except XHSAPIError as e:
        logger.error(f"小红书 API 错误: {e}")
        return get_default_layouts()  # 返回基础布局方案
    except VisualAnalysisError as e:
        logger.error(f"视觉分析错误: {e}")
        return get_default_layouts()
    except Exception as e:
        logger.error(f"未知错误: {e}")
        return get_default_layouts()
```

**服务层**: 抛出特定异常，提供空结果

```python
class VisualAnalysisService:
    async def analyze_scene(...) -> SceneAnalysisResult:
        try:
            posts = await XHSClient.search_posts(...)
            if not posts:
                raise NoDataError(f"未找到场景 '{scene}' 的热门笔记")

            # 提取视觉特征
            color_palettes = await VisualDataExtractor.extract_color_palette(post_images)
            layouts = await VisualDataExtractor.detect_layout_type(post_images)
            elements = await VisualDataExtractor.identify_visual_elements(post_images)
            styles = await VisualDataExtractor.classify_visual_style(post_images)

            # 构建分析结果
            return SceneAnalysisResult(
                scene=scene,
                sample_size=len(posts),
                style_distribution=calculate_distribution(styles),
                layout_distribution=calculate_distribution(layouts),
                color_palettes=color_palettes,
                visual_elements=elements,
                trending_styles=extract_top_items(styles, 3),
                trending_layouts=extract_top_items(layouts, 3),
                analyzed_at=datetime.now()
            )

        except NoDataError:
            # 返回空分析结果
            return SceneAnalysisResult(
                scene=scene,
                sample_size=0,
                style_distribution={},
                layout_distribution={},
                color_palettes=[],
                visual_elements={},
                trending_styles=[],
                trending_layouts=[],
                analyzed_at=datetime.now()
            )
        except Exception as e:
            logger.error(f"场景分析失败: {e}")
            raise VisualAnalysisError(f"分析场景 '{scene}' 失败")
```

### Fallback Strategy

**多级降级方案**:

- **Level 1**: 返回基于热门笔记的简化方案（从缓存）
- **Level 2**: 返回预定义的基础布局
- **Level 3**: 返回最简单的默认布局

### Cache Expiration

- 缓存有效期：24小时
- 数据完整性检查：样本量 ≥ 30
- 自动刷新机制：定期更新场景数据

## Testing Strategy

### Unit Tests

**Location**: `tests/test_visual_service.py`

**测试内容**:
- `VisualAnalysisService.analyze_scene()` - 场景分析成功/失败
- `VisualAnalysisService.get_layout_recommendations()` - 布局推荐
- `VisualAnalysisService.get_style_recommendations()` - 风格推荐
- `VisualDataExtractor` - 色彩提取、布局检测、元素识别、风格分类

### Integration Tests

**Location**: `tests/test_visual_integration.py`

**测试内容**:
- 完整工作流测试（Agent → Tool → Service → Data）
- 真实 API 测试（需要配置环境）
- 备选方案数量验证
- 数据完整性验证

### Performance Tests

**Location**: `tests/test_visual_performance.py`

**测试内容**:
- 分析速度测试（应 < 30秒）
- 缓存有效性测试（缓存响应应快10倍以上）

## Implementation Plan

### Phase 1: 美食场景（优先）

**Week 1**:
- 实现 `VisualAnalysisService` 核心框架
- 实现 `VisualDataExtractor` 基础功能
- 实现 `SceneDatabase` JSON 存储

**Week 2**:
- 美食场景数据采集和存储
- 增强 `layout_recommender`
- 增强 `style_library`
- 单元测试和集成测试

### Phase 2-5: 其他场景

每场景约1周，按优先级逐步实现。

## File Structure

```
xhs_growth/
├── services/
│   ├── visual_analysis.py      # VisualAnalysisService
│   ├── visual_extractor.py     # VisualDataExtractor
│   └── __init__.py
├── memory/
│   ├── scene_database.py       # SceneDatabase
│   └── __init__.py
├── config/
│   ├── scenes/
│   │   ├── food.json           # 美食场景数据
│   │   ├── fashion.json        # 穿搭场景数据
│   │   ├── travel.json         # 旅行场景数据
│   │   └── skincare.json       # 护肤场景数据
│   └── prompts/
│       ├── visual_designer.yaml
│       └── ...
├── tools/
│   ├── content/
│   │   ├── layout.py           # layout_recommender (enhanced)
│   │   ├── style.py            # style_library (enhanced)
│   │   └── __init__.py
│   └── ...
└── ...

tests/
├── test_visual_service.py
├── test_visual_extractor.py
├── test_visual_integration.py
├── test_visual_performance.py
└── ...
```

## Dependencies

### New Dependencies

- `colorthief` - 色彩提取
- `opencv-python` - 图像处理（可选）
- `pillow` - 图像基础操作

### Existing Dependencies

- `langchain_core` - Tool decorator
- `langgraph` - State management
- `xhs_growth.services.XHSClient` - 小红书数据采集

## Success Criteria

### Feature Success

- ✅ 提供至少3个布局备选方案
- ✅ 提供至少5个风格备选方案
- ✅ 每个方案包含优劣分析
- ✅ 每个方案包含参考笔记
- ✅ 支持至少4个场景（美食/穿搭/旅行/护肤）

### Quality Success

- ✅ 单元测试覆盖率 ≥ 80%
- ✅ 集成测试通过
- ✅ 错误处理完善（降级方案可用）
- ✅ 缓存机制有效

## Risks and Mitigation

### Risk 1: 小红书 API 限制

**Mitigation**: 使用缓存、降级方案、请求频率控制

### Risk 2: 图像识别准确性

**Mitigation**: 初期使用简化算法，后期接入专业服务

### Risk 3: 数据时效性

**Mitigation**: 定期刷新缓存，24小时有效期

## Future Enhancements

- 接入 OpenAI Vision API 提升图像识别准确性
- 支持更多垂直领域（健身、家居、教育等）
- 用户个性化推荐（基于历史偏好）
- 实时趋势跟踪（热门风格变化检测）