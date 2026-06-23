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

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps (browser extra pulls playwright for real XHS publishing)
COPY pyproject.toml uv.lock ./
COPY backend/ backend/
RUN pip install --no-cache-dir hatchling && \
    pip install --no-cache-dir ".[browser]"

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
