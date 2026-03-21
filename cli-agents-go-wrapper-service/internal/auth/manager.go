// Package auth provides a server-wide authentication state cache for agent adapters.
//
// Each agent type (claude-code, cursor, gemini, …) has its own login state.
// Once an adapter confirms it is logged in, the result is cached in memory so
// that subsequent session creates do not trigger a redundant CLI check.
//
// Cache invalidation:
//   - Explicit call to Invalidate(agentName) — e.g. from DELETE /agents/{agent}/auth
//   - Server restart (state is in-memory only)
//
// The zero value is not usable — use NewManager().
package auth

import (
	"context"
	"fmt"
	"sync"
	"time"

	"github.com/cli-agents-go-wrapper-service/internal/agent"
)

// ErrAuthRequired is a sentinel that callers can check with errors.Is.
// It wraps the agent name and the login URL when available.
type ErrAuthRequired struct {
	AgentName string
	LoginURL  string
}

func (e *ErrAuthRequired) Error() string {
	if e.LoginURL != "" {
		return fmt.Sprintf("AUTH_REQUIRED: agent %q is not logged in; visit %s", e.AgentName, e.LoginURL)
	}
	return fmt.Sprintf("AUTH_REQUIRED: agent %q is not logged in; call POST /agents/%s/auth/login", e.AgentName, e.AgentName)
}

// entry caches the authentication state for one agent type.
type entry struct {
	loggedIn  bool
	detail    string
	checkedAt time.Time
}

// Manager caches per-agent authentication state.
type Manager struct {
	mu    sync.RWMutex
	cache map[string]*entry // keyed by agent name
}

// NewManager creates an auth Manager.
func NewManager() *Manager {
	return &Manager{cache: make(map[string]*entry)}
}

// Status returns the cached auth state for an agent. ok is false if the state
// has never been checked (no cache entry).
func (m *Manager) Status(agentName string) (loggedIn bool, detail string, checkedAt time.Time, ok bool) {
	m.mu.RLock()
	e, exists := m.cache[agentName]
	m.mu.RUnlock()
	if !exists {
		return false, "", time.Time{}, false
	}
	return e.loggedIn, e.detail, e.checkedAt, true
}

// SetStatus stores an auth result directly (used after an explicit check or login).
func (m *Manager) SetStatus(agentName string, loggedIn bool, detail string) {
	m.mu.Lock()
	m.cache[agentName] = &entry{loggedIn: loggedIn, detail: detail, checkedAt: time.Now().UTC()}
	m.mu.Unlock()
}

// Invalidate removes the cached state for an agent, forcing a fresh check next time.
func (m *Manager) Invalidate(agentName string) {
	m.mu.Lock()
	delete(m.cache, agentName)
	m.mu.Unlock()
}

// EnsureAuth checks whether the given adapter is authenticated, using the cache
// when available.
//
//   - If the adapter does not implement Authenticator, auth is considered not
//     required and EnsureAuth returns nil immediately.
//   - If the cached state says logged-in, returns nil immediately.
//   - Otherwise runs CheckAuth. If not logged in, attempts to start a Login flow
//     and returns *ErrAuthRequired containing the browser URL.
func (m *Manager) EnsureAuth(ctx context.Context, agentName string, a agent.Adapter) error {
	auth, ok := agent.AsAuthenticator(a)
	if !ok {
		// Agent does not require authentication.
		return nil
	}

	// Check cache first.
	m.mu.RLock()
	e, exists := m.cache[agentName]
	m.mu.RUnlock()
	if exists && e.loggedIn {
		return nil
	}

	// Run the live check.
	status, err := auth.CheckAuth(ctx)
	if err != nil {
		return fmt.Errorf("check auth for %q: %w", agentName, err)
	}
	m.SetStatus(agentName, status.LoggedIn, status.Detail)

	if status.LoggedIn {
		return nil
	}

	// Not logged in — start a login flow to get the URL for the client.
	flow, err := auth.Login(ctx)
	if err != nil {
		return &ErrAuthRequired{AgentName: agentName}
	}
	return &ErrAuthRequired{AgentName: agentName, LoginURL: flow.URL}
}
