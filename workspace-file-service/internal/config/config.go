// Package config loads workspace-file-service settings from the environment.
package config

import (
	"os"
	"strconv"
	"strings"
)

// Config holds runtime configuration.
type Config struct {
	Host string // bind address, e.g. 0.0.0.0
	Port int

	// WorkspaceRoot is the directory under which per-session folders are created:
	//   <WorkspaceRoot>/<sessionId>/...
	WorkspaceRoot string

	// LogFile, if non-empty, receives JSON logs in addition to stdout.
	LogFile string
}

func getenv(key, def string) string {
	v := strings.TrimSpace(os.Getenv(key))
	if v == "" {
		return def
	}
	return v
}

func getenvInt(key string, def int) int {
	v := strings.TrimSpace(os.Getenv(key))
	if v == "" {
		return def
	}
	n, err := strconv.Atoi(v)
	if err != nil {
		return def
	}
	return n
}

// FromEnv loads configuration from environment variables.
//
//   WORKSPACE_FILE_HOST          (default 0.0.0.0)
//   WORKSPACE_FILE_PORT          (default 8090)
//   WORKSPACE_FILE_ROOT          (default ../dorsia-workspace when cwd is workspace-file-service; override with absolute path)
//   WORKSPACE_FILE_LOG_FILE      (optional) — append JSON logs; not under workspace root
func FromEnv() Config {
	return Config{
		Host:          getenv("WORKSPACE_FILE_HOST", "0.0.0.0"),
		Port:          getenvInt("WORKSPACE_FILE_PORT", 8090),
		WorkspaceRoot: getenv("WORKSPACE_FILE_ROOT", "../dorsia-workspace"),
		LogFile:       strings.TrimSpace(os.Getenv("WORKSPACE_FILE_LOG_FILE")),
	}
}
