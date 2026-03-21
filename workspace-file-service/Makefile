# Repo root: .. from this directory. Session dirs: <repo>/dorsia-workspace/<sessionId>/
REPO_ROOT := $(abspath ..)
WORKSPACE_FILE_ROOT ?= $(REPO_ROOT)/dorsia-workspace

.PHONY: run test build tidy

run:
	WORKSPACE_FILE_ROOT=$(WORKSPACE_FILE_ROOT) go run ./cmd/workspace-file-service

test:
	go test ./... -v

build:
	go build -ldflags="-s -w" -o bin/workspace-file-service ./cmd/workspace-file-service

tidy:
	go mod tidy
