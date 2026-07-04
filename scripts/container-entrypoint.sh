#!/bin/sh
set -e

# Seed the persistent HF cache (bind-mounted from host /test/xhs/.hf-cache)
# from the baked image copy on first run. Subsequent runs read the host dir directly.
if [ ! -d "$HF_HOME/hub" ]; then
    echo ">>> Seeding HF embedding cache from image seed..."
    cp -r /opt/hf-cache-seed/. "$HF_HOME"/
fi

# Xvfb: 虚拟 DISPLAY 给 headed Chrome（扫码登录 headless 触发 xhs 471 风控）。
# Xvfb 不存在则跳过（旧镜像无 xvfb，scan-login 会回退 headless 被风控——可接受降级）。
if command -v Xvfb >/dev/null 2>&1; then
    Xvfb :99 -screen 0 1280x720x24 -nolisten tcp >/tmp/xvfb.log 2>&1 &
    export DISPLAY=:99
    echo ">>> Xvfb started on :99 (DISPLAY=$DISPLAY)"
fi

exec "$@"
