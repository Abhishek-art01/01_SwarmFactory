# =============================================================
# Swarm Factory — Production Dockerfile
# Multi-stage build: keeps final image small
# =============================================================

# Stage 1: Frontend build
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci --silent
COPY frontend/ ./
RUN npm run build

# Stage 2: Python deps
FROM python:3.11-slim AS python-deps
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl git && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Stage 3: Final production image
FROM python:3.11-slim AS production
LABEL maintainer="Swarm Factory Team"
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl git && rm -rf /var/lib/apt/lists/*

COPY --from=python-deps /install /usr/local
COPY backend/ ./backend/
COPY main.py ./
COPY --from=frontend-builder /app/frontend/dist/ ./frontend/dist/

RUN mkdir -p ./sessions
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

EXPOSE 8000

CMD ["uvicorn", "backend.api.server:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "2", "--log-level", "info"]
