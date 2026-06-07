#!/usr/bin/env bash
# deploy.sh — 容器化部署脚本 for XhsGrowthAgent
# 用法: ./scripts/deploy.sh [rebuild|start|stop|restart|status]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# 从 .env 读取配置
set -a; source "$PROJECT_DIR/.env"; set +a

NET="xhs-net"
BACKEND_IMG="localhost/xhs-growth:latest"
RIPPLE_IMG="localhost/ripple-service:local"

# ── 子命令 ──

cmd_rebuild() {
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
    echo ">>> 所有服务已停止"
}

cmd_start() {
    echo ">>> 确保 $NET 存在..."
    podman network exists "$NET" 2>/dev/null || podman network create "$NET"

    echo ">>> 启动 Ripple CAS..."
    podman run -d \
        --name ripple-service \
        --network "$NET" \
        --restart always \
        -p 8080:8080 \
        -e RIPPLE_PHASE_TIMEOUT_INIT="${RIPPLE_PHASE_TIMEOUT_INIT:-300}" \
        -e RIPPLE_INIT_MERGED=true \
        -e RIPPLE_LLM_MODEL_PLATFORM="${RIPPLE_LLM_MODEL_PLATFORM:-openai}" \
        -e RIPPLE_LLM_MODEL_NAME="${RIPPLE_LLM_MODEL_NAME}" \
        -e RIPPLE_LLM_API_KEY="${RIPPLE_LLM_API_KEY}" \
        -e RIPPLE_LLM_URL="${RIPPLE_LLM_URL:-}" \
        "$RIPPLE_IMG"

    echo ">>> 等待 Ripple 就绪..."
    sleep 3
    # Patch llm_config.yaml: add max_tokens and json_mode to prevent truncated/malformed LLM output
    podman exec ripple-service sh -c "cat > /app/llm_config.yaml <<'LLMEOF'
_default:
  model_platform: ${RIPPLE_LLM_MODEL_PLATFORM:-openai}
  model_name: ${RIPPLE_LLM_MODEL_NAME:-}
  api_key: ${RIPPLE_LLM_API_KEY:-}
  temperature: 0.7
  max_retries: 3
  url: ${RIPPLE_LLM_URL:-}
  max_tokens: 8192
  json_mode: true
LLMEOF"
    podman exec ripple-service cat /app/llm_config.yaml 2>/dev/null || echo "[warn] llm_config.yaml not found"

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
        -e XHS_COOKIE="${XHS_COOKIE:-}" \
        -e XHS_USER_ID="${XHS_USER_ID:-}" \
        -e RIPPLE_BASE_URL=http://ripple-service:8080 \
        -e RIPPLE_API_TOKEN="${RIPPLE_API_TOKEN:-}" \
        -e RIPPLE_ENABLED=true \
        -e RIPPLE_DEFAULT_MAX_WAVES="${RIPPLE_DEFAULT_MAX_WAVES:-8}" \
        -e RIPPLE_DEFAULT_SIMULATION_HORIZON="${RIPPLE_DEFAULT_SIMULATION_HORIZON:-48h}" \
        -e RIPPLE_REQUEST_TIMEOUT="${RIPPLE_REQUEST_TIMEOUT:-300}" \
        -e RIPPLE_WORKFLOW_TIMEOUT="${RIPPLE_WORKFLOW_TIMEOUT:-1800}" \
        -e RIPPLE_PHASE_TIMEOUT_INIT="${RIPPLE_PHASE_TIMEOUT_INIT:-300}" \
        -e RIPPLE_LLM_MODEL_PLATFORM="${RIPPLE_LLM_MODEL_PLATFORM:-openai}" \
        -e RIPPLE_LLM_MODEL_NAME="${RIPPLE_LLM_MODEL_NAME:-}" \
        -e RIPPLE_LLM_API_KEY="${RIPPLE_LLM_API_KEY:-}" \
        -e RIPPLE_LLM_URL="${RIPPLE_LLM_URL:-}" \
        -e POSTGRES_URI="${POSTGRES_URI:-postgresql://xhs:xhs@postgres-xhs:5432/xhs_growth}" \
        -e TAVILY_API_KEY="${TAVILY_API_KEY:-}" \
        -e REDIS_URI="${REDIS_URI:-redis://redis:6379/0}" \
        -v "$PROJECT_DIR/frontend/dist:/app/frontend/dist:ro" \
        "$BACKEND_IMG"

    echo ">>> 等待后端就绪..."
    sleep 3

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

# ── 入口 ──

CMD="${1:-status}"

case "$CMD" in
    rebuild) cmd_rebuild ;;
    start)   cmd_start ;;
    stop)    cmd_stop ;;
    restart) cmd_restart ;;
    status)  cmd_status ;;
    *)
        echo "用法: $0 [rebuild|start|stop|restart|status]"
        echo ""
        echo "  rebuild — 重新构建后端镜像"
        echo "  start   — 启动所有服务（Ripple + 后端）"
        echo "  stop    — 停止所有服务"
        echo "  restart — 停止 + 重新启动"
        echo "  status  — 查看服务状态和健康检查"
        exit 1
        ;;
esac