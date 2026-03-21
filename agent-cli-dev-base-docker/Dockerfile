# syntax=docker/dockerfile:1
# Pin the Node base image (override: docker build --build-arg NODE_VERSION=22.13.1)
ARG NODE_VERSION=22.14.0
FROM node:${NODE_VERSION}-bookworm-slim

LABEL org.opencontainers.image.description="Agent/dev base: Cursor Agent, Claude Code, Gemini CLI, Node, Go, Temurin JDK, Python (non-root dev user)"

# TARGETARCH is provided by BuildKit (amd64, arm64, …) — avoids $$/sh quoting bugs in RUN
ARG TARGETARCH
ARG GO_VERSION=1.24.1
# Optional: docker build --build-arg CLAUDE_CODE_VERSION=1.0.0 --build-arg GEMINI_CLI_VERSION=0.34.0
ARG CLAUDE_CODE_VERSION=latest
ARG GEMINI_CLI_VERSION=latest

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    ca-certificates \
    curl \
    git \
    gnupg \
    jq \
    util-linux \
    python3 \
    python3-pip \
    python3-venv \
    && rm -rf /var/lib/apt/lists/*

# Eclipse Temurin 21 (LTS) — newer than Debian's default OpenJDK 17
RUN mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://packages.adoptium.net/artifactory/api/gpg/key/public \
        | gpg --dearmor -o /etc/apt/keyrings/adoptium.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/adoptium.gpg] https://packages.adoptium.net/artifactory/deb bookworm main" \
        > /etc/apt/sources.list.d/adoptium.list \
    && apt-get update && apt-get install -y --no-install-recommends temurin-21-jdk \
    && rm -rf /var/lib/apt/lists/*

# Go from golang.org (TARGETARCH matches go.dev tarball names for amd64/arm64)
RUN curl -fsSL "https://go.dev/dl/go${GO_VERSION}.linux-${TARGETARCH}.tar.gz" -o /tmp/go.tgz \
    && rm -rf /usr/local/go \
    && tar -C /usr/local -xzf /tmp/go.tgz \
    && rm /tmp/go.tgz
ENV PATH="/usr/local/go/bin:${PATH}"

# ── Non-root user ───────────────────────────────────────────────────
# Official `node` images already reserve uid/gid 1000 (`node`). Reuse that account as `dev`.
RUN if getent passwd node >/dev/null; then \
      groupmod -n dev node \
      && usermod -l dev node \
      && mv /home/node /home/dev \
      && usermod -d /home/dev dev; \
    else \
      groupadd --gid 1000 dev \
      && useradd --uid 1000 --gid dev --shell /bin/bash --create-home dev; \
    fi

# Global npm CLIs (installed as root into /usr/local; usable by dev)
RUN npm install -g @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION} @google/gemini-cli@${GEMINI_CLI_VERSION} \
    && npm cache clean --force

RUN mkdir -p /workspace && chown dev:dev /workspace

# Copy entrypoint + verification script
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
COPY scripts/verify-agents.sh /usr/local/bin/verify-agents.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh /usr/local/bin/verify-agents.sh

# ── Switch to non-root dev user ─────────────────────────────────────
# Cursor Agent installs to ~/.local/bin (see https://cursor.com/install)
USER dev
ENV HOME=/home/dev
ENV PATH="/home/dev/.local/bin:/usr/local/go/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

# Default paths / policies (override at `docker run` / compose)
ENV WORKSPACE_ROOT=/workspace \
    AGENT_DATA_DIR=/workspace/.agent-data \
    REQUIRE_WORKSPACE_MOUNT=1 \
    REQUIRE_AGENT_DATA_MOUNT=0 \
    AUTO_LOGIN_AGENTS=1

# Pre-create agent config directories (owned by dev)
RUN mkdir -p \
    /home/dev/.claude \
    /home/dev/.gemini \
    /home/dev/.local/share/cursor-agent \
    /home/dev/.local/bin

RUN curl -fsSL https://cursor.com/install | bash \
    && ln -sf agent /home/dev/.local/bin/cursor

# Verify all tools are on PATH
RUN set -eux; \
    command -v agent; command -v cursor-agent; command -v cursor; \
    command -v node; command -v npm; command -v claude; command -v gemini; \
    command -v go; command -v java; command -v python3; command -v pip3

WORKDIR /workspace

# Login shells (e.g. `bash -l`) source `/etc/profile` and can drop image ENV PATH — restore toolchain paths.
USER root
RUN printf '%s\n' \
      'export PATH="/home/dev/.local/bin:/usr/local/go/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"' \
      >> /home/dev/.profile \
    && chown dev:dev /home/dev/.profile
USER dev

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["bash"]
