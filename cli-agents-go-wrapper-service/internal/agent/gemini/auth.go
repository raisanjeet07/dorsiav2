package gemini

// This file implements the agent.Authenticator interface for Gemini CLI.
//
// Login check: `gemini auth status` (or `gemini --version` as a fallback)
//   exit 0  → logged in
//   non-zero → not logged in (or binary missing)
//
// Login flow: `gemini auth login`
//   Reads stdout/stderr looking for a https:// URL for browser-based OAuth.

import (
	"bufio"
	"bytes"
	"context"
	"io"
	"os/exec"
	"strings"

	"github.com/cli-agents-go-wrapper-service/internal/agent"
	"github.com/cli-agents-go-wrapper-service/internal/process"
)

// CheckAuth runs `gemini auth status`.
// A quota/rate-limit error (429) means the API key is valid but exhausted —
// treat that as authenticated so sessions are not blocked by ephemeral limits.
func (a *Adapter) CheckAuth(ctx context.Context) (*agent.AuthStatus, error) {
	cmd := exec.CommandContext(ctx, "gemini", "auth", "status") //nolint:gosec
	var out bytes.Buffer
	cmd.Stdout = &out
	cmd.Stderr = &out
	if err := cmd.Start(); err != nil {
		return nil, err
	}
	process.LogSpawned(cmd)
	err := cmd.Wait()
	detail := strings.TrimSpace(out.String())
	if err != nil {
		// Quota exhausted means the key is valid — don't block session creation.
		if strings.Contains(detail, "QuotaError") ||
			strings.Contains(detail, "TerminalQuotaError") ||
			strings.Contains(detail, "quota") ||
			strings.Contains(detail, "429") {
			return &agent.AuthStatus{LoggedIn: true, Detail: detail}, nil
		}
		return &agent.AuthStatus{LoggedIn: false, Detail: detail}, nil
	}
	return &agent.AuthStatus{LoggedIn: true, Detail: detail}, nil
}

// Login runs `gemini auth login` and waits for a browser URL.
func (a *Adapter) Login(ctx context.Context) (*agent.LoginFlow, error) {
	cmd := exec.CommandContext(ctx, "gemini", "auth", "login") //nolint:gosec
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return nil, err
	}
	stderr, err := cmd.StderrPipe()
	if err != nil {
		return nil, err
	}
	if err := cmd.Start(); err != nil {
		return nil, err
	}
	process.LogSpawned(cmd)

	urlCh := make(chan string, 1)
	doneCh := make(chan error, 1)

	go func() {
		scanner := bufio.NewScanner(io.MultiReader(stdout, stderr))
		urlFound := false
		for scanner.Scan() {
			line := scanner.Text()
			if !urlFound {
				if u := extractGeminiURL(line); u != "" {
					urlCh <- u
					urlFound = true
				}
			}
		}
		doneCh <- cmd.Wait()
	}()

	select {
	case url := <-urlCh:
		return &agent.LoginFlow{URL: url, Done: doneCh}, nil
	case err := <-doneCh:
		if err != nil {
			return nil, err
		}
		return &agent.LoginFlow{URL: "", Done: doneCh}, nil
	case <-ctx.Done():
		_ = cmd.Process.Kill()
		return nil, ctx.Err()
	}
}

func extractGeminiURL(line string) string {
	idx := strings.Index(line, "https://")
	if idx == -1 {
		return ""
	}
	raw := line[idx:]
	if i := strings.IndexAny(raw, " \t\r\n"); i != -1 {
		raw = raw[:i]
	}
	return raw
}

// Ensure Adapter satisfies agent.Authenticator.
var _ agent.Authenticator = (*Adapter)(nil)
