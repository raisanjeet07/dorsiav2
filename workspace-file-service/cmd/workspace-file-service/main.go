// Command workspace-file-service serves per-session workspace directories over HTTP.
package main

import (
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"os"
	"path/filepath"

	"github.com/dorsiav2/workspace-file-service/internal/api"
	"github.com/dorsiav2/workspace-file-service/internal/config"
	"github.com/dorsiav2/workspace-file-service/internal/store"
)

func main() {
	cfg := config.FromEnv()

	logPath := cfg.LogFile
	logger, logCloser := newLogger(logPath)
	if logCloser != nil {
		defer logCloser.Close()
	}
	slog.SetDefault(logger)

	st, err := store.New(cfg.WorkspaceRoot)
	if err != nil {
		logger.Error("store init failed", "error", err)
		os.Exit(1)
	}
	logger.Info("workspace root", "path", st.Root)

	srv := api.NewServer(st)
	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", srv.Health)
	mux.HandleFunc("POST /api/v1/sessions", srv.CreateSession)
	mux.HandleFunc("GET /api/v1/sessions/{sessionId}", srv.GetSession)
	mux.HandleFunc("GET /api/v1/sessions/{sessionId}/location", srv.GetSessionLocation)
	mux.HandleFunc("GET /files/", srv.ServeFiles)
	mux.HandleFunc("HEAD /files/", srv.ServeFiles)

	addr := fmt.Sprintf("%s:%d", cfg.Host, cfg.Port)
	logger.Info("listening", "addr", addr)
	if err := http.ListenAndServe(addr, mux); err != nil {
		logger.Error("server exit", "error", err)
		os.Exit(1)
	}
}

func newLogger(logPath string) (*slog.Logger, io.Closer) {
	opts := &slog.HandlerOptions{Level: slog.LevelInfo}
	if logPath == "" {
		return slog.New(slog.NewJSONHandler(os.Stdout, opts)), nil
	}
	if err := os.MkdirAll(filepath.Dir(logPath), 0o755); err != nil {
		fmt.Fprintf(os.Stderr, "mkdir log file parent: %v\n", err)
		os.Exit(1)
	}
	f, err := os.OpenFile(logPath, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644)
	if err != nil {
		fmt.Fprintf(os.Stderr, "open log file: %v\n", err)
		os.Exit(1)
	}
	mw := io.MultiWriter(os.Stdout, f)
	return slog.New(slog.NewJSONHandler(mw, opts)), f
}
