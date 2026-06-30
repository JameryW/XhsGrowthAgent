# Stage 1: Build frontend (skip if dist/ already exists locally)
# FROM node:22-slim AS frontend-build
# WORKDIR /app/frontend
# COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
# RUN corepack enable && pnpm install --frozen-lockfile
# COPY frontend/ ./
# RUN corepack enable && NODE_OPTIONS="--max-old-space-size=768" npx vite build

# Stage 2: Python backend + serve frontend
FROM python:3.11-slim
WORKDIR /app

# Install system deps + bun runtime + omp CLI (needed by OmpSession for agent mode TUI).
# ponytail: single apt layer; curl/unzip only for bun install, then purged.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev curl unzip \
    && curl -fsSL https://bun.sh/install | BUN_INSTALL=/usr/local bash -s "bun-v1.3.14" \
    && /usr/local/bin/bun install -g @oh-my-pi/pi-coding-agent \
    && ln -s /root/.bun/bin/omp /usr/local/bin/omp \
    && apt-get purge -y curl unzip && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

# Install torch CPU-only first (~200MB vs ~4GB CUDA), then the rest.
# sentence-transformers depends on torch; without this pre-install pip pulls
# the default CUDA build which bloats the image by ~4GB on a CPU-only host.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# uv binary — used to export a pinned requirements file from uv.lock.
RUN pip install --no-cache-dir uv

# Install THIRD-PARTY deps from uv.lock BEFORE copying backend source.
# ponytail: this layer depends only on pyproject.toml/uv.lock, so .py edits
# hit the cache and skip the multi-minute dep install on every rebuild.
# --no-emit-project skips the local pkg (no source yet); --no-dev excludes
# mypy/pytest/ruff; --no-emit-package torch keeps the CPU pre-install above.
COPY pyproject.toml uv.lock ./
RUN uv export --frozen --extra browser --no-dev --no-emit-project --no-emit-package torch --no-hashes -o /tmp/reqs.txt && \
    # Drop torch's CUDA deps (nvidia-*, cuda-*, triton) — torch itself is the
    # CPU pre-install above; these would otherwise pull ~4GB of CUDA blobs.
    grep -vE '^(nvidia-|cuda-|triton==)' /tmp/reqs.txt > /tmp/reqs_clean.txt && \
    pip install --no-cache-dir -r /tmp/reqs_clean.txt && rm /tmp/reqs.txt /tmp/reqs_clean.txt

# Backend source copied AFTER deps — .py edits only invalidate the layer below.
COPY backend/ backend/
# Install the local package itself (deps already present; --no-deps avoids
# re-resolving). hatchling is the build backend declared in pyproject.
RUN pip install --no-cache-dir hatchling && \
    pip install --no-cache-dir --no-deps ".[browser]"

# Install chromium browser + system deps for playwright real publishing.
# Baked into the image so containers don't download at runtime (no network dep).
# ponytail: ~500MB layer; acceptable — real publishing requires a real browser.
RUN playwright install --with-deps chromium

# Bake the local embedding model into the image as a SEED copy at
# /opt/hf-cache-seed. The model is COPY'd from the host .hf-cache dir (populated
# once from a successful download — build containers can't reliably reach the HF
# mirror, so we bake offline). Runtime HF_HOME is /opt/hf-cache (bind-mounted
# from host /test/xhs/.hf-cache); the entrypoint seeds the host dir from this
# copy on first run — zero runtime network dependency AND the cache persists
# visibly on the host across image rebuilds.
# ponytail: model is fixed to bge-small-zh-v1.5 — switching XHS_EMBED_MODEL to a
# different local model needs a rebuild (or a runtime download with network).
COPY .hf-cache /opt/hf-cache-seed
RUN chmod -R a+rX /opt/hf-cache-seed
ENV HF_HOME=/opt/hf-cache
ENV HF_ENDPOINT=https://hf-mirror.com

COPY scripts/container-entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Copy built frontend from local dist (built outside container to avoid OOM)
COPY frontend/dist ./frontend/dist

EXPOSE 8889

ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "backend.api.app:app", "--host", "0.0.0.0", "--port", "8889"]
