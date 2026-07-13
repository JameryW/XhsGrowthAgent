#!/usr/bin/env bash
# deploy.sh — 容器化部署脚本 for XhsGrowthAgent
# 用法: ./scripts/deploy.sh [rebuild|deploy|start|stop|restart|status|backup|restore]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# 从 .env 读取配置
set -a; source "$PROJECT_DIR/.env"; set +a

NET="xhs-net"
BACKEND_IMG="localhost/xhs-growth:latest"
RIPPLE_IMG="localhost/ripple-service:local"
PG_IMG="pgvector/pgvector:pg15"
PG_VOL="xhs-pgdata"
PG_USER="xhs"
PG_DB="xhs_growth"
BACKUP_DIR="$PROJECT_DIR/.backups"

# ── Postgres 管理 ──

cmd_ensure_postgres() {
    # 确保 Postgres 容器运行，带 pgvector 支持
    if podman ps --filter name=postgres-xhs --format '{{.Names}}' | grep -q postgres-xhs; then
        return 0
    fi

    # 容器不存在（已停止或已删除）— 检查是否需要恢复
    if podman ps -a --filter name=postgres-xhs --format '{{.Names}}' | grep -q postgres-xhs; then
        echo ">>> 启动已有 Postgres 容器..."
        podman start postgres-xhs
        sleep 2
        return 0
    fi

    echo ">>> 创建 Postgres 容器（pgvector: $PG_IMG）..."
    podman run -d \
        --name postgres-xhs \
        --network "$NET" \
        --restart always \
        -p 5432:5432 \
        -e POSTGRES_USER="$PG_USER" \
        -e POSTGRES_PASSWORD="$PG_USER" \
        -e POSTGRES_DB="$PG_DB" \
        -v "$PG_VOL:/var/lib/postgresql/data" \
        "$PG_IMG"
    sleep 3
}

# ── 备份与恢复 ──

cmd_backup() {
    # 备份 Postgres 数据到 .backups/ 目录
    mkdir -p "$BACKUP_DIR"
    TIMESTAMP=$(date +%Y%m%d_%H%M%S)
    BACKUP_FILE="$BACKUP_DIR/xhs_growth_${TIMESTAMP}.sql.gz"

    if ! podman ps --filter name=postgres-xhs --format '{{.Names}}' | grep -q postgres-xhs; then
        echo "错误: Postgres 容器未运行，无法备份"
        exit 1
    fi

    echo ">>> 备份 Postgres 数据..."
    podman exec postgres-xhs pg_dump -U "$PG_USER" "$PG_DB" | gzip > "$BACKUP_FILE"
    SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
    echo ">>> 备份完成: $BACKUP_FILE ($SIZE)"

    # 保留最近 5 个备份
    ls -t "$BACKUP_DIR"/xhs_growth_*.sql.gz | tail -n +6 | xargs -r rm --
    echo ">>> 保留最近 5 个备份"
}

cmd_restore() {
    # 从最近的备份恢复 Postgres 数据
    LATEST=$(ls -t "$BACKUP_DIR"/xhs_growth_*.sql.gz 2>/dev/null | head -1)
    if [ -z "$LATEST" ]; then
        echo "错误: 没有找到备份文件（$BACKUP_DIR/xhs_growth_*.sql.gz）"
        exit 1
    fi

    echo ">>> 将从备份恢复: $LATEST"
    read -p "确认恢复？这将覆盖当前数据 [y/N] " confirm
    if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
        echo "取消恢复"
        exit 0
    fi

    # 确保 Postgres 运行
    cmd_ensure_postgres
    sleep 2

    # 终止现有连接并恢复
    echo ">>> 恢复数据..."
    podman exec postgres-xhs psql -U "$PG_USER" -d postgres -c \
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$PG_DB' AND pid <> pg_backend_pid();" 2>/dev/null || true
    podman exec postgres-xhs psql -U "$PG_USER" -d postgres -c "DROP DATABASE IF EXISTS $PG_DB;"
    podman exec postgres-xhs psql -U "$PG_USER" -d postgres -c "CREATE DATABASE $PG_DB;"

    gunzip -c "$LATEST" | podman exec -i postgres-xhs psql -U "$PG_USER" -d "$PG_DB" 2>&1 | tail -5
    echo ">>> 恢复完成"
}

# ── 子命令 ──

# Wait for the backend health endpoint, up to ~60s. The backend loads the
# embedding model on startup (~13s observed), so the old 10s/15s polls raced
# it and printed "后端未响应" even on a successful deploy. Returns non-zero
# on timeout so `set -e` surfaces a real failure instead of silently proceeding.
wait_for_backend() {
    local timeout="${1:-60}"
    echo ">>> 等待后端就绪（最多 ${timeout}s）..."
    for i in $(seq 1 "$timeout"); do
        if curl -sf http://localhost:8889/api/system/health >/dev/null 2>&1; then
            echo "  后端已就绪 (${i}s)"
            return 0
        fi
        sleep 1
    done
    echo "  后端在 ${timeout}s 内未就绪 — 检查日志: podman logs xhs-growth" >&2
    return 1
}

cmd_frontend() {
    echo ">>> 构建前端..."
    (cd "$PROJECT_DIR/frontend" && npm run build)
    echo ">>> 前端构建完成"
}

cmd_rebuild() {
    cmd_frontend
    echo ">>> 重新构建后端镜像..."
    podman build -t "$BACKEND_IMG" "$PROJECT_DIR"
    echo ">>> 镜像构建完成: $BACKEND_IMG"
}

cmd_stop() {
    echo ">>> 停止所有服务..."
    podman stop xhs-growth 2>/dev/null || true
    podman rm   xhs-growth 2>/dev/null || true
    podman stop ripple-service 2>/dev/null || true
    podman rm   ripple-service 2>/dev/null || true
    echo ">>> 后端和 Ripple 已停止（Postgres 保持运行）"
}

cmd_start() {
    echo ">>> 确保 $NET 存在..."
    podman network exists "$NET" 2>/dev/null || podman network create "$NET"

    # HF embedding model cache on the host — seeded from the image on first run,
    # then persists across rebuilds. (Image also bakes a seed copy as fallback.)
    mkdir -p "$PROJECT_DIR/.hf-cache"

    # 确保 Postgres 运行
    cmd_ensure_postgres

    # ponytail: generate a stable ENCRYPTION_KEY for credential Fernet encryption
    # if .env doesn't have one. Persisted back so redeploys decrypt the same DB.
    if [[ -z "${ENCRYPTION_KEY:-}" ]]; then
        GENERATED_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
        echo "" >> "$PROJECT_DIR/.env"
        echo "# Auto-generated by deploy.sh — used to encrypt account_credentials" >> "$PROJECT_DIR/.env"
        echo "ENCRYPTION_KEY=$GENERATED_KEY" >> "$PROJECT_DIR/.env"
        export ENCRYPTION_KEY="$GENERATED_KEY"
        echo ">>> 已生成 ENCRYPTION_KEY 并写入 .env（请妥善保管）"
    fi

    echo ">>> 启动 Ripple CAS..."
    podman run -d \
        --name ripple-service \
        --network "$NET" \
        --restart always \
        -p 8080:8080 \
        --health-cmd "python -c \"import urllib.request,sys;sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz').status==200 else 1)\"" \
        --health-interval 15s \
        --health-timeout 3s \
        --health-retries 10 \
        --health-start-period 10s \
        -e RIPPLE_PHASE_TIMEOUT_INIT="${RIPPLE_PHASE_TIMEOUT_INIT:-300}" \
        -e RIPPLE_INIT_MERGED=true \
        -e RIPPLE_LLM_MODEL_PLATFORM="${RIPPLE_LLM_MODEL_PLATFORM:-openai}" \
        -e RIPPLE_LLM_MODEL_NAME="${RIPPLE_LLM_MODEL_NAME}" \
        -e RIPPLE_LLM_API_KEY="${RIPPLE_LLM_API_KEY}" \
        -e RIPPLE_LLM_URL="${RIPPLE_LLM_URL:-}" \
        "$RIPPLE_IMG"

    echo ">>> 等待 Ripple 就绪..."
    for i in $(seq 1 15); do
        if curl -sf http://localhost:8080/healthz >/dev/null 2>&1; then
            echo "  Ripple 已就绪 (${i}s)"
            break
        fi
        sleep 1
    done
    # Patch llm_config.yaml: add max_tokens and json_mode to prevent truncated/malformed LLM output.
    # Send it through stdin so the API key never appears in command arguments or deployment logs.
    podman exec -i ripple-service sh -c 'cat > /app/llm_config.yaml' <<LLMEOF
_default:
  model_platform: ${RIPPLE_LLM_MODEL_PLATFORM:-openai}
  model_name: ${RIPPLE_LLM_MODEL_NAME:-}
  api_key: ${RIPPLE_LLM_API_KEY:-}
  temperature: 0.7
  max_retries: 3
  url: ${RIPPLE_LLM_URL:-}
  max_tokens: 8192
  json_mode: true
_providers:
  topology:
    impl: synthetic
    model: ba
    n: 100
    seed: 42
LLMEOF
    echo "  Ripple LLM config written (credentials redacted)"

    echo ">>> 启动 XhsGrowthAgent 后端..."
    podman run -d \
        --name xhs-growth \
        --network "$NET" \
        --restart always \
        -p 8889:8889 \
        -e ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-}" \
        -e OPENAI_API_KEY="${OPENAI_API_KEY:-}" \
        -e DEEPSEEK_API_KEY="${DEEPSEEK_API_KEY:-}" \
        -e DASHSCOPE_API_KEY="${DASHSCOPE_API_KEY:-}" \
        -e XIAOMIMIMO_API_KEY="${XIAOMIMIMO_API_KEY:-}" \
        -e XIAOMIMIMO_BASE_URL="${XIAOMIMIMO_BASE_URL:-}" \
        -e XUNFEI_API_KEY="${XUNFEI_API_KEY:-}" \
        -e XUNFEI_BASE_URL="${XUNFEI_BASE_URL:-}" \
        -e XHS_EMBED_MODEL="${XHS_EMBED_MODEL:-}" \
        -e XHS_EMBED_DIMS="${XHS_EMBED_DIMS:-}" \
        -e XHS_EMBED_BASE_URL="${XHS_EMBED_BASE_URL:-}" \
        -e HF_HOME=/opt/hf-cache \
        -e HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}" \
        -e XHS_USE_BROWSER="${XHS_USE_BROWSER:-false}" \
        -e XHS_CHROME_PROFILES_DIR="${XHS_CHROME_PROFILES_DIR:-$PROJECT_DIR/.chrome-profiles}" \
        -e XHS_CDP_BASE_PORT="${XHS_CDP_BASE_PORT:-9222}" \
        -e CREATOR_STATS_SYNC_INTERVAL_HOURS="${CREATOR_STATS_SYNC_INTERVAL_HOURS:-6}" \
        -e RIPPLE_BASE_URL=http://ripple-service:8080 \
        -e RIPPLE_API_TOKEN="${RIPPLE_API_TOKEN:-}" \
        -e RIPPLE_ENABLED=true \
        -e RIPPLE_DEFAULT_MAX_WAVES="${RIPPLE_DEFAULT_MAX_WAVES:-3}" \
        -e RIPPLE_DEFAULT_SIMULATION_HORIZON="${RIPPLE_DEFAULT_SIMULATION_HORIZON:-12h}" \
        -e RIPPLE_MAX_WAVES="${RIPPLE_MAX_WAVES:-3}" \
        -e RIPPLE_SIMULATION_HORIZON="${RIPPLE_SIMULATION_HORIZON:-12h}" \
        -e RIPPLE_ENSEMBLE_RUNS="${RIPPLE_ENSEMBLE_RUNS:-1}" \
        -e RIPPLE_REQUEST_TIMEOUT="${RIPPLE_REQUEST_TIMEOUT:-300}" \
        -e RIPPLE_WORKFLOW_TIMEOUT="${RIPPLE_WORKFLOW_TIMEOUT:-1800}" \
        -e RIPPLE_PHASE_TIMEOUT_INIT="${RIPPLE_PHASE_TIMEOUT_INIT:-300}" \
        -e RIPPLE_LLM_MODEL_PLATFORM="${RIPPLE_LLM_MODEL_PLATFORM:-openai}" \
        -e RIPPLE_LLM_MODEL_NAME="${RIPPLE_LLM_MODEL_NAME:-}" \
        -e RIPPLE_LLM_API_KEY="${RIPPLE_LLM_API_KEY:-}" \
        -e RIPPLE_LLM_URL="${RIPPLE_LLM_URL:-}" \
        -e POSTGRES_URI="${POSTGRES_URI:-postgresql://xhs:xhs@postgres-xhs:5432/xhs_growth}" \
        -e ENCRYPTION_KEY="${ENCRYPTION_KEY}" \
        -e TAVILY_API_KEY="${TAVILY_API_KEY:-}" \
        -e REDIS_URI="${REDIS_URI:-redis://redis:6379/0}" \
        -e OMP_CWD="${OMP_CWD:-/app}" \
        -v "$PROJECT_DIR/frontend/dist:/app/frontend/dist:ro" \
        -v "$PROJECT_DIR/.hf-cache:/opt/hf-cache" \
        "$BACKEND_IMG"

    wait_for_backend

    echo ">>> 所有服务已启动"
    cmd_status
}

cmd_restart() {
    cmd_stop
    cmd_start
}

cmd_status() {
    echo ">>> 服务状态:"
    podman ps -a --filter name=xhs-growth --filter name=ripple-service --filter name=postgres-xhs --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
    echo ""
    echo ">>> 健康检查:"
    curl -s http://localhost:8889/api/system/health 2>/dev/null | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)['data']['checks']
    for k, v in d.items():
        status = v.get('status', '?')
        msg = v.get('message', v.get('reason', ''))
        print(f'  {k}: {status} — {msg}')
except:
    print('  后端未响应')
" || echo "  后端未响应"
    echo ""
    echo ">>> Ripple LLM config:"
    curl -s http://localhost:8080/healthz 2>/dev/null | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(f'  healthz: {d.get(\"status\")}')
except:
    print('  Ripple 未响应')
" || echo "  Ripple 未响应"
}

cmd_deploy() {
    # 部署前自动备份
    if podman ps --filter name=postgres-xhs --format '{{.Names}}' | grep -q postgres-xhs; then
        echo ">>> 部署前自动备份..."
        cmd_backup
    fi

    # Frontend: skip rebuild when no source is newer than dist/ (saves ~20s).
    # Set FORCE_FRONTEND=1 to always rebuild.
    if [ "${FORCE_FRONTEND:-}" = "1" ]; then
        cmd_frontend
    elif [ -d "$PROJECT_DIR/frontend/dist" ]; then
        NEWEST_DIST=$(find "$PROJECT_DIR/frontend/dist" -type f -printf '%T@\n' 2>/dev/null | sort -rn | head -1)
        NEWEST_SRC=$(find "$PROJECT_DIR/frontend/src" "$PROJECT_DIR/frontend/index.html" "$PROJECT_DIR/frontend/package.json" "$PROJECT_DIR/frontend/vite.config.ts" -type f -newermt "@0" -printf '%T@\n' 2>/dev/null | sort -rn | head -1)
        if [ -n "$NEWEST_SRC" ] && [ -n "$NEWEST_DIST" ] && [ "$(printf '%s\n' "$NEWEST_SRC" "$NEWEST_DIST" | sort -rn | head -1)" = "$NEWEST_DIST" ]; then
            echo ">>> 前端源码未变更，跳过构建"
        else
            cmd_frontend
        fi
    else
        cmd_frontend
    fi

    # ponytail: skip image rebuild when only frontend changed — saves ~60s
    # Set SKIP_REBUILD=1 to force skip; auto-detects via .py mtime vs image creation
    REBUILT=0
    if [ "${SKIP_REBUILD:-}" = "1" ]; then
        echo ">>> 跳过镜像构建（SKIP_REBUILD=1）"
    elif ! podman image exists "$BACKEND_IMG" 2>/dev/null; then
        echo ">>> 镜像不存在，首次构建..."
        podman build -t "$BACKEND_IMG" "$PROJECT_DIR"
        REBUILT=1
    else
        IMAGE_TS=$(podman inspect "$BACKEND_IMG" --format '{{.Created}}' 2>/dev/null)
        CHANGED=""
        if [ -n "$IMAGE_TS" ]; then
            CHANGED=$(find "$PROJECT_DIR/backend" -name "*.py" -newermt "$(echo "$IMAGE_TS" | cut -d. -f1)" -type f 2>/dev/null | head -1)
        fi
        if [ -n "$CHANGED" ]; then
            echo ">>> 检测到后端代码变更（$(basename "$CHANGED")），重建镜像..."
            podman build -t "$BACKEND_IMG" "$PROJECT_DIR"
            REBUILT=1
        else
            echo ">>> 后端代码未变更，跳过镜像构建"
        fi
    fi

    # When the image was rebuilt, `podman restart` is WRONG — it reuses the old
    # container's filesystem layers, so new backend code never takes effect.
    # Must stop+rm+run to pick up the new image. Only restart when the image is
    # unchanged (frontend-dist-only deploys, where dist is a bind mount).
    if podman ps -a --filter name=xhs-growth --format '{{.Names}}' | grep -q xhs-growth; then
        if [ "$REBUILT" = "1" ]; then
            echo ">>> 镜像已重建，重新创建容器以加载新代码..."
            podman stop xhs-growth 2>/dev/null || true
            podman rm   xhs-growth 2>/dev/null || true
            podman stop ripple-service 2>/dev/null || true
            podman rm   ripple-service 2>/dev/null || true
            cmd_start
            return
        else
            echo ">>> 镜像未变更，重启容器（加载新前端 dist）..."
            podman restart xhs-growth
            podman restart ripple-service 2>/dev/null || true
        fi
    else
        cmd_start
        return
    fi

    wait_for_backend

    echo ">>> 部署完成"
    cmd_status
}

# ── 入口 ──

CMD="${1:-status}"

case "$CMD" in
    rebuild) cmd_rebuild ;;
    deploy)  cmd_deploy ;;
    start)   cmd_start ;;
    stop)    cmd_stop ;;
    restart) cmd_restart ;;
    status)  cmd_status ;;
    backup)  cmd_backup ;;
    restore) cmd_restore ;;
    *)
        echo "用法: $0 [rebuild|deploy|start|stop|restart|status|backup|restore]"
        echo ""
        echo "  rebuild  — 构建前端 + 重新构建后端镜像"
        echo "  deploy   — 备份数据 + 构建前端 + 重建镜像 + 重启服务（安全一键部署）"
        echo "  start    — 启动所有服务（Postgres + Ripple + 后端）"
        echo "  stop     — 停止后端和 Ripple（Postgres 保持运行）"
        echo "  restart  — 停止 + 重新启动"
        echo "  status   — 查看服务状态和健康检查"
        echo "  backup   — 备份 Postgres 数据到 .backups/（保留最近 5 个）"
        echo "  restore  — 从最近备份恢复 Postgres 数据"
        exit 1
        ;;
esac
