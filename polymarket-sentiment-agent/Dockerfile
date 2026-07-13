# syntax=docker/dockerfile:1.7

# ---- Stage 1: build the React frontend ------------------------------------
FROM node:20-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- Stage 2: Python runtime ---------------------------------------------
FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    FRONTEND_DIST=/app/frontend_dist \
    DATABASE_URL=sqlite:////data/doa.db

WORKDIR /app

COPY backend/requirements.txt ./
RUN pip install -r requirements.txt

COPY backend/ ./
COPY --from=web /web/dist /app/frontend_dist

# /data holds the SQLite fallback DB when DATABASE_URL is not overridden.
# Mount a volume here for persistence, or point DATABASE_URL at Postgres.
RUN mkdir -p /data
VOLUME ["/data"]

COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/app/docker-entrypoint.sh"]
