# 生产部署指南

本文档说明如何将 XHS Growth Agent 部署到生产环境。

## 架构概览

```
┌─────────────────────────────────────────────────────┐
│                    Load Balancer                     │
└─────────────────────────────────────────────────────┘
                          │
          ┌───────────────┼───────────────┐
          │               │               │
    ┌─────┴─────┐   ┌─────┴─────┐   ┌─────┴─────┐
    │  API #1   │   │  API #2   │   │  API #3   │
    │ (FastAPI) │   │ (FastAPI) │   │ (FastAPI) │
    └─────┬─────┘   └─────┬─────┘   └─────┬─────┘
          │               │               │
          └───────────────┼───────────────┘
                          │
              ┌───────────┼───────────┐
              │           │           │
        ┌─────┴─────┐ ┌───┴───┐ ┌─────┴─────┐
        │ PostgreSQL│ │ Redis │ │   LLM     │
        │  (State)  │ │(Cache)│ │ Providers │
        └───────────┘ └───────┘ └───────────┘
```

## 环境要求

### 软件

| 组件 | 版本 | 用途 |
|------|------|------|
| Python | 3.11+ | 后端运行 |
| PostgreSQL | 15+ | 状态持久化 |
| Redis | 7+ | 缓存和会话 |
| Node.js | 18+ | 前端构建 |

### 硬件 (建议)

| 资源 | 最小 | 推荐 |
|------|------|------|
| CPU | 2核 | 4核 |
| 内存 | 4GB | 8GB |
| 存储 | 20GB | 50GB |

## PostgreSQL 配置

### 1. 安装 PostgreSQL

```bash
# Ubuntu/Debian
sudo apt install postgresql postgresql-contrib

# macOS
brew install postgresql@15
```

### 2. 创建数据库

```bash
sudo -u postgres psql
CREATE DATABASE xhs_growth;
CREATE USER xhs_user WITH PASSWORD 'secure_password';
GRANT ALL PRIVILEGES ON DATABASE xhs_growth TO xhs_user;
```

### 3. 连接配置

```bash
# .env
POSTGRES_URI=postgresql://xhs_user:secure_password@localhost:5432/xhs_growth
```

### 4. SSL 连接 (生产)

```bash
POSTGRES_URI=postgresql://xhs_user:secure_password@db-host:5432/xhs_growth?sslmode=require
```

## Redis 配置

### 1. 安装 Redis

```bash
# Ubuntu/Debian
sudo apt install redis-server

# macOS
brew install redis
```

### 2. 配置密码

```bash
# /etc/redis/redis.conf
requirepass your_redis_password
```

### 3. 连接配置

```bash
# .env
REDIS_URI=redis://:your_redis_password@localhost:6379/0
```

## 环境变量设置

### 生产 .env

```bash
# LLM Providers
ANTHROPIC_API_KEY=your_key
OPENAI_API_KEY=your_key
DEEPSEEK_API_KEY=your_key
DASHSCOPE_API_KEY=your_key

# XHS browser login
XHS_USE_BROWSER=true
XHS_CHROME_PROFILES_DIR=/path/to/.chrome-profiles
XHS_CDP_BASE_PORT=9222

# Database
POSTGRES_URI=postgresql://user:pass@host:5432/db?sslmode=require
REDIS_URI=redis://:pass@host:6379/0

# Ripple CAS
RIPPLE_BASE_URL=http://ripple-server:8081
RIPPLE_API_TOKEN=your_token
RIPPLE_ENABLED=true

# API Server
API_HOST=0.0.0.0
API_PORT=8000
```

## Public Showcase 发布治理

公开案例默认保持 `private`。只有明确设置为 `public` 的工作流才会出现在
`GET /api/public/showcase/cases`；`unlisted` 仅允许已知链接访问。生产环境应设置稳定的
`XHS_PUBLIC_ID_SECRET`，不要在部署间变更，否则会使已分享的案例链接失效。

可选配置：

- `XHS_SHOWCASE_PUBLIC_IDS`：逗号分隔的 legacy allowlist，仅用于迁移已审核案例。
- `XHS_PUBLIC_URL_HOSTS`：公开发布链接允许的 host，默认仅允许小红书官方域名。

发布/撤销接口位于 `/api/public/admin/showcase/cases/{public_id}`，需要已认证的控制台用户：
`PUT` 用于设置 `private`、`unlisted` 或 `public`、展示标题/摘要和精选排序，`DELETE` 用于
撤销公开。服务端会记录批准/撤销操作者，并在返回前执行文本、URL、标识和颜色白名单脱敏。
详细只读 DTO、manifest 分页和 checkpoint detail 以 `/openapi.json` 为准。

公共页埋点默认发送到同源的 `/api/public/telemetry`；接收端只保留事件白名单、视口/状态等
分类字段和有界耗时，匿名请求按来源限流，数据保留 30 天且不保存 publicId、账号、正文、URL
或原始错误。若目标环境已有 host adapter，可设置 `VITE_TELEMETRY_ENDPOINT` 覆盖接收地址；
显式设为空值可关闭本地构建埋点。已认证控制台可通过
`GET /api/public/admin/telemetry/summary?days=7` 获取按事件/设备/模式聚合的数量、p50/p75
耗时，供 Settings → 公开页体验监控面板接入；该接口不返回原始事件。面板仅在认证后的
Settings 页面显示，接口请求支持取消、周期切换和失败重试。

发布前可运行公共页自动化验收（需要 Chromium 和前端的 `@axe-core/playwright` 依赖）：

```bash
python scripts/acceptance/public_ux_audit.py \
  --base-url http://127.0.0.1:8889 \
  --output /tmp/public-ux-audit.json \
  --screenshot-dir /tmp/public-ux-audit-screenshots
```

脚本会检查真实空态的 private-by-default，并用无敏感 fixture 覆盖 Showcase/Replay 的
320–1440px、中文/英文、明暗主题、正常/减弱动画、横向溢出、阶段键盘导航和 axe
serious/critical；fixture 结果不能替代真实公开案例的 owner 授权、Lighthouse 或慢网采样。
需要做受限网络抽样时，可在小规模代表性组合上显式启用 Slow 4G 和 Save-Data：

```bash
python scripts/acceptance/public_ux_audit.py \
  --base-url http://127.0.0.1:8889 \
  --network-profile slow-4g \
  --save-data \
  --max-combinations 4 \
  --output /tmp/public-ux-audit-slow-4g.json
```

`--network-profile` 默认是 `online`；受限网络命令用于采样证据，不改变默认全矩阵的发布门槛。

## Docker 部署

### docker-compose.yml

```yaml
version: '3.8'

services:
  api:
    build: .
    ports:
      - "8000:8000"
    environment:
      - POSTGRES_URI=postgresql://xhs:password@db:5432/xhs_growth
      - REDIS_URI=redis://:password@redis:6379/0
    depends_on:
      - db
      - redis
    env_file:
      - .env

  frontend:
    build: ./frontend
    ports:
      - "3000:3000"
    depends_on:
      - api

  db:
    image: postgres:15
    environment:
      POSTGRES_DB: xhs_growth
      POSTGRES_USER: xhs
      POSTGRES_PASSWORD: password
    volumes:
      - postgres_data:/var/lib/postgresql/data

  redis:
    image: redis:7
    command: redis-server --requirepass password
    volumes:
      - redis_data:/data

volumes:
  postgres_data:
  redis_data:
```

### 构建和运行

```bash
docker-compose build
docker-compose up -d
```

## CDP 多 profile 部署（多账号发布）

CDP 模式下，发布连接到常驻真实 Chrome（profile 自带扫码登录态），绕过 XHS 反爬。
单账号用 `.chrome-profile/` + 全局 `XHS_CDP_ENDPOINT`；多账号需每账号独立
`--user-data-dir` + 独立 `--remote-debugging-port` 的常驻 Chrome。

### 1. 配置环境变量

在 `.env` 中设置（env-only，不入 system_config）：

```bash
# per-account profile 基础目录（创建账号时自动分配 <dir>/<account_id>）
XHS_CHROME_PROFILES_DIR=/test/xhs/.chrome-profiles
# 起始 port（创建账号时从 base+1 递增找首个未占用 port）
XHS_CDP_BASE_PORT=9222
# Creator Center background import interval (hours; 0 disables the scheduler)
CREATOR_STATS_SYNC_INTERVAL_HOURS=6
# 可选：显式指定 Chrome binary 路径（默认自动探测 google-chrome > google-chrome-stable > chromium）
# XHS_CHROME_BIN=/usr/bin/google-chrome
```

### 2. 安装 Chrome

host 需安装真实 Chrome（非 chromium，反爬指纹基线不同）：

```bash
# RHEL/Alibaba Linux
sudo dnf install -y google-chrome-stable
# 验证
which google-chrome  # /usr/bin/google-chrome
```

### 3. 创建账号并扫码登录

账号创建时自动分配 `chrome_profile_path` + `cdp_port`（写回 accounts 表）。
首次需扫码登录（headed Chrome 开 XHS creator 登录页）：

```bash
# 用 CLI 命令（推荐，与 xhs-growth 风格一致）
xhs-growth login <account_id>
# 或直接调脚本
# python3 -m backend.cli.main login <account_id>
```

打开 headed Chrome 至 `https://creator.xiaohongshu.com/login`，用小红书 App 扫码。
登录态写入该账号的 `user_data_dir`，持久——之后常驻 CDP Chrome 复用，无需再扫码。

### 4. 启动常驻 Chrome（launcher）

launcher 在 **host** 上跑（Chrome 在 host，backend 容器经
`host.containers.internal:<port>` 连接）。读 accounts 表，为每个 active 且
有 `cdp_port` 的账号保活一个 Chrome：

```bash
# 启动/保活（HTTP 探活 + stale SingletonLock 清理 + 启动）
scripts/chrome-profiles.sh start
# 查看状态（每账号 port + alive/dead）
scripts/chrome-profiles.sh status
# 停止所有（按 pidfile SIGTERM，超时 SIGKILL）
scripts/chrome-profiles.sh stop
# headed 启动（默认；扫码登录态需 headed）
scripts/chrome-profiles.sh start
# headless 启动（已登录后省内存）
scripts/chrome-profiles.sh start --headless
```

launcher 逻辑（`backend/services/chrome_launcher.py`，可单测）：
- HTTP-probe `GET /json/version` on `127.0.0.1:<port>` 探活——活则 skip
- 死则检 `<user_data_dir>/SingletonLock`：PID 死则清 SingletonLock/Cookie/Socket，
  PID 活则 skip（不抢同 dir）
- 启 `google-chrome --user-data-dir=<path> --remote-debugging-port=<port>
  --remote-debugging-address=0.0.0.0 --no-first-run --no-default-browser-check &`
  并写 pidfile

### 5. 容器网络

`--remote-debugging-address=0.0.0.0` 让 host 上的 Chrome 端口对容器可见。
backend 容器经 `host.containers.internal:<port>` 连接（`get_account_cdp_endpoint`
自动解析 host——容器内返 `host.containers.internal`，本地 dev 返 `127.0.0.1`）。
deploy.sh 的 `xhs-net` 网络已支持此解析。

### 6. 部署流程

```bash
# 1. 部署 backend + postgres 容器
scripts/deploy.sh deploy

# 2. host 上启动常驻 Chrome（非容器，Chrome 在 host）
scripts/chrome-profiles.sh start

# 3. 新账号：先扫码登录，再 launcher start 保活
xhs-growth login <new_account_id>
scripts/chrome-profiles.sh start
```

向后兼容：账号无 `cdp_port`（0/null）→ 发布时 fallback 全局
`_resolve_cdp_endpoint`（`XHS_CDP_ENDPOINT` 或 `host.containers.internal:9223`），
不破坏现有单账号 `.chrome-profile/` 模式。

## API 服务器启动

### 使用 Uvicorn

```bash
# 单进程 (开发)
uvicorn xhs_growth.api.app:app --reload

# 多进程 (生产)
uvicorn xhs_growth.api.app:app \
  --host 0.0.0.0 \
  --port 8000 \
  --workers 4 \
  --proxy-headers
```

### 使用 Gunicorn

```bash
gunicorn xhs_growth.api.app:app \
  -k uvicorn.workers.UvicornWorker \
  -w 4 \
  -b 0.0.0.0:8000
```

## 前端部署

### 构建

```bash
cd frontend
npm run build
```

### 部署选项

1. **静态托管**: Nginx/Vercel/Netlify
2. **与 API 同源**: 通过 FastAPI static files

```python
# xhs_growth/api/app.py
from fastapi.staticfiles import StaticFiles
app.mount("/", StaticFiles(directory="frontend/dist", html=True), name="static")
```

## 监控和日志

### Prometheus 指标

```python
from prometheus_fastapi_instrumentator import Instrumentator
Instrumentator().instrument(app).expose(app)
```

### 日志配置

```python
import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/app.log'),
        logging.StreamHandler()
    ]
)
```

## 健康检查

```bash
# API 健康检查
curl http://localhost:8000/health

# PostgreSQL 连接检查
psql -h localhost -U xhs_user -d xhs_growth -c "SELECT 1"

# Redis 连接检查
redis-cli -a password ping
```

## 备份策略

### PostgreSQL 备份

```bash
# 每日备份
pg_dump xhs_growth > backup_$(date +%Y%m%d).sql

# 定时任务 (cron)
0 2 * * * pg_dump xhs_growth > /backups/xhs_$(date +\%Y\%m\%d).sql
```

### Redis 备份

```bash
# RDB 备份 (redis.conf)
save 60 1000
```

## 故障恢复

### API 重启

```bash
# systemd 服务
sudo systemctl restart xhs-growth-api

# Docker
docker-compose restart api
```

### 数据恢复

```bash
# PostgreSQL 恢复
psql xhs_growth < backup.sql
```

## 安全加固

参见 `docs/security.md`:
- API 认证配置
- CORS 设置
- Rate limiting
- Secrets 管理
