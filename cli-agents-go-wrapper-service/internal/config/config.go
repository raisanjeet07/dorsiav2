// Package config provides configuration loading for the gateway service.
package config

import (
	"encoding/json"
	"os"
	"strconv"
)

// Config holds all service configuration.
type Config struct {
	// Server settings.
	Server ServerConfig `json:"server"`

	// Agent-specific defaults.
	Agents map[string]AgentConfig `json:"agents,omitempty"`
}

// ServerConfig configures the HTTP/WS server.
type ServerConfig struct {
	// Host to bind to (default: "0.0.0.0").
	Host string `json:"host"`

	// Port to listen on (default: 8080).
	Port int `json:"port"`

	// AllowedOrigins for CORS/WebSocket origin checking.
	AllowedOrigins []string `json:"allowedOrigins,omitempty"`
}

// AgentConfig holds defaults for a specific agent type.
type AgentConfig struct {
	// Command overrides the default binary name.
	Command string `json:"command,omitempty"`

	// DefaultModel sets the model if none specified by the client.
	DefaultModel string `json:"defaultModel,omitempty"`

	// Models is the list of model IDs advertised by GET /agents/{agent}/models.
	// When empty, adapters use their built-in defaults.
	Models []string `json:"models,omitempty"`

	// Env extra environment variables to pass.
	Env map[string]string `json:"env,omitempty"`

	// ExtraArgs appended to every spawn.
	ExtraArgs []string `json:"extraArgs,omitempty"`
}

// DefaultConfig returns a config with sensible defaults.
func DefaultConfig() *Config {
	return &Config{
		Server: ServerConfig{
			Host: "0.0.0.0",
			Port: 8080,
		},
		// No DefaultModel set — each agent chooses its own default.
		Agents: map[string]AgentConfig{
			"claude-code": {Command: "claude"},
			"cursor":      {Command: "agent"}, // gateway flow "cursor"; binary is `agent` CLI
			"gemini":      {Command: "gemini"},
		},
	}
}

// LoadFromFile loads config from a JSON file, falling back to defaults
// for any unset fields.
func LoadFromFile(path string) (*Config, error) {
	cfg := DefaultConfig()

	data, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return cfg, nil // use defaults
		}
		return nil, err
	}

	if err := json.Unmarshal(data, cfg); err != nil {
		return nil, err
	}
	return cfg, nil
}

// LoadFromEnv creates a config from environment variables.
func LoadFromEnv() *Config {
	cfg := DefaultConfig()
	ApplyEnvOverrides(cfg)
	return cfg
}

// ApplyEnvOverrides merges GATEWAY_* from the environment into cfg.
// Call after loading defaults and optional JSON file.
func ApplyEnvOverrides(cfg *Config) {
	if cfg == nil {
		return
	}
	if host := os.Getenv("GATEWAY_HOST"); host != "" {
		cfg.Server.Host = host
	}
	if port := os.Getenv("GATEWAY_PORT"); port != "" {
		if p, err := strconv.Atoi(port); err == nil && p > 0 {
			cfg.Server.Port = p
		}
	}
	// GATEWAY_WORKSPACE_FILE_SERVICE_URL is read in cmd/server (optional workspace-file-service).
}
