# Stage 1: Build frontend
FROM node:22-slim AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN corepack enable && pnpm install --frozen-lockfile
COPY frontend/ ./
RUN corepack enable && pnpm build

# Stage 2: Python backend + serve frontend
FROM python:3.11-slim
WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY pyproject.toml uv.lock ./
COPY backend/ backend/
RUN pip install --no-cache-dir hatchling && \
    pip install --no-cache-dir .

# Copy built frontend into the expected path
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

EXPOSE 8889

CMD ["uvicorn", "backend.api.app:app", "--host", "0.0.0.0", "--port", "8889"]
