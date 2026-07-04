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

cd "$PROJECT_DIR"

# Forward all args (subcommand + flags like --headless) to the python CLI.
exec python3 -m backend.services.chrome_launcher "$@"
