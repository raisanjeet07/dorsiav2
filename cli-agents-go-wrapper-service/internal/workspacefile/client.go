// Package workspacefile calls the workspace-file-service HTTP API to provision
// per-session directories on disk.
package workspacefile

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"
)

// Client is a thin HTTP client for workspace-file-service.
type Client struct {
	baseURL string
	http    *http.Client
}

// NewClient returns a client for the given base URL (e.g. http://localhost:8090).
// Trailing slashes are stripped.
func NewClient(baseURL string) *Client {
	base := strings.TrimRight(strings.TrimSpace(baseURL), "/")
	return &Client{
		baseURL: base,
		http: &http.Client{
			Timeout: 30 * time.Second,
		},
	}
}

// ensureResponse matches GET/POST /api/v1/sessions success body.
type ensureResponse struct {
	SessionID     string `json:"session_id"`
	WorkspacePath string `json:"workspace_path"`
	Created       bool   `json:"created"`
}

type errResponse struct {
	Error string `json:"error"`
	Code  string `json:"code"`
}

// EnsureWorkspace calls GET /api/v1/sessions/{sessionId} which ensures the directory exists
// (creates it if missing) and returns the absolute workspace_path for the agent working directory.
func (c *Client) EnsureWorkspace(ctx context.Context, sessionID string) (workspacePath string, err error) {
	if c == nil || c.baseURL == "" {
		return "", fmt.Errorf("workspacefile: client not configured")
	}
	u := c.baseURL + "/api/v1/sessions/" + url.PathEscape(sessionID)
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, u, nil)
	if err != nil {
		return "", err
	}
	resp, err := c.http.Do(req)
	if err != nil {
		return "", fmt.Errorf("workspacefile: request: %w", err)
	}
	defer resp.Body.Close()
	b, _ := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	if resp.StatusCode != http.StatusOK && resp.StatusCode != http.StatusCreated {
		var er errResponse
		_ = json.Unmarshal(b, &er)
		if er.Error != "" {
			return "", fmt.Errorf("workspacefile: %s (%d)", er.Error, resp.StatusCode)
		}
		return "", fmt.Errorf("workspacefile: unexpected status %d: %s", resp.StatusCode, strings.TrimSpace(string(b)))
	}
	var out ensureResponse
	if err := json.Unmarshal(b, &out); err != nil {
		return "", fmt.Errorf("workspacefile: decode response: %w", err)
	}
	if out.WorkspacePath == "" {
		return "", fmt.Errorf("workspacefile: empty workspace_path")
	}
	return out.WorkspacePath, nil
}
