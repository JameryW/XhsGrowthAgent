# Design Creative Memory Layer

## Goal

为创作流程设计并实现一个 memory 层，每次创作过程基于历史沉淀的风格指纹、高转化策略、优质素材进行创作，形成「创作即沉淀」的闭环，让系统越用越懂创作者风格。

## What I already know

* 现有 `MemoryManager`（backend/memory/store.py）提供 4 个 namespace：content_history, audience_preferences, performance_insights, strategy_notes
* 当前 memory 能力很弱：只存文本 insight/strategy_note，无结构化创作数据
* copywriter 已调用 `_recall_memory`（content_history + audience_preferences），但只召回标题+互动率文本
* content_strategist 已调用 `_recall_memory`（performance_insights），但只召回 insight 文本
* visual_designer 完全不使用 memory
* analyst 是当前唯一做沉淀的 agent（store_insight + store_strategy_note），但存的是非结构化文本
* publisher 做了 content_history 记录，但只存 title/topic/hashtags/status
* BaseStore 是 LangGraph 的语义搜索存储，支持 asearch/aput
* 现有视觉分析系统（VisualAnalysisService）有 SceneDatabase + StyleOption，但无账号级沉淀
* Ripple 校准已有对比逻辑（_compare_prediction_vs_actual），但校准结果只存文本

## Requirements

### 三层 Memory 架构

**1. Style DNA — 风格指纹** (accounts/{id}/style_dna)

```python
class StyleDNA(TypedDict):
    style_id: str
    tone: str                  # 文风: 活泼/专业/治愈/犀利
    voice_patterns: list[str]  # 常用句式/开头/结尾模板
    visual_style: str          # 视觉风格: 温暖治愈/高冷高级/...
    color_palette: list[str]   # 偏好色系
    layout_preference: str     # 偏好排版: 网格/拼贴/单焦点
    emoji_usage: str           # emoji 使用风格: 重度/克制/无
    hashtag_style: str         # 标签风格: 精准少而美/广撒网/蹭热点
    engagement_rate: float     # 该风格的历史互动率
    sample_count: int          # 采样次数
    last_used: str             # ISO timestamp
```

**2. Conversion Playbook — 转化策略手册** (accounts/{id}/conversion_playbook)

```python
class ConversionPlay(TypedDict):
    play_id: str
    trigger_condition: str     # 什么时候用: "新品首发"/"教程干货"/"种草安利"
    title_formula: str         # 标题公式: "数字+痛点+解决方案"
    opening_hook: str          # 开头钩子模板
    cta_pattern: str           # 行动号召模式
    best_posting_hour: int     # 最佳发布时段
    avg_engagement_rate: float
    avg_save_rate: float       # 收藏率
    content_type: str          # note/video/carousel
    niche: str                 # 适用赛道
    proven_count: int          # 验证次数
    last_proven: str           # 最近验证时间
```

**3. Material Vault — 优质素材库** (accounts/{id}/material_vault)

```python
class MaterialEntry(TypedDict):
    material_id: str
    category: str              # 封面/文案片段/标签组合/选题角度
    content: str               # 实际内容
    source_post_id: str        # 来源帖子
    source_engagement_rate: float
    tags: list[str]            # "高转化"/"爆款标题"/"引流开头"
    reuse_count: int           # 被复用次数
    effectiveness: float       # 复用后平均效果 (0-1)
    weight: float              # 权重（软降权用，初始 1.0）
    created_at: str
```

### 行业基准 (benchmarks/{niche}/)

独立结构，与账号级 memory 不同 TypedDict：

```python
class NicheBenchmark(TypedDict):
    niche: str
    top_styles: list[dict]          # [{style_name, usage_rate, avg_engagement}]
    avg_engagement_by_angle: dict   # {angle: avg_rate}
    trending_formulas: list[str]    # 当前赛道热门标题公式
    peak_posting_hours: list[int]   # 赛道整体高峰时段
    updated_at: str
```

### Agent 集成

* **copywriter**: 读取 Style DNA + Material Vault(文案片段)，沉淀标题/文案片段到 Material Vault
* **visual_designer**: 读取 Style DNA(视觉偏好)，沉淀风格/配色选择到 Style DNA
* **content_strategist**: 读取 Style DNA + Conversion Playbook + NicheBenchmark，沉淀新策略到 Conversion Playbook
* **brief_analyzer**: 读取 Style DNA + NicheBenchmark（商单场景匹配行业基准），沉淀商单风格偏好到 Style DNA
* **analyst**: 输出校准数据，由异步任务回写三个 namespace

### Graceful Fallback

* 所有 `recall_*` 方法在 BaseStore 不可用（None / 异常）时返回空列表，不中断创作流程
* 所有 `deposit_*` 方法在 BaseStore 不可用时静默失败 + warning 日志
* CreativeMemory 构造时检查 store 是否为 None，设置 `_available` 标志
* 冷启动和无 store 场景走同一条路径：返回默认值

### 校准机制（异步）

* analyst 执行时只产出 `calibration_payload`（校准数据），写入 state
* workflow 结束后，异步 `calibrate_creative_memory()` 任务读取 payload 回写
* 回写操作：Style DNA 合并 engagement_rate、Conversion Playbook 递增 proven_count、Material Vault 更新 effectiveness、低效素材软降权（weight 降低）

### 冷启动策略

* 前 N 次（默认 5 次）创作无 memory 可召回，使用默认 Style DNA
* 默认 Style DNA 从 `style_library` 的 `get_default_styles()` 生成
* 行业基准初始从 SceneDatabase 现有数据提取
* `CREATIVE_MEMORY_MIN_SAMPLES = 5`（可配置）

### Material Vault 软降权

* effectiveness 连续低于阈值（默认 0.3）时 weight *= 0.8
* 搜索时按 weight * relevance 排序，低效素材自然沉底
* 永不删除，保留历史参考

## Acceptance Criteria

* [ ] CreativeMemory 类实现三层 namespace 读写 + 行业基准读取
* [ ] StyleDNA / ConversionPlay / MaterialEntry / NicheBenchmark TypedDict 定义
* [ ] Style DNA 支持同风格合并（加权平均 engagement_rate + sample_count 累加）
* [ ] Conversion Playbook 支持 proven_count 递增
* [ ] Material Vault 支持 effectiveness 更新 + weight 软降权
* [ ] copywriter 在创作前读取 memory，创作后沉淀
* [ ] visual_designer 在创作前读取 memory，创作后沉淀
* [ ] content_strategist 在创作前读取 memory，创作后沉淀
* [ ] brief_analyzer 在创作前读取 memory，创作后沉淀
* [ ] analyst 输出 calibration_payload，不直接回写
* [ ] 异步 calibrate_creative_memory() 任务回写三个 namespace
* [ ] BaseStore 不可用时 graceful fallback（不中断创作流程）
* [ ] 冷启动可用（无 memory 时不报错，用默认值）
* [ ] 单元测试覆盖核心逻辑（合并、降权、冷启动、fallback）

## Definition of Done

* Tests added/updated (unit/integration where appropriate)
* Lint / typecheck / CI green
* 所有 Agent 集成完成，创作流程端到端可运行

## Decision (ADR-lite)

**Context**: Creative Memory 需要决定三个关键设计问题
**Decision**:
1. MVP 包含三层 + 行业基准（非仅单账号）
2. 行业基准用独立 TypedDict（NicheBenchmark），不与账号级混用
3. analyst 校准通过异步任务回写，不阻塞主流程

**Consequences**: 异步回写意味着校准有延迟（下一轮创作才能用到上一轮的校准结果），但不影响当前轮次的创作速度

## Out of Scope

* 前端 UI 展示 memory 内容
* Memory 导出/导入功能
* 手动编辑/删除 memory 的 API
* 跨账号数据共享（每个账号隔离）

## Technical Notes

* 核心文件：backend/memory/store.py（现有 MemoryManager）
* 需新增：backend/memory/creative.py（CreativeMemory 类）、backend/memory/types.py（TypedDict）
* 需新增：backend/memory/calibrator.py（异步校准任务）
* 需修改：backend/agents/copywriter.py, visual_designer.py, content_strategist.py, analyst.py, brief_analyzer.py
* Namespace：accounts/{id}/style_dna, accounts/{id}/conversion_playbook, accounts/{id}/material_vault, benchmarks/{niche}/
* BaseStore.asearch 支持语义搜索，aput 支持 upsert（同 key 覆盖）
* 合并策略需要先 asearch 再 aput（BaseStore 无原子的 read-modify-write）
* 异步任务可用 asyncio.create_task 或后台工作线程
* 异步校准任务失败时需重试（最多 3 次）+ 日志记录，避免数据丢失
