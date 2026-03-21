package cursor

import (
	"bytes"
	"context"
	"fmt"
	"os/exec"
	"strings"

	"github.com/cli-agents-go-wrapper-service/internal/agent"
	"github.com/cli-agents-go-wrapper-service/internal/process"
)

// CheckAuth runs `agent status` and reports whether the user is logged in.
// Exit 0 + "Logged in" text → logged in.
func (a *Adapter) CheckAuth(ctx context.Context) (*agent.AuthStatus, error) {
	cmd := exec.CommandContext(ctx, "agent", "status")
	var out bytes.Buffer
	cmd.Stdout = &out
	cmd.Stderr = &out

	if err := cmd.Start(); err != nil {
		return nil, err
	}
	process.LogSpawned(cmd)
	err := cmd.Wait()
	combined := ansiEscape.ReplaceAllString(out.String(), "")

	if err != nil {
		return &agent.AuthStatus{LoggedIn: false, Detail: strings.TrimSpace(combined)}, nil
	}

	loggedIn := strings.Contains(combined, "Logged in")
	detail := strings.TrimSpace(combined)
	return &agent.AuthStatus{LoggedIn: loggedIn, Detail: detail}, nil
}

// Login runs `agent login` with NO_OPEN_BROWSER=1 and returns a URL for the
// user to open manually, mirroring the claude-code and gemini auth flow.
func (a *Adapter) Login(ctx context.Context) (*agent.LoginFlow, error) {
	cmd := exec.CommandContext(ctx, "agent", "login")
	cmd.Env = append(cmd.Environ(), "NO_OPEN_BROWSER=1")

	var out bytes.Buffer
	cmd.Stdout = &out
	cmd.Stderr = &out

	done := make(chan error, 1)
	if err := cmd.Start(); err != nil {
		return nil, fmt.Errorf("start agent login: %w", err)
	}
	process.LogSpawned(cmd)

	doneCh := make(chan error, 1)
	go func() {
		err := cmd.Wait()
		doneCh <- err
	}()

	// Scan output for the login URL.
	url := extractCursorURL(out.String())
	if url == "" {
		// Give the process a moment to emit the URL then scan again.
		// (agent login writes the URL quickly before waiting for browser.)
		select {
		case <-ctx.Done():
			_ = cmd.Process.Kill()
			return nil, ctx.Err()
		case err := <-doneCh:
			url = extractCursorURL(out.String())
			if url == "" {
				return nil, fmt.Errorf("agent login did not emit a URL: %w", err)
			}
			close(done)
			return &agent.LoginFlow{URL: url, Done: doneCh}, nil
		}
	}

	return &agent.LoginFlow{URL: url, Done: doneCh}, nil
}

func extractCursorURL(text string) string {
	clean := ansiEscape.ReplaceAllString(text, "")
	for _, line := range strings.Split(clean, "\n") {
		if idx := strings.Index(line, "https://"); idx >= 0 {
			url := line[idx:]
			if sp := strings.IndexAny(url, " \t\r"); sp > 0 {
				url = url[:sp]
			}
			return strings.TrimSpace(url)
		}
	}
	return ""
}
