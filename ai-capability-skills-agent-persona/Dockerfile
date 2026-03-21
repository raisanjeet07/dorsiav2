FROM python:3.12-slim AS base

WORKDIR /app

# Install declared dependencies first (layer-cache friendly)
COPY pyproject.toml ./
RUN pip install --no-cache-dir \
    "fastapi>=0.115.0" \
    "uvicorn[standard]>=0.30.0" \
    "pydantic>=2.7.0" \
    "pydantic-settings>=2.3.0" \
    "pyyaml>=6.0.1" \
    "httpx>=0.27.0" \
    "watchdog>=4.0.0" \
    "jsonschema>=4.22.0" \
    "structlog>=24.2.0"

# Copy source code
COPY src/ src/
COPY defaults/ defaults/
COPY config/ config/

# Create extensions directory for API-persisted extensions
RUN mkdir -p config/extensions/personas config/extensions/capabilities config/extensions/agents

EXPOSE 8100

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import httpx; r = httpx.get('http://localhost:8100/api/v1/health'); assert r.status_code == 200"

CMD ["python", "-m", "src.main"]
