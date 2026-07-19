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
#                                       # (headless automatically when no X11)
#   scripts/chrome-profiles.sh status   # probe each account's CDP port (read-only)
#   scripts/chrome-profiles.sh stop     # SIGTERM every account's Chrome (via pidfile)
#   scripts/chrome-profiles.sh start --headless  # launch Chrome with --headless=new
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

# Host Chrome needs an X display in headed mode. In service/agent shells DISPLAY
# is often unset even though an Xvfb socket is already available, so pick one
# before the launcher starts Chrome.
if [[ -z "${DISPLAY:-}" && -d /tmp/.X11-unix ]]; then
    for socket in /tmp/.X11-unix/X99 /tmp/.X11-unix/X97 /tmp/.X11-unix/X*; do
        if [[ -S "$socket" ]]; then
            export DISPLAY=":${socket##*X}"
            break
        fi
    done
fi

# Creator Center sync only needs a CDP browser. Service shells commonly have
# no X11 display, and a headed Chrome would fail after leaving a stale
# forwarder behind. Keep headed mode for QR-login sessions when a display is
# available, but make the unattended/default path self-healing. Operators can
# override the policy with XHS_CHROME_HEADLESS=0|1 (or pass --headless).
headless_arg=0
for arg in "$@"; do
    if [[ "$arg" == "--headless" ]]; then
        headless_arg=1
        break
    fi
done

if [[ "${1:-}" == "start" && "$headless_arg" -eq 0 ]]; then
    case "${XHS_CHROME_HEADLESS:-auto}" in
        1|true|yes)
            set -- "$@" --headless
            ;;
        0|false|no)
            ;;
        auto)
            if [[ -z "${DISPLAY:-}" ]]; then
                set -- "$@" --headless
            fi
            ;;
        *)
            echo "XHS_CHROME_HEADLESS must be auto, 0, or 1" >&2
            exit 2
            ;;
    esac
fi

cd "$PROJECT_DIR"

# Forward all args (subcommand + flags like --headless) to the python CLI.
exec python3 -m backend.services.chrome_launcher "$@"
