# Dorsia — Build & Run
#
# Docker usage:
#   make up       # Build everything and start all services in Docker
#   make down     # Stop all services (keep data)
#   make clean    # Stop all services and wipe volumes
#   make logs     # Tail logs from all services
#   make ps       # Show running containers
#
# Local usage (services on host, Postgres in Docker):
#   make local-setup    # One-time: create venvs and install deps
#   make local-up       # Start everything (infra + all services)
#   make local-down     # Stop everything
#   make local-status   # Show what's running
#   make local-logs     # Tail all service logs

-include .env
export

.PHONY: up down clean logs ps build-base build \
        local-setup local-infra local-up local-down local-status local-logs \
        local-gateway local-caps local-research local-stop-services \
        local-restart kill-claude

# ── Docker (full-stack) ──────────────────────────────────────────────────────

## Build the dev base image (prerequisite for the gateway)
build-base:
	docker build -t agent-cli-dev-base:test ./agent-cli-dev-base-docker

## Build all service images (base image first)
build: build-base
	docker compose build

## Build (if needed) and start all services
up: build-base
	docker compose up --build -d

## Start without rebuilding
start:
	docker compose up -d

## Stop all services (volumes preserved)
down:
	docker compose down

## Stop all services and remove all volumes (destructive)
clean:
	docker compose down -v

## Tail logs from all services
logs:
	docker compose logs -f

## Show running containers and health status
ps:
	docker compose ps

# ── Local Development (services on host, infra in Docker) ────────────────────

LOCAL_LOG_DIR := .local/logs
LOCAL_PID_DIR := .local/pids
GATEWAY_BIN  := cli-agents-go-wrapper-service/bin/cli-agent-gateway

## One-time setup: create Python venvs and install all dependencies
local-setup:
	@echo "==> Setting up Capability Service..."
	cd ai-capability-skills-agent-persona && python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
	@echo ""
	@echo "==> Setting up Research Workflow..."
	cd research-work-flow-ai && python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
	@echo ""
	@echo "==> Building Go Gateway..."
	cd cli-agents-go-wrapper-service && go build -ldflags="-s -w" -o bin/cli-agent-gateway ./cmd/server
	@echo ""
	@echo "==> Setup complete. Run 'make local-up' to start all services."

## Start PostgreSQL in Docker
local-infra:
	@docker compose -f docker-compose.infra.yml up -d
	@echo "Waiting for PostgreSQL..."
	@until docker compose -f docker-compose.infra.yml exec -T postgres pg_isready -U $${POSTGRES_USER:-postgres} > /dev/null 2>&1; do sleep 1; done
	@echo "PostgreSQL ready on localhost:5432"

## Start all services locally (Postgres in Docker, apps on host)
local-up: local-infra
	@mkdir -p $(LOCAL_LOG_DIR) $(LOCAL_PID_DIR) workspace
	@# -- Gateway --
	@if [ -f $(LOCAL_PID_DIR)/gateway.pid ] && kill -0 $$(cat $(LOCAL_PID_DIR)/gateway.pid) 2>/dev/null; then \
		echo "Gateway already running (PID $$(cat $(LOCAL_PID_DIR)/gateway.pid))"; \
	else \
		echo "Starting Gateway on :8080..."; \
		cd cli-agents-go-wrapper-service && \
			GEMINI_API_KEY="$${GOOGLE_API_KEY}" \
			GATEWAY_WORKSPACE_FILE_SERVICE_URL="$${GATEWAY_WORKSPACE_FILE_SERVICE_URL:-http://localhost:8090}" \
			go run ./cmd/server --port 8080 \
			> ../$(LOCAL_LOG_DIR)/gateway.log 2>&1 & echo $$! > ../$(LOCAL_PID_DIR)/gateway.pid; \
		sleep 3; \
		if curl -sf http://localhost:8080/health > /dev/null 2>&1; then \
			echo "  Gateway healthy ✓"; \
		else \
			echo "  Gateway starting (check logs: $(LOCAL_LOG_DIR)/gateway.log)"; \
		fi; \
	fi
	@# -- Capability Service --
	@if [ -f $(LOCAL_PID_DIR)/capability-service.pid ] && kill -0 $$(cat $(LOCAL_PID_DIR)/capability-service.pid) 2>/dev/null; then \
		echo "Capability Service already running (PID $$(cat $(LOCAL_PID_DIR)/capability-service.pid))"; \
	else \
		echo "Starting Capability Service on :8100..."; \
		cd ai-capability-skills-agent-persona && \
			CAPS_GATEWAY_HTTP_URL=http://localhost:8080 \
			.venv/bin/python -m src.main \
			> ../$(LOCAL_LOG_DIR)/capability-service.log 2>&1 & echo $$! > ../$(LOCAL_PID_DIR)/capability-service.pid; \
		sleep 3; \
		if curl -sf http://localhost:8100/api/v1/health > /dev/null 2>&1; then \
			echo "  Capability Service healthy ✓"; \
		else \
			echo "  Capability Service starting (check logs: $(LOCAL_LOG_DIR)/capability-service.log)"; \
		fi; \
	fi
	@# -- Research Workflow --
	@if [ -f $(LOCAL_PID_DIR)/research-workflow.pid ] && kill -0 $$(cat $(LOCAL_PID_DIR)/research-workflow.pid) 2>/dev/null; then \
		echo "Research Workflow already running (PID $$(cat $(LOCAL_PID_DIR)/research-workflow.pid))"; \
	else \
		echo "Starting Research Workflow on :8000..."; \
		cd research-work-flow-ai && \
			RESEARCH_DATABASE_URL="postgresql+asyncpg://$${POSTGRES_USER:-postgres}:$${POSTGRES_PASSWORD:-postgres}@localhost:5432/$${POSTGRES_DB:-research_workflows}" \
			RESEARCH_GATEWAY_WS_URL="ws://localhost:8080/ws" \
			RESEARCH_GATEWAY_HTTP_URL="http://localhost:8080" \
			RESEARCH_CAPABILITY_SERVICE_URL="http://localhost:8100" \
			RESEARCH_GATEWAY_AGENT_WORK_DIR="$(CURDIR)/workspace" \
			.venv/bin/python -m app.main \
			> ../$(LOCAL_LOG_DIR)/research-workflow.log 2>&1 & echo $$! > ../$(LOCAL_PID_DIR)/research-workflow.pid; \
		sleep 3; \
		if curl -sf http://localhost:8000/api/v1/health > /dev/null 2>&1; then \
			echo "  Research Workflow healthy ✓"; \
		else \
			echo "  Research Workflow starting (check logs: $(LOCAL_LOG_DIR)/research-workflow.log)"; \
		fi; \
	fi
	@echo ""
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "  Dorsia — Local Deployment"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@echo "  Gateway:            http://localhost:8080/health"
	@echo "  Capability Service: http://localhost:8100/api/v1/health"
	@echo "  Research Workflow:  http://localhost:8000/api/v1/health"
	@echo "  PostgreSQL:         localhost:5432"
	@echo ""
	@echo "  Logs:   make local-logs"
	@echo "  Status: make local-status"
	@echo "  Stop:   make local-down"
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

## Stop host services only (keep Postgres running)
local-stop-services:
	@echo "Stopping host services..."
	@for svc in research-workflow capability-service gateway; do \
		if [ -f $(LOCAL_PID_DIR)/$$svc.pid ]; then \
			pid=$$(cat $(LOCAL_PID_DIR)/$$svc.pid); \
			if kill -0 $$pid 2>/dev/null; then \
				kill $$pid 2>/dev/null; \
				echo "  Stopped $$svc (PID $$pid)"; \
			else \
				echo "  $$svc already stopped"; \
			fi; \
			rm -f $(LOCAL_PID_DIR)/$$svc.pid; \
		fi; \
	done

## Stop everything (host services + Docker infrastructure)
local-down: local-stop-services
	@echo "Stopping infrastructure..."
	@docker compose -f docker-compose.infra.yml down 2>/dev/null || true
	@echo "All stopped."

## Tail logs from all local services
local-logs:
	@tail -f $(LOCAL_LOG_DIR)/*.log

## Show status of all local services
local-status:
	@echo ""
	@echo "━━━ Host Services ━━━"
	@for svc in gateway capability-service research-workflow; do \
		if [ -f $(LOCAL_PID_DIR)/$$svc.pid ]; then \
			pid=$$(cat $(LOCAL_PID_DIR)/$$svc.pid); \
			if kill -0 $$pid 2>/dev/null; then \
				printf "  %-22s running  (PID %s)\n" "$$svc:" "$$pid"; \
			else \
				printf "  %-22s stopped  (stale PID)\n" "$$svc:"; \
			fi; \
		else \
			printf "  %-22s not started\n" "$$svc:"; \
		fi; \
	done
	@echo ""
	@echo "━━━ Infrastructure (Docker) ━━━"
	@docker compose -f docker-compose.infra.yml ps 2>/dev/null || echo "  Not running"
	@echo ""

## Run gateway in foreground (for a dedicated terminal)
local-gateway:
	cd cli-agents-go-wrapper-service && \
		GEMINI_API_KEY="$${GOOGLE_API_KEY}" \
		GATEWAY_WORKSPACE_FILE_SERVICE_URL="$${GATEWAY_WORKSPACE_FILE_SERVICE_URL:-http://localhost:8090}" \
		go run ./cmd/server --port 8080

## Best-effort: kill Claude Code CLI subprocesses (narrow patterns; macOS/Linux)
kill-claude:
	@pkill -f "@anthropic-ai/claude-code" 2>/dev/null || true
	@pkill -f "claude-code" 2>/dev/null || true
	@echo "kill-claude: done (no error if nothing matched)."

## Stop host Dorsia services and start again (Postgres container unchanged)
local-restart: local-stop-services local-up

## Run capability service in foreground (for a dedicated terminal)
local-caps:
	cd ai-capability-skills-agent-persona && \
		CAPS_GATEWAY_HTTP_URL=http://localhost:8080 \
		.venv/bin/python -m src.main

## Run research workflow in foreground (for a dedicated terminal)
local-research:
	cd research-work-flow-ai && \
		RESEARCH_DATABASE_URL="postgresql+asyncpg://$${POSTGRES_USER:-postgres}:$${POSTGRES_PASSWORD:-postgres}@localhost:5432/$${POSTGRES_DB:-research_workflows}" \
		RESEARCH_GATEWAY_WS_URL="ws://localhost:8080/ws" \
		RESEARCH_GATEWAY_HTTP_URL="http://localhost:8080" \
		RESEARCH_CAPABILITY_SERVICE_URL="http://localhost:8100" \
		RESEARCH_GATEWAY_AGENT_WORK_DIR="$(CURDIR)/workspace" \
		.venv/bin/python -m app.main
