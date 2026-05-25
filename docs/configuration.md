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

### 小红书平台

| 变量 | 必填 | 说明 | 注意 |
|------|------|------|------|
| `XHS_COOKIE` | 是 | 小红书登录 cookie | 有效期约30天，需定期刷新 |
| `XHS_USER_ID` | 是 | 用户 ID | 从 cookie 中提取 |

### 数据库

| 变量 | 必填 | 说明 | 默认值 |
|------|------|------|--------|
| `POSTGRES_URI` | 生产必填 | PostgreSQL 连接字符串 | 无（开发模式用内存） |
| `REDIS_URI` | 生产必填 | Redis 连接字符串 | 无（开发模式不使用） |

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