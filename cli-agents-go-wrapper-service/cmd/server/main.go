// Command server starts the CLI Agent Gateway — a WebSocket service that
// provides a unified protocol for UIs to communicate with any CLI coding agent.
//
// Usage:
//
//	go run ./cmd/server [--config path/to/config.json] [--port 8080] [--log-file path]
package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	"strings"
	"syscall"
	"time"

	"github.com/cli-agents-go-wrapper-service/internal/agent"
	"github.com/cli-agents-go-wrapper-service/internal/agenthttp"
	"github.com/cli-agents-go-wrapper-service/internal/auth"
	"github.com/cli-agents-go-wrapper-service/internal/config"
	"github.com/cli-agents-go-wrapper-service/internal/mcp"
	"github.com/cli-agents-go-wrapper-service/internal/session"
	"github.com/cli-agents-go-wrapper-service/internal/skill"
	"github.com/cli-agents-go-wrapper-service/internal/workspacefile"
	"github.com/cli-agents-go-wrapper-service/internal/ws"

	// Import adapters so their init() functions register them.
	_ "github.com/cli-agents-go-wrapper-service/internal/agent/claudecode"
	_ "github.com/cli-agents-go-wrapper-service/internal/agent/cursor"
	_ "github.com/cli-agents-go-wrapper-service/internal/agent/gemini"
)

func main() {
	var (
		configPath = flag.String("config", "", "path to config JSON file")
		port         = flag.Int("port", 0, "override server port")
		logFile      = flag.String("log-file", "", "append JSON logs to this file (also stdout); default from $GATEWAY_LOG_FILE")
	)
	flag.Parse()

	logPath := strings.TrimSpace(*logFile)
	if logPath == "" {
		logPath = strings.TrimSpace(os.Getenv("GATEWAY_LOG_FILE"))
	}
	logger, closeLog := newJSONLogger(logPath)
	defer closeLog()
	slog.SetDefault(logger)

	// Load configuration.
	cfg := config.DefaultConfig()
	if *configPath != "" {
		var err error
		cfg, err = config.LoadFromFile(*configPath)
		if err != nil {
			logger.Error("failed to load config", "path", *configPath, "error", err)
			os.Exit(1)
		}
	}
	config.ApplyEnvOverrides(cfg)
	if *port > 0 {
		cfg.Server.Port = *port
	}
	if logPath != "" {
		logger.Info("logging to file (and stdout)", "path", logPath)
	}

	// Log registered adapters.
	logger.Info("registered agent adapters", "adapters", agent.RegisteredAdapters())

	// Create session manager.
	sessMgr := session.NewManager(logger)

	// Create global skill and MCP registries.
	skillReg := skill.NewRegistry()
	mcpReg := mcp.NewRegistry()

	// Create auth manager (caches per-agent login state).
	authMgr := auth.NewManager()

	var wsFile *workspacefile.Client
	u := strings.TrimSpace(os.Getenv("GATEWAY_WORKSPACE_FILE_SERVICE_URL"))
	// Explicit opt-out: do not call workspace-file-service (use client workingDir only).
	if strings.EqualFold(u, "none") || strings.EqualFold(u, "off") || u == "0" {
		u = ""
	}
	if u != "" {
		wsFile = workspacefile.NewClient(u)
		logger.Info("workspace-file-service integration enabled", "url", u)
	} else {
		logger.Warn("GATEWAY_WORKSPACE_FILE_SERVICE_URL not set (or disabled); per-session workspace provisioning off — agent uses client workingDir only. Set to http://localhost:8090 for local workspace-file-service.")
	}

	// Create WebSocket hub.
	hub := ws.NewHub(sessMgr, skillReg, mcpReg, authMgr, logger, wsFile)

	// Set up HTTP routes.
	mux := http.NewServeMux()

	// WebSocket endpoint.
	mux.HandleFunc("/ws", hub.ServeHTTP)

	// Health check.
	mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		fmt.Fprintf(w, `{"status":"ok","time":"%s"}`,
			time.Now().UTC().Format(time.RFC3339))
	})

	// ── Agent authentication --------------------------------------------------
	mux.HandleFunc("/agents/{agent}/auth", agenthttp.HandleAgentAuth(authMgr))
	mux.HandleFunc("POST /agents/{agent}/auth/login", agenthttp.HandleAgentAuthLogin(authMgr))

	// ── Agent models & modes --------------------------------------------------
	mux.HandleFunc("GET /agents/{agent}/models", agenthttp.HandleAgentModels(cfg))
	mux.HandleFunc("GET /agents/{agent}/modes", agenthttp.HandleAgentModes)

	// ── Global skill registry ------------------------------------------------
	mux.HandleFunc("/skills", agenthttp.HandleSkills(skillReg))
	mux.HandleFunc("/skills/{name}", agenthttp.HandleSkillByName(skillReg))
	mux.HandleFunc("/agents/{agent}/skills", agenthttp.HandleAgentSkills(skillReg))

	// ── Global MCP registry --------------------------------------------------
	mux.HandleFunc("/mcps", agenthttp.HandleMCPs(mcpReg))
	mux.HandleFunc("/mcps/{name}", agenthttp.HandleMCPByName(mcpReg))
	mux.HandleFunc("/agents/{agent}/mcps", agenthttp.HandleAgentMCPs(mcpReg))

	// ── Session-level attachment (attach/detach skills and MCPs at runtime) --
	mux.HandleFunc("/sessions/{sessionId}/skills", agenthttp.HandleSessionSkills(sessMgr, skillReg))
	mux.HandleFunc("/sessions/{sessionId}/skills/{skillName}", agenthttp.HandleSessionSkills(sessMgr, skillReg))
	mux.HandleFunc("/sessions/{sessionId}/mcps", agenthttp.HandleSessionMCPs(sessMgr, mcpReg))
	mux.HandleFunc("/sessions/{sessionId}/mcps/{mcpName}", agenthttp.HandleSessionMCPs(sessMgr, mcpReg))

	// ── List registered adapters with capabilities ---------------------------
	mux.HandleFunc("/adapters", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		adapters := agent.RegisteredAdapters()
		caps := make([]map[string]any, 0, len(adapters))
		for _, name := range adapters {
			a, err := agent.NewAdapter(name)
			if err != nil {
				continue
			}
			c := a.Capabilities()
			caps = append(caps, map[string]any{
				"name":         name,
				"capabilities": c,
			})
		}
		data, _ := json.Marshal(caps)
		_, _ = w.Write(data)
	})

	addr := fmt.Sprintf("%s:%d", cfg.Server.Host, cfg.Server.Port)
	server := &http.Server{
		Addr:         addr,
		Handler:      mux,
		ReadTimeout:  15 * time.Second,
		WriteTimeout: 15 * time.Second,
		IdleTimeout:  60 * time.Second,
	}

	// Graceful shutdown.
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	go func() {
		logger.Info("gateway server starting", "addr", addr)
		if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			logger.Error("server error", "error", err)
			os.Exit(1)
		}
	}()

	<-ctx.Done()
	logger.Info("shutting down...")

	// Stop all sessions.
	sessMgr.StopAll()

	shutdownCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if err := server.Shutdown(shutdownCtx); err != nil {
		logger.Error("shutdown error", "error", err)
	}

	logger.Info("gateway stopped")
}

// newJSONLogger writes structured JSON logs to stdout, and optionally also appends to path.
func newJSONLogger(path string) (*slog.Logger, func()) {
	cleanup := func() {}
	var w io.Writer = os.Stdout
	if path != "" {
		dir := filepath.Dir(path)
		if dir != "." && dir != "" {
			if err := os.MkdirAll(dir, 0755); err != nil {
				fmt.Fprintf(os.Stderr, "gateway: mkdir log dir: %v\n", err)
				os.Exit(1)
			}
		}
		f, err := os.OpenFile(path, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0644)
		if err != nil {
			fmt.Fprintf(os.Stderr, "gateway: open log file: %v\n", err)
			os.Exit(1)
		}
		w = io.MultiWriter(os.Stdout, f)
		cleanup = func() { _ = f.Close() }
	}
	lg := slog.New(slog.NewJSONHandler(w, &slog.HandlerOptions{Level: slog.LevelDebug}))
	return lg, cleanup
}
