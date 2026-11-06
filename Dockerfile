FROM python:3.11-slim

# Install system dependencies including Git
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependency specifications first for layer caching
COPY pyproject.toml README.md ./
COPY configs/ configs/

# Install dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir ".[api]"

# Copy source code
COPY src/ src/

# Install project
RUN pip install --no-cache-dir -e .

EXPOSE 8000

# Default command starts the FastAPI backend server
CMD ["uvicorn", "regression_radar.api:app", "--host", "0.0.0.0", "--port", "8000"]
