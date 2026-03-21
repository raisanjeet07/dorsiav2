# Dockerfile for Research Workflow Service
FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies (explicit list avoids hatchling packaging issues)
RUN pip install --no-cache-dir \
    "fastapi>=0.115.0" \
    "uvicorn[standard]>=0.30.0" \
    "pydantic>=2.7.0" \
    "pydantic-settings>=2.3.0" \
    "sqlalchemy[asyncio]>=2.0.30" \
    "asyncpg>=0.29.0" \
    "alembic>=1.13.0" \
    "httpx>=0.27.0" \
    "websockets>=14.0" \
    "structlog>=24.2.0" \
    "python-ulid>=2.7.0"

# Copy project files
COPY pyproject.toml .
COPY app/ ./app/
COPY migrations/ ./migrations/

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/api/v1/health')" || exit 1

CMD ["python", "-m", "app.main"]
