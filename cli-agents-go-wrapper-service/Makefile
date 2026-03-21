.PHONY: build build-aw run run-dev test tidy clean build-all \
        docker-build docker-run docker-stop docker-push \
        compose-up compose-down compose-logs compose-rebuild \
        deploy deploy-local

BINARY    := cli-agent-gateway
AW_BINARY := aw
BUILD_DIR := ./bin
IMAGE     ?= cli-agent-gateway
TAG       ?= latest
PORT      ?= 8080

# ── Local build ──────────────────────────────────────────────────────────────

build:
	@echo "Building $(BINARY)..."
	go build -ldflags="-s -w" -o $(BUILD_DIR)/$(BINARY) ./cmd/server

# WebSocket CLI client for manual testing against a running gateway.
build-aw:
	@echo "Building $(AW_BINARY)..."
	go build -ldflags="-s -w" -o $(BUILD_DIR)/$(AW_BINARY) ./cmd/aw

run: build
	GATEWAY_WORKSPACE_FILE_SERVICE_URL=$${GATEWAY_WORKSPACE_FILE_SERVICE_URL:-http://localhost:8090} $(BUILD_DIR)/$(BINARY) --port $(PORT)

run-dev:
	GATEWAY_WORKSPACE_FILE_SERVICE_URL=$${GATEWAY_WORKSPACE_FILE_SERVICE_URL:-http://localhost:8090} go run ./cmd/server --port $(PORT)

test:
	go test ./... -v

tidy:
	go mod tidy

clean:
	rm -rf $(BUILD_DIR)

# Cross-compile for all platforms.
build-all:
	GOOS=darwin  GOARCH=arm64 go build -ldflags="-s -w" -o $(BUILD_DIR)/$(BINARY)-darwin-arm64  ./cmd/server
	GOOS=darwin  GOARCH=amd64 go build -ldflags="-s -w" -o $(BUILD_DIR)/$(BINARY)-darwin-amd64  ./cmd/server
	GOOS=linux   GOARCH=amd64 go build -ldflags="-s -w" -o $(BUILD_DIR)/$(BINARY)-linux-amd64   ./cmd/server
	GOOS=windows GOARCH=amd64 go build -ldflags="-s -w" -o $(BUILD_DIR)/$(BINARY)-windows-amd64.exe ./cmd/server

# ── Docker ───────────────────────────────────────────────────────────────────

docker-build:
	docker build -t $(IMAGE):$(TAG) .

# Run the container.  Pass env vars on the command line:
#   make docker-run ANTHROPIC_API_KEY=sk-ant-... GOOGLE_API_KEY=AIza...
docker-run:
	docker run --rm -d \
		--name $(BINARY) \
		-p $(PORT):8080 \
		$(if $(ANTHROPIC_API_KEY),-e ANTHROPIC_API_KEY=$(ANTHROPIC_API_KEY)) \
		$(if $(GOOGLE_API_KEY),-e GOOGLE_API_KEY=$(GOOGLE_API_KEY)) \
		$(if $(CURSOR_API_KEY),-e CURSOR_API_KEY=$(CURSOR_API_KEY)) \
		$(IMAGE):$(TAG)
	@echo "Container started → http://localhost:$(PORT)/health"

docker-stop:
	docker stop $(BINARY) 2>/dev/null || true

# Push to a registry.  Override IMAGE:
#   make docker-push IMAGE=ghcr.io/your-org/cli-agent-gateway TAG=v1.0.0
docker-push:
	docker push $(IMAGE):$(TAG)

# ── Docker Compose ────────────────────────────────────────────────────────────

# Start the gateway with docker-compose (detached).
#   make compose-up ANTHROPIC_API_KEY=sk-ant-... GOOGLE_API_KEY=AIza...
compose-up:
	ANTHROPIC_API_KEY=$(ANTHROPIC_API_KEY) \
	GOOGLE_API_KEY=$(GOOGLE_API_KEY) \
	CURSOR_API_KEY=$(CURSOR_API_KEY) \
	GATEWAY_PORT=$(PORT) \
	docker compose up -d --build
	@echo "Gateway started → http://localhost:$(PORT)/health"

compose-down:
	docker compose down

compose-logs:
	docker compose logs -f gateway

# Rebuild and restart (no cache).
compose-rebuild:
	ANTHROPIC_API_KEY=$(ANTHROPIC_API_KEY) \
	GOOGLE_API_KEY=$(GOOGLE_API_KEY) \
	CURSOR_API_KEY=$(CURSOR_API_KEY) \
	GATEWAY_PORT=$(PORT) \
	docker compose up -d --build --force-recreate
	@echo "Gateway rebuilt → http://localhost:$(PORT)/health"

# ── Deploy helpers ───────────────────────────────────────────────────────────

# Quick local deploy (build → run as background process, write PID).
deploy-local: build
	@echo "Starting $(BINARY) on port $(PORT)..."
	@$(BUILD_DIR)/$(BINARY) --port $(PORT) & echo $$! > $(BUILD_DIR)/$(BINARY).pid
	@echo "PID $$(cat $(BUILD_DIR)/$(BINARY).pid) → http://localhost:$(PORT)/health"

# Stop the local deploy.
stop-local:
	@if [ -f $(BUILD_DIR)/$(BINARY).pid ]; then \
		kill $$(cat $(BUILD_DIR)/$(BINARY).pid) && rm $(BUILD_DIR)/$(BINARY).pid && echo "Stopped."; \
	else \
		echo "No PID file found."; \
	fi

# Remote deploy via SSH.  Set DEPLOY_HOST and optionally DEPLOY_USER/DEPLOY_DIR.
#   make deploy DEPLOY_HOST=your-server.com ANTHROPIC_API_KEY=sk-ant-...
DEPLOY_HOST ?=
DEPLOY_USER ?= ubuntu
DEPLOY_DIR  ?= /opt/cli-agent-gateway

deploy: build
	@if [ -z "$(DEPLOY_HOST)" ]; then echo "DEPLOY_HOST is required"; exit 1; fi
	@echo "Deploying to $(DEPLOY_USER)@$(DEPLOY_HOST):$(DEPLOY_DIR)"
	ssh $(DEPLOY_USER)@$(DEPLOY_HOST) "mkdir -p $(DEPLOY_DIR)"
	scp $(BUILD_DIR)/$(BINARY)-linux-amd64 $(DEPLOY_USER)@$(DEPLOY_HOST):$(DEPLOY_DIR)/$(BINARY)
	scp scripts/deploy.sh $(DEPLOY_USER)@$(DEPLOY_HOST):$(DEPLOY_DIR)/deploy.sh
	ssh $(DEPLOY_USER)@$(DEPLOY_HOST) "chmod +x $(DEPLOY_DIR)/$(BINARY) $(DEPLOY_DIR)/deploy.sh"
	ssh $(DEPLOY_USER)@$(DEPLOY_HOST) \
		"ANTHROPIC_API_KEY='$(ANTHROPIC_API_KEY)' GOOGLE_API_KEY='$(GOOGLE_API_KEY)' \
		 CURSOR_API_KEY='$(CURSOR_API_KEY)' GATEWAY_PORT='$(PORT)' \
		 $(DEPLOY_DIR)/deploy.sh $(DEPLOY_DIR)/$(BINARY)"
	@echo "Deployed → http://$(DEPLOY_HOST):$(PORT)/health"
