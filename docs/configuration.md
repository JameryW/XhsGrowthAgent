# Configuration Reference

本文档说明 XHS Growth Agent 的所有配置选项。

## 环境变量

### LLM Provider Keys

| 变量 | 必填 | 说明 | 默认值 |
|------|------|------|--------|
| `ANTHROPIC_API_KEY` | 是 | Anthropic Claude API key | 无 |
| `OPENAI_API_KEY` | 是 | OpenAI GPT API key | 无 |
| `DEEPSEEK_API_KEY` | 是 | DeepSeek API key | 无 |
| `DASHSCOPE_API_KEY` | 否 | 阿里云 Qwen API key | 无 |

### 小红书浏览器登录

| 变量 | 必填 | 说明 | 注意 |
|------|------|------|------|
| `XHS_USE_BROWSER` | 否 | 启用浏览器/CDP 发布流程 | 生产发布建议启用 |
| `XHS_CHROME_PROFILES_DIR` | 否 | 小红书账号浏览器 profile 目录 | 默认使用项目内 `.chrome-profiles` |
| `XHS_CDP_BASE_PORT` | 否 | 账号浏览器 CDP 起始端口 | 默认 `9222` |

### 数据库

| 变量 | 必填 | 说明 | 默认值 |
|------|------|------|--------|
| `POSTGRES_URI` | 生产必填 | PostgreSQL 连接字符串 | 无（开发模式用内存） |
| `REDIS_URI` | 生产必填 | Redis 连接字符串 | 无（开发模式不使用） |

### 创作者中心数据导入

| 变量 | 必填 | 说明 | 默认值 |
|------|------|------|--------|
| `CREATOR_STATS_SYNC_INTERVAL_HOURS` | 否 | 后台定时导入基准间隔（实际执行间隔在 0.75–1.5× 间按三角分布取值，峰值 1×）；仅导入当前激活账号，设为 `0` 可关闭 | `36` |
| `CREATOR_STATS_SKIP_DAY_CHANCE` | 否 | 反风控：每轮以该概率整天跳过同步（按星期加权）；`0` 从不跳过 | `0.25` |
| `CREATOR_STATS_STARTUP_DELAY_MIN_SECONDS` / `CREATOR_STATS_STARTUP_DELAY_MAX_SECONDS` | 否 | 反风控：服务启动/重启后首次同步前的随机延迟（秒）；设为 `0` 恢复启动即跑 | `600` / `2400` |
| `CREATOR_STATS_ACTIVE_WINDOW_START_HOUR` / `CREATOR_STATS_ACTIVE_WINDOW_END_HOUR` | 否 | 反风控：每日同步时刻限制在中国本地时间（UTC+8）窗口内，深夜不爬 | `9` / `22` |
| `CREATOR_STATS_LIGHT_RUN_CHANCE` | 否 | 反风控：每轮以该概率只抓概览+笔记列表（不深入创作者中心详情）；`0` 关闭 | `0.35` |
| `CREATOR_STATS_ENRICH_SKIP_CHANCE` | 否 | 反风控：深入轮内逐篇以该概率跳过创作者中心详情；`0` 关闭 | `0.30` |
| `CREATOR_STATS_HOME_ENTRY_CHANCE` | 否 | 反风控：先打开创作者主页再进数据页的概率 | `0.55` |
| `CREATOR_STATS_PAGE_STOP_CHANCE` | 否 | 反风控：列表翻页提前停止概率 | `0.28` |
| `CREATOR_STATS_DASHBOARD_BROWSE_CHANCE` | 否 | 反风控：数据页先点日期 Tab 再进笔记管理的概率 | `0.30` |
| `CREATOR_STATS_MAX_LIST_PAGES` | 否 | 反风控：单次同步最多翻几页笔记列表（硬上限） | `5` |
| `CREATOR_STATS_MAX_DETAIL_VISITS` | 否 | 反风控：单次同步最多打开几篇笔记详情页 | `4` |
| `CREATOR_STATS_MAX_BODY_VISITS` | 否 | 已废弃，仅保留旧配置兼容；任何值均被忽略，创作者中心同步永久不访问公开笔记页 | `0` |
| `CREATOR_STATS_SCHEDULED_FORCE_LIGHT` | 否 | 定时同步强制轻量轮（只概览+列表，不点详情）；`0` 关闭强制模式，但仍受普通轻量概率控制 | `1` |
| `CREATOR_STATS_DEEP_EVERY_N_RUNS` | 否 | 自动同步默认只抓概览+笔记列表；未设置或设为 `0` 时永远轻量，只有显式设置正整数 N 才在连续 N 次轻量后开启一次深入轮 | `0` |
| `CREATOR_STATS_MIN_REFRESH_HOURS` | 否 | 账号数据仍在该小时内视为新鲜，跳过浏览器同步；`0` 关闭 | `18` |
| `CREATOR_STATS_SAFE_MODE` | 否 | `1` 时进一步收紧：更高轻量概率、更少翻页/详情、更慢节奏 | `0` |
| `CREATOR_STATS_DETAIL_CIRCUIT_FAILURES` | 否 | 反风控：创作者中心详情连续失败几次后熔断本轮深入 | `2` |
| `CREATOR_STATS_BODY_EMPTY_CIRCUIT` | 否 | 已废弃，仅保留旧配置兼容；公开正文抓取已永久移除 | `3` |
| `CREATOR_STATS_SESSION_WIND_DOWN_MIN_S` / `CREATOR_STATS_SESSION_WIND_DOWN_MAX_S` | 否 | 抓取结束后关页前随机停留（秒） | `3` / `12` |
| `CREATOR_STATS_ENRICH_RECENT_DAYS` | 否 | 增量同步：发布距今不超过该天数的笔记总是重新访问详情页 | `3` |
| `CREATOR_STATS_BODY_LOOKBACK_DAYS` | 否 | 已废弃，仅保留旧配置兼容；不再决定任何浏览行为 | `14` |
| `CREATOR_STATS_REQUEST_DELAY_MIN_S` / `CREATOR_STATS_REQUEST_DELAY_MAX_S` | 否 | 单次同步内逐篇页面访问之间的随机间隔（秒） | `3.5` / `10.0` |
| `CREATOR_STATS_LONG_PAUSE_CHANCE` | 否 | 反风控：长停顿概率（走神/切任务） | `0.12` |
| `CREATOR_STATS_LONG_PAUSE_MIN_S` / `CREATOR_STATS_LONG_PAUSE_MAX_S` | 否 | 反风控：长停顿区间（秒） | `20` / `60` |
| `CREATOR_STATS_SYNC_COOLDOWN_MINUTES` | 否 | 反风控：距上次成功同步不足该分钟数时跳过（含手动）；`0` 关闭 | `45` |
| `CREATOR_STATS_AUTH_FAIL_COOLDOWN_MINUTES` | 否 | 反风控：鉴权失败后禁止再同步的分钟数；`0` 关闭 | `120` |
| `XHS_QR_LOGIN_COOLDOWN_SECONDS` | 否 | 反风控：同一账号两次扫码启动的最小间隔（秒）；短时间反复弹码易触发登录风控；`0` 关闭 | `900` |
| `XHS_QR_RISK_BLOCK_SECONDS` | 否 | 反风控：检测到 300012/安全限制后禁止再次扫码的秒数；前端同步禁用按钮；`0` 关闭 | `3600` |

Creator statistics imports are permanently confined to the Creator Center
overview, list, and Creator Center detail metric APIs. The transport never
navigates to `www.xiaohongshu.com/explore/<note>`; the legacy
`CREATOR_STATS_MAX_BODY_VISITS`, `CREATOR_STATS_BODY_LOOKBACK_DAYS`, and
`CREATOR_STATS_BODY_EMPTY_CIRCUIT` settings are accepted only for deployment
compatibility and cannot re-enable public-note browsing. `body_text` already
present in a Creator Center payload is preserved as-is.

此外，连续同步失败会自动退避降频：第二次连续失败起，下次运行间隔按 1.5–2.5× 随机放大（固定倍数也是可预测的退避节律），成功一次即复位。抓取过程中还会在页面间产生随机鼠标轨迹、滚动列表时偶尔回滚上一屏，且每轮的深入预算按详情预算基准随机缩放 0.35–0.75×，避免"全程无指针活动""只往下滚""时长聚类"等机器特征。单账号手动同步仍遵守新鲜窗口；`sync-all` 有批量冷却，扫码登录后的首次同步才会强制刷新；定时同步也会跳过窗口内的数据。

**PostgreSQL URI 格式:**
```
postgresql://user:password@host:5432/database?sslmode=require
```

**Redis URI 格式:**
```
redis://:password@host:6379/0
```

### Ripple CAS 模拟引擎

| 变量 | 必填 | 说明 | 默认值 |
|------|------|------|--------|
| `RIPPLE_BASE_URL` | 否 | Ripple 服务地址 | `http://127.0.0.1:8081` |
| `RIPPLE_API_TOKEN` | 否 | Ripple API token | 无 |
| `RIPPLE_ENABLED` | 否 | 是否启用 Ripple | `true` |

---

## 配置文件

### settings.py 字段说明

```python
class Settings(BaseSettings):
    # LLM Configuration
    model_env: str = "prod"
    """运行环境: prod | dev | test"""
    
    anthropic_api_key: str = ""
    """Anthropic API key - 用于 Claude 模型"""
    
    openai_api_key: str = ""
    """OpenAI API key - 用于 GPT-4o"""
    
    deepseek_api_key: str = ""
    """DeepSeek API key - 用于 routing/scouting 任务"""
    
    # XHS Platform
    xhs_cookie: str = ""
    """小红书 cookie - 用于 API 认证"""
    
    xhs_user_id: str = ""
    """小红书用户 ID"""
    
    # Database
    postgres_uri: str = ""
    """PostgreSQL URI - 生产模式状态持久化"""
    
    redis_uri: str = ""
    """Redis URI - 生产模式缓存"""
    
    # Ripple
    ripple_base_url: str = "http://127.0.0.1:8081"
    """Ripple CAS 服务地址"""
    
    ripple_api_token: str = ""
    """Ripple API 认证 token"""
    
    ripple_enabled: bool = True
    """是否启用 Ripple 传播预测"""
```

---

## 模型路由配置

### TaskType → Model 映射

| TaskType | Model | Provider | 用途 |
|----------|-------|----------|------|
| `ROUTING` | deepseek-chat | DeepSeek | 编排决策 |
| `SCOUTING` | deepseek-chat | DeepSeek | 趋势发现 |
| `STRATEGY` | claude-sonnet-4-20250514 | Anthropic | 内容策略 |
| `WRITING` | claude-sonnet-4-20250514 | Anthropic | 文案生成 |
| `VISUAL` | gpt-4o | OpenAI | 视觉分析 |
| `ANALYSIS` | gpt-4o | OpenAI | 数据分析 |
| `PUBLISHING` | qwen-plus | DashScope | 发布执行 |
| `ENGAGEMENT` | deepseek-chat | DeepSeek | 用户互动 |

### 模型参数默认值

```python
class ModelConfig:
    temperature: float = 0.7  # 创意任务默认
    max_tokens: int = 4096    # 最大输出长度
    timeout: int = 60         # API 超时（秒）
```

**各模型差异:**
- Claude (WRITING/STRATEGY): temperature=0.7，平衡创意与准确
- GPT-4o (VISUAL/ANALYSIS): temperature=0.5，偏向准确
- DeepSeek (ROUTING/SCOUTING): temperature=0.6，快速决策

---

## 开发 vs 生产配置

### 开发模式 (默认)

| 配置项 | 值 |
|--------|-----|
| 检查点 | MemorySaver（内存） |
| 中断节点 | `review_gate`（人工审核） |
| 数据库 | 不使用 PostgreSQL/Redis |
| Ripple | 本地 mock |

### 生产模式

| 配置项 | 值 |
|--------|-----|
| 检查点 | AsyncPostgresSaver |
| 中断节点 | `review_gate` |
| 数据库 | PostgreSQL + Redis |
| Ripple | 外部服务 |

**切换方式:**
```python
# 开发
graph = compile_graph_dev()

# 生产
graph = await compile_graph_prod(POSTGRES_URI)
```

---

## 场景分析缓存

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `SCENE_ANALYSIS_EXPIRY_DAYS` | 场景数据过期天数 | 7 |
| `SCENE_MIN_SAMPLES` | 最小样本数才开始缓存 | 10 |

---

## 配置验证

```bash
# 验证必填变量
python -c "from xhs_growth.config.settings import Settings; s = Settings(); print(s.model_env)"

# 验证 LLM 连接
python -c "from xhs_growth.models.router import get_model; print(get_model('writing'))"
```
