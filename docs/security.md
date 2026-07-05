# 安全注意事项

本文档说明 XHS Growth Agent 的安全考量和最佳实践。

## 环境变量管理

### 必填 API Keys

| 变量 | 用途 | 风险等级 |
|------|------|----------|
| `ANTHROPIC_API_KEY` | Claude 模型 | HIGH |
| `OPENAI_API_KEY` | GPT 模型 | HIGH |
| `DEEPSEEK_API_KEY` | DeepSeek 模型 | HIGH |
| `DASHSCOPE_API_KEY` | Qwen 模型 | HIGH |

### 安全实践

1. **不要提交 .env 文件**
   - `.env` 已在 `.gitignore` 中
   - 使用 `.env.example` 作为模板
   - 生产环境使用 secrets manager

2. **API Key 存储**
   ```bash
   # 开发环境
   cp .env.example .env
   # 编辑 .env 填入真实值

   # 生产环境 (推荐)
   # 使用 Kubernetes Secrets 或 AWS Secrets Manager
   ```

3. **Key 权限最小化**
   - Anthropic: 只授予必要模型访问权限
   - OpenAI: 设置使用限额
   - 小红书账号：使用独立创作者账号，通过浏览器扫码登录，不提交浏览器 profile 数据

## 小红书账号安全

- 使用账号页面的扫码登录流程，不在 `.env`、文档或代码中保存 Cookie。
- 浏览器 profile 目录只保存在部署机器本地，避免提交到仓库或日志。
- 使用独立创作者账号，降低主账号风险。

## API 安全

### 当前状态

- **无认证**: 当前为内部工具，无 API 认证
- **本地运行**: 默认 `localhost:8000`
- **无 CORS**: 仅允许本地请求

### 生产部署建议

1. **添加认证**
   ```python
   # FastAPI JWT 认证
   from fastapi.security import HTTPBearer
   security = HTTPBearer()
   ```

2. **CORS 配置**
   ```python
   from fastapi.middleware.cors import CORSMiddleware
   app.add_middleware(
       CORSMiddleware,
       allow_origins=["your-domain.com"],
       allow_credentials=True,
   )
   ```

3. **Rate Limiting**
   ```python
   from slowapi import Limiter
   limiter = Limiter(key_func=get_remote_address)
   ```

## 数据安全

### PostgreSQL

- 使用 SSL 连接 (`POSTGRES_URI`)
- 定期备份数据
- 限制数据库访问 IP

### Redis

- 设置密码 (`REDIS_URI`)
- 不暴露公网
- 启用 TLS

### 用户内容

- 存储在 PostgreSQL
- 包含创作内容、分析数据
- 遵守小红书数据政策

## 日志安全

### 不要记录敏感信息

```python
# 错误示例
logger.info(f"Using cookie: {cookie}")  # ❌

# 正确示例
logger.info("XHS client initialized")  # ✅
```

### 日志级别

- `DEBUG`: 开发环境（不含敏感数据）
- `INFO`: 生产环境
- `ERROR`: 错误堆栈（不含认证信息）

## Ripple CAS 集成

- 外部模拟引擎
- 使用独立 API Token
- 不传输敏感内容数据

```bash
RIPPLE_BASE_URL=http://ripple-server:8081
RIPPLE_API_TOKEN=your-token  # 与 XHS Cookie 分离
```

## 漏洞报告

发现安全问题请邮件报告:
- 不要公开提交 Issue
- 描述漏洞和影响范围
- 提供修复建议（如有）
