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
| `CREATOR_STATS_SYNC_INTERVAL_HOURS` | 否 | 后台定时导入基准间隔（实际执行间隔在 0.75–1.5× 间随机，即默认 18–36h，不留固定周期）；仅导入当前激活账号（`get_active_account`，切换账号后旧账号不再同步），设为 `0` 可关闭 | `24` |
| `CREATOR_STATS_SKIP_DAY_CHANCE` | 否 | 反风控：每轮以该概率整天跳过同步——"每天必爬一次"本身是可识别的规律；`0` 从不跳过 | `0.15` |
| `CREATOR_STATS_STARTUP_DELAY_MIN_SECONDS` / `CREATOR_STATS_STARTUP_DELAY_MAX_SECONDS` | 否 | 反风控：服务启动/重启后首次同步前的随机延迟（秒），避免"启动即爬"的机器模式；设为 `0` 恢复启动即跑 | `300` / `1800` |
| `CREATOR_STATS_ACTIVE_WINDOW_START_HOUR` / `CREATOR_STATS_ACTIVE_WINDOW_END_HOUR` | 否 | 反风控：每日同步时刻限制在中国本地时间（UTC+8）的该窗口内，窗口外的候选时刻平移到窗口内；窗口内落点按人类活跃度加权（晚间 20-22 点最高、清晨最低），深夜不爬 | `8` / `23` |
| `CREATOR_STATS_LIGHT_RUN_CHANCE` | 否 | 反风控：每轮以该概率只抓概览+笔记列表就结束（不做逐篇详情/正文深入），模拟人"扫一眼就关掉"的轻量访问；`0` 关闭 | `0.15` |
| `CREATOR_STATS_ENRICH_SKIP_CHANCE` | 否 | 反风控：深入轮内逐篇笔记以该概率跳过详情/正文访问（被跳过的笔记下轮仍会被增量过滤器选中），避免"候选全扫"的机器人完备性特征；`0` 关闭 | `0.15` |
| `CREATOR_STATS_HOME_ENTRY_CHANCE` | 否 | 反风控：每轮以该概率先打开创作者主页再进数据页（真人通常从主页点进去），避免"每次会话都以同一个深链开头"的固定模式；`0` 关闭 | `0.5` |
| `CREATOR_STATS_PAGE_STOP_CHANCE` | 否 | 反风控：笔记列表每翻一页前以该概率停止继续翻页——人很少每次都滚到底，被截断的旧笔记下轮仍会被翻到；`0` 关闭 | `0.15` |
| `CREATOR_STATS_ENRICH_RECENT_DAYS` | 否 | 增量同步：发布距今不超过该天数的笔记总是重新访问详情页 | `7` |
| `CREATOR_STATS_BODY_LOOKBACK_DAYS` | 否 | 增量同步：仅为该天数内发布且尚无正文的笔记抓取公开正文（已有正文永不重抓） | `30` |
| `CREATOR_STATS_REQUEST_DELAY_MIN_S` / `CREATOR_STATS_REQUEST_DELAY_MAX_S` | 否 | 单次同步内逐篇笔记页面访问之间的随机间隔（秒），防风控 | `2.0` / `6.0` |
| `CREATOR_STATS_LONG_PAUSE_CHANCE` | 否 | 反风控：每次访问停顿以小概率改为长停顿（模拟人走神/切换任务），打乱均匀节奏；`0` 关闭 | `0.08` |
| `CREATOR_STATS_LONG_PAUSE_MIN_S` / `CREATOR_STATS_LONG_PAUSE_MAX_S` | 否 | 反风控：长停顿的随机区间（秒） | `15.0` / `45.0` |
| `CREATOR_STATS_SYNC_COOLDOWN_MINUTES` | 否 | 反风控：距上次成功同步不足该分钟数时，再次触发（含手动 sync-all）直接跳过，防止短时间内反复全量爬取；`0` 关闭 | `30` |

此外，连续同步失败会自动退避降频：第二次连续失败起，下次运行间隔按 1.5–2.5× 随机放大（固定倍数也是可预测的退避节律），成功一次即复位。抓取过程中还会在页面间产生随机鼠标轨迹、滚动列表时偶尔回滚上一屏，且每轮的深入预算（会话总时长）随机缩放 0.7–1.3×，避免"全程无指针活动""只往下滚""时长聚类"等机器特征。

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
