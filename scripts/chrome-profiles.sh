#!/usr/bin/env bash
# chrome-profiles.sh — manage N always-on per-account Chrome instances (CDP multi-profile)
#
# Thin wrapper around `python3 -m backend.services.chrome_launcher`. The python
# module owns the testable logic (port probe, stale-lock cleanup, launch/stop);
# this script just forwards the subcommand and loads .env so POSTGRES_URI is set.
#
# Usage:
#   scripts/chrome-profiles.sh start    # launch/keepalive Chrome for every
#                                       # active account with a cdp_port binding
#                                       # (always headed; auto-starts Xvfb when
#                                       # no X display exists)
#   scripts/chrome-profiles.sh status   # probe each account's CDP port (read-only)
#   scripts/chrome-profiles.sh stop     # SIGTERM every account's Chrome (via pidfile)
#
# headless 模式已完全禁止：小红书风控会拦截 headless Chrome（扫码登录 300012）。
# 传入 --headless 会直接报错退出；无 X display 时脚本自动启动 Xvfb。
#
# Runs on the HOST (Chrome lives on the host; the backend container connects to
# it via host.containers.internal:<port>). Requires POSTGRES_URI to point at the
# postgres-xhs container's published port (deploy.sh publishes 5432 on the host).
#
# See docs/deployment.md "CDP multi-profile" section for the full workflow.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Load .env so POSTGRES_URI / XHS_CHROME_PROFILES_DIR / XHS_CDP_BASE_PORT are set.
# Tolerate a missing .env (CI/scratch runs) — the python CLI degrades gracefully.
if [[ -f "$PROJECT_DIR/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$PROJECT_DIR/.env"
    set +a
fi

# This script runs on the host, while .env is also consumed by the backend
# container. The container reaches Postgres as postgres-xhs; the host reaches the
# published DB port on localhost. Normalize only that deployment hostname and
# leave explicit operator overrides untouched.
if [[ "${POSTGRES_URI:-}" == *"@postgres-xhs:"* ]]; then
    export POSTGRES_URI="${POSTGRES_URI/@postgres-xhs:/@localhost:}"
fi

# Host Chrome runs HEADED ONLY — headless Chrome is banned (XHS risk control
# blocks it: QR login fails with 300012 / "未找到登录二维码").  Headed mode
# needs an X display: in service/agent shells DISPLAY is often unset even
# though an Xvfb socket is already available, so pick one; when no X server
# exists at all, start Xvfb ourselves so headed always works unattended.
if [[ -z "${DISPLAY:-}" && -d /tmp/.X11-unix ]]; then
    for socket in /tmp/.X11-unix/X99 /tmp/.X11-unix/X97 /tmp/.X11-unix/X*; do
        if [[ -S "$socket" ]]; then
            export DISPLAY=":${socket##*X}"
            break
        fi
    done
fi

if [[ -z "${DISPLAY:-}" ]] && command -v Xvfb >/dev/null 2>&1; then
    for disp in 99 98 97 96 95; do
        if [[ ! -e "/tmp/.X11-unix/X${disp}" ]]; then
            echo ">>> 无 X display，启动 Xvfb :${disp}（headed Chrome 需要）..."
            nohup Xvfb ":${disp}" -screen 0 1920x1080x24 >"/tmp/xvfb-${disp}.log" 2>&1 &
            sleep 2
            if [[ -S "/tmp/.X11-unix/X${disp}" ]]; then
                export DISPLAY=":${disp}"
                break
            fi
        fi
    done
fi

# headless is banned outright — XHS risk control blocks headless Chrome (QR
# login fails with 300012 / "未找到登录二维码"). Reject any explicit attempt.
for arg in "$@"; do
    if [[ "$arg" == "--headless" ]]; then
        echo "错误：headless 模式已被完全禁止（小红书风控会拦截 headless Chrome，扫码登录 300012）。请使用默认 headed 模式。" >&2
        exit 2
    fi
done

cd "$PROJECT_DIR"

# Forward all args (subcommand + flags) to the python CLI.
exec python3 -m backend.services.chrome_launcher "$@"
