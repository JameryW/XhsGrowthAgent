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

### 合规与自动化底线（P0）

- **伪签名已删除**：`XHSSignature` 不再生成伪造 `x-s`/`x-t`。依赖旧 HTTP 加签的调用返回 `signature_unavailable`，不会静默空结果。平台操作走 headed CDP / 浏览器路径。
- **防检测伪装已硬删除**：无 `playwright-stealth`、无 `XHS_BROWSER_STEALTH` opt-in、无 `navigator.webdriver` 隐藏脚本、无 `AutomationControlled` 伪装参数。登录走真实 headed CDP Chrome profile。
- **发布资格 = 确定性判定器 + 审计**：`backend/services/compliance/judgers.py` 按失败模式（词库 / 商单披露 / 硬合规 / 双自动 / 高风险自动放行）各自判定，结果写入 `evaluation_result.publish_eligibility`；**不**把 LLM 综合自评当作放行依据。质量面板仅驱动修订回路。
- **双自动硬拒绝**：`AUTO_APPROVE_LOW_RISK=true` 与 `auto_publish=true` 不能同时开启（`POST /start` 与 `xhs-growth run` 一致）。合规 blocking、商单 `is_commercial`、高风险垂类永不 `auto_low_risk`。
- **发布回执**：`publish_confirmation` 记录 `confirmer` / `source`（`human` / `auto_*`）/ `confirmed_at`，以及 P1-4 `ai_content_declared`（含 AI 生成内容声明，Review 默认勾选）。
- **私信策略**：默认仅回复未读/入站白名单用户；日配额默认私信 20、评论回复 50；冷启动「新建私信」需 `XHS_ALLOW_OUTBOUND_DM=1` + 逐条 `human_confirmed`。风控标记命中后互动暂停默认 6 小时，Settings `/api/system/risk-gates` 可见原因与剩余时间。
- **确定性词库**：LLM 评估前扫描违禁词（含 niche 扩展库）；商单 brief 模式置 `is_commercial=true`，发布前须勾选披露确认且文案保留合作/广告标注。

## API 安全

### 当前状态（P1-5）

- **控制台认证**: `POST /api/auth/login` 签发 bearer token；受保护路由经 `get_current_user` 校验。凭据仅来自 `console_users` 表（无硬编码 admin 回退）。
- **Token 后端**: `REDIS_URI`（或 `Settings().database.redis_uri`）可达时使用 Redis + TTL（与 `AUTH_TOKEN_EXPIRE_HOURS`，默认 24h 对齐）；不可用时降级进程内存，并在日志标明 `backend=redis|memory`。多实例部署必须配置 Redis，否则各进程 token 不共享。
- **CORS**: FastAPI 挂载 `CORSMiddleware`（当前 `allow_origins=["*"]` 便于本地/内网联调；生产应收紧为显式来源列表）。
- **本地运行**: 默认 `localhost:8000`

### 生产部署建议

1. **收紧 CORS**
   ```python
   app.add_middleware(
       CORSMiddleware,
       allow_origins=["https://your-domain.com"],
       allow_credentials=True,
   )
   ```

2. **配置 Redis token 后端**
   ```bash
   REDIS_URI=redis://:password@redis:6379/0
   AUTH_TOKEN_EXPIRE_HOURS=24
   ```

3. **Rate Limiting**（可选）
   ```python
   from slowapi import Limiter
   limiter = Limiter(key_func=get_remote_address)
   ```

## 数据安全

### PostgreSQL

- 使用 SSL 连接 (`POSTGRES_URI`)
- 定期备份数据
- 限制数据库访问 IP
- 风控冷却（`risk_gate_cooldowns` KV）经 DB 共享，多实例一致

### Redis

- 设置密码 (`REDIS_URI`)
- 不暴露公网
- 启用 TLS
- 用途：控制台 auth token（P1-5）；不可用时 auth 降级内存

### 用户内容与个保数据清单（P1-3）

| 数据族 | 存储位置 | 默认保留 | 删除/导出 |
|--------|----------|----------|-----------|
| 工作流元数据 / 创作内容 | PostgreSQL `workflows` + checkpoint / Artifact store | 运维策略 | 工作流删除 API |
| Creator Stats 笔记快照 | PostgreSQL creator_stats* | 账号级导入历史 | 账号删除 |
| Relationship Memory（Audience） | `creator_agent_relationships` | 90 天（`XHS_PRIVACY_RELATIONSHIP_RETENTION_DAYS`） | `DELETE /api/creator-agent/audience/{id}`；导出 `GET .../export` |
| Learning Signals | `creator_agent_learning_signals` | 随 Audience 删除联动 | 同上 |
| 评论抓取缓存 | 进程内 scrape cache（脱敏昵称/ID） | 90 天（`XHS_PRIVACY_COMMENTS_RETENTION_DAYS`） | 保留清理任务 |
| 私信入站白名单 peer | risk_gates KV / 内存 | 90 天（`XHS_PRIVACY_DM_RETENTION_DAYS`） | 保留清理任务 |
| 控制台用户 | `console_users` | 账号生命周期 | 管理 API（撤 token） |

启动时 / 运维可调用 `backend.services.privacy_retention.run_privacy_cleanup()` 执行到期清理。遵守小红书与适用个保法规；默认偏安全。

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
