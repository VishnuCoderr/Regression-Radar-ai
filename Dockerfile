# ===========================================================================
# Stage 1: Build Frontend (React + Vite + Tailwind CSS)
# ===========================================================================
FROM node:20-alpine AS frontend-builder

WORKDIR /build/ui

# Install dependencies with npm ci for reproducible builds
COPY ui/package.json ui/package-lock.json ./
RUN npm ci

# Copy frontend source and build production bundle
COPY ui/ ./
RUN npm run build

# ===========================================================================
# Stage 2: Production Python Runtime
# ===========================================================================
FROM python:3.11-slim AS runtime

# Install Git (required for history/diff analysis) and curl (for container healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create dedicated non-root user for security
RUN groupadd -r appuser && useradd -r -g appuser -d /app appuser

WORKDIR /app

# Copy dependency specifications first for optimal layer caching
COPY pyproject.toml README.md ./
COPY configs/ configs/

# Install Python dependencies and regression-radar package
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir ".[api]" && \
    pip install --no-cache-dir -e .

# Copy backend source code and demo scenario generators
COPY src/ src/
COPY examples/ examples/

# Copy compiled React frontend assets from Stage 1
COPY --from=frontend-builder /build/ui/dist /app/ui/dist

# Set up storage and examples directories with non-root user permissions
RUN mkdir -p /app/data /app/examples && chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

ENV PORT=10000 \
    RR_HOST=0.0.0.0 \
    LOG_LEVEL=INFO \
    SERVE_STATIC_UI=true \
    STORAGE_PATH=/app/data

EXPOSE 10000

# Container healthcheck using the readiness endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:${PORT:-10000}/health/ready || exit 1

# Default entrypoint dynamically uses Render's assigned $PORT (defaults to 10000)
CMD ["sh", "-c", "uvicorn regression_radar.api:app --host 0.0.0.0 --port ${PORT:-10000} --workers 2"]
