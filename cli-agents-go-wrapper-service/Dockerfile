# ── CLI Agent Gateway ─────────────────────────────────────────────────────────
# Base image ships Go, Node.js, and all three CLI agents
# (Claude Code, Cursor CLI, Gemini CLI) pre-installed.
FROM agent-cli-dev-base:test

LABEL maintainer="cli-agent-gateway"
LABEL description="WebSocket gateway for CLI coding agents"

# ── Build args ────────────────────────────────────────────────────────────────
ARG GATEWAY_PORT=8080

# Switch to root for the build so COPY and go build have the right permissions.
USER root

# ── Working directory for the gateway source ──────────────────────────────────
WORKDIR /app

# Copy dependency manifests first for better layer caching.
COPY go.mod go.sum ./
RUN go mod download

# Copy the full source tree and build.
COPY . .
RUN CGO_ENABLED=0 go build -ldflags="-s -w" -o /usr/local/bin/cli-agent-gateway ./cmd/server

# ── Runtime configuration ─────────────────────────────────────────────────────
# Agent API keys — pass at runtime, never bake into the image.
ENV ANTHROPIC_API_KEY=""
ENV GOOGLE_API_KEY=""
ENV CURSOR_API_KEY=""
ENV GATEWAY_HOST="0.0.0.0"
ENV GATEWAY_PORT="${GATEWAY_PORT}"

# Working directory for agent sessions (mount a volume here for persistence).
ENV AGENT_WORK_DIR="/workspace"
RUN mkdir -p /workspace && chown dev:dev /workspace

# Switch to non-root user — Claude Code refuses --dangerously-skip-permissions as root.
USER dev
WORKDIR /workspace

EXPOSE ${GATEWAY_PORT}

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD wget -qO- http://localhost:${GATEWAY_PORT}/health || exit 1

ENTRYPOINT ["cli-agent-gateway"]
