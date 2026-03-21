package claudecode

// This file implements the agent.Authenticator interface for Claude Code.
//
// Login check: `claude auth status`
//   exit 0  → logged in
//   non-zero → not logged in
//
// Login flow: `claude auth login`
//   Reads stdout/stderr line-by-line looking for a URL (https://…) that the
//   user must open in their browser to complete the OAuth flow.

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

// CheckAuth runs `claude auth status` to determine whether the user is logged in.
func (a *Adapter) CheckAuth(ctx context.Context) (*agent.AuthStatus, error) {
	binary, err := findClaudeBinary()
	if err != nil {
		return nil, err
	}

	cmd := exec.CommandContext(ctx, binary, "auth", "status") //nolint:gosec
	var out bytes.Buffer
	cmd.Stdout = &out
	cmd.Stderr = &out
	if err := cmd.Start(); err != nil {
		return nil, err
	}
	process.LogSpawned(cmd)
	err = cmd.Wait()
	detail := strings.TrimSpace(out.String())
	if err != nil {
		return &agent.AuthStatus{LoggedIn: false, Detail: detail}, nil
	}
	return &agent.AuthStatus{LoggedIn: true, Detail: detail}, nil
}

// Login runs `claude auth login`, waits briefly for a browser URL to appear on
// stdout/stderr, then returns a LoginFlow. The Done channel receives the
// process exit error (nil = success) when the CLI finishes.
func (a *Adapter) Login(ctx context.Context) (*agent.LoginFlow, error) {
	binary, err := findClaudeBinary()
	if err != nil {
		return nil, err
	}

	cmd := exec.CommandContext(ctx, binary, "auth", "login") //nolint:gosec
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
				if u := extractURL(line); u != "" {
					urlCh <- u
					urlFound = true
				}
			}
		}
		doneCh <- cmd.Wait()
	}()

	// Wait up to the context deadline for the URL to appear.
	select {
	case url := <-urlCh:
		return &agent.LoginFlow{URL: url, Done: doneCh}, nil
	case err := <-doneCh:
		if err != nil {
			return nil, err
		}
		// Exited without emitting a URL (already logged in?).
		return &agent.LoginFlow{URL: "", Done: doneCh}, nil
	case <-ctx.Done():
		_ = cmd.Process.Kill()
		return nil, ctx.Err()
	}
}

// extractURL finds the first https:// URL in a line of text.
func extractURL(line string) string {
	idx := strings.Index(line, "https://")
	if idx == -1 {
		return ""
	}
	// Trim everything before the URL and any trailing whitespace / punctuation.
	raw := line[idx:]
	// Stop at the first whitespace character.
	if i := strings.IndexAny(raw, " \t\r\n"); i != -1 {
		raw = raw[:i]
	}
	return raw
}

// Ensure Adapter satisfies agent.Authenticator.
var _ agent.Authenticator = (*Adapter)(nil)
