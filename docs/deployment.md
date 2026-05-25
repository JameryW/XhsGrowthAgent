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

# XHS Platform
XHS_COOKIE=your_cookie
XHS_USER_ID=your_user_id

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