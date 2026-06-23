#!/bin/sh
set -e

# Seed the persistent HF cache (bind-mounted from host /test/xhs/.hf-cache)
# from the baked image copy on first run. Subsequent runs read the host dir directly.
if [ ! -d "$HF_HOME/hub" ]; then
    echo ">>> Seeding HF embedding cache from image seed..."
    cp -r /opt/hf-cache-seed/. "$HF_HOME"/
fi

exec "$@"
