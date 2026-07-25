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
#   scripts/chrome-profiles.sh start --headless  # emergency override (NOT
#                                       # recommended: XHS risk control blocks
#                                       # headless, QR login fails with 300012)
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

# Host Chrome runs HEADED ONLY — headless Chrome is flagged by XHS risk
# control (QR login fails with 300012 / "未找到登录二维码").  Headed mode
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

# Never fall back to headless automatically.  --headless (or
# XHS_CHROME_HEADLESS=1) remains as an explicit operator override for
# emergencies, but the default path stays headed even without a display.
headless_arg=0
for arg in "$@"; do
    if [[ "$arg" == "--headless" ]]; then
        headless_arg=1
        break
    fi
done

if [[ "${1:-}" == "start" && "$headless_arg" -eq 0 ]]; then
    case "${XHS_CHROME_HEADLESS:-0}" in
        1|true|yes)
            echo ">>> 警告：显式启用 headless 模式，可能被小红书风控拦截（不推荐）" >&2
            set -- "$@" --headless
            ;;
        0|false|no|auto)
            ;;
        *)
            echo "XHS_CHROME_HEADLESS must be 0 or 1" >&2
            exit 2
            ;;
    esac
fi

cd "$PROJECT_DIR"

# Forward all args (subcommand + flags like --headless) to the python CLI.
exec python3 -m backend.services.chrome_launcher "$@"
