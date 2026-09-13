# ==========================================
# WLai PM Backend — Multi-stage Docker Build
# ==========================================

# Stage 1: 构建依赖
FROM python:3.11-slim AS builder

WORKDIR /build

COPY backend/requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Stage 2: 运行时
FROM python:3.11-slim AS runtime

# 安全：非 root 运行
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser

WORKDIR /app

# 复制已安装依赖
COPY --from=builder /install /usr/local

# 复制应用代码
COPY backend/app ./app
COPY backend/migrations ./migrations
COPY backend/alembic.ini ./alembic.ini
COPY backend/data/knowledge_seed ./data/knowledge_seed

# 创建数据与日志目录
RUN mkdir -p logs data/chroma_db && chown -R appuser:appuser /app

# 安装 curl 用于 HEALTHCHECK
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

ENTRYPOINT ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
