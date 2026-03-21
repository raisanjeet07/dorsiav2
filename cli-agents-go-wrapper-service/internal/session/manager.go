// Package session manages the lifecycle of agent sessions.
//
// Key invariants:
//   - Every session is keyed by an upstream-provided sessionID (not generated).
//   - Each session is bound to exactly one flow (agent type) on first creation.
//     This binding is immutable — requests with a mismatched flow are rejected.
//   - If the underlying agent process dies, the next request to that session
//     transparently re-spawns / reconnects using the stored StartOptions.
//   - A session is never deleted from the map on process death — only on
//     explicit session.end or StopAll. This allows auto-resume.
package session

import (
	"context"
	"fmt"
	"log/slog"
	"sync"
	"time"

	"github.com/cli-agents-go-wrapper-service/internal/agent"
	"github.com/cli-agents-go-wrapper-service/internal/protocol"
)

// Session represents one active conversation between a UI client and a CLI agent.
type Session struct {
	// ID is the upstream-provided session identifier.
	ID string

	// Flow is the agent type bound to this session (immutable after creation).
	Flow string

	// Adapter is the agent adapter for this session.
	Adapter agent.Adapter

	// Status: "running", "stopped", "error"
	Status string

	// CreatedAt is when the session was first created.
	CreatedAt time.Time

	// WorkingDir is the agent's working directory.
	WorkingDir string

	// startOpts stores the options used to start this session so we can
	// re-spawn the process on auto-resume.
	startOpts agent.StartOptions

	mu     sync.Mutex
	cancel context.CancelFunc
	ctx    context.Context

	// promptMu serializes prompt.send handling (one in-flight prompt per session).
	promptMu sync.Mutex

	muPrompt           sync.Mutex
	activePromptCancel context.CancelFunc
}

// Manager tracks all sessions and enforces routing invariants.
type Manager struct {
	mu       sync.RWMutex
	sessions map[string]*Session // keyed by upstream sessionID
	logger   *slog.Logger
}

// NewManager creates a session manager.
func NewManager(logger *slog.Logger) *Manager {
	return &Manager{
		sessions: make(map[string]*Session),
		logger:   logger,
	}
}

// Resolve is the primary entry point for the WS hub. It implements the
// core routing logic:
//
//  1. If sessionID is new → create a new session bound to flow, start the agent.
//  2. If sessionID exists and flow matches → return the existing session.
//     If the agent process is dead → auto-resume (re-spawn) transparently.
//  3. If sessionID exists but flow does NOT match → return an error.
//
// createPayload is only required for first-time creation (may be nil on
// subsequent requests — the stored startOpts will be used for auto-resume).
func (m *Manager) Resolve(
	ctx context.Context,
	sessionID, flow string,
	createPayload *protocol.SessionCreatePayload,
) (*Session, string, error) {

	m.mu.Lock()
	sess, exists := m.sessions[sessionID]

	// --- Case 3: flow mismatch -----------------------------------------------
	if exists && sess.Flow != flow {
		m.mu.Unlock()
		return nil, "", fmt.Errorf(
			"FLOW_MISMATCH: session %q is bound to flow %q, cannot use flow %q",
			sessionID, sess.Flow, flow,
		)
	}

	// --- Case 1: new session --------------------------------------------------
	if !exists {
		// Need a createPayload for the initial setup.
		if createPayload == nil {
			m.mu.Unlock()
			return nil, "", fmt.Errorf(
				"SESSION_NOT_FOUND: session %q does not exist; send session.create first",
				sessionID,
			)
		}

		adapter, err := agent.NewAdapter(flow)
		if err != nil {
			m.mu.Unlock()
			return nil, "", err
		}

		sessCtx, cancel := context.WithCancel(ctx)

		startOpts := agent.StartOptions{
			ConnectionMode: createPayload.ConnectionMode,
			WorkingDir:     createPayload.WorkingDir,
			ConnectAddress: createPayload.ConnectAddress,
			Model:          createPayload.Model,
			Config:         createPayload.Config,
			SessionID:      sessionID,
			Flow:           flow,
		}
		if startOpts.ConnectionMode == "" {
			startOpts.ConnectionMode = "spawn"
		}

		sess = &Session{
			ID:         sessionID,
			Flow:       flow,
			Adapter:    adapter,
			Status:     "starting",
			CreatedAt:  time.Now().UTC(),
			WorkingDir: createPayload.WorkingDir,
			startOpts:  startOpts,
			cancel:     cancel,
			ctx:        sessCtx,
		}

		m.sessions[sessionID] = sess
		m.mu.Unlock()

		if err := adapter.Start(sessCtx, startOpts); err != nil {
			sess.mu.Lock()
			sess.Status = "error"
			sess.mu.Unlock()
			cancel()
			return nil, "", fmt.Errorf("start agent %q: %w", flow, err)
		}

		sess.mu.Lock()
		sess.Status = "running"
		sess.mu.Unlock()

		m.logger.Info("session created",
			"sessionId", sessionID,
			"flow", flow,
			"mode", startOpts.ConnectionMode,
		)

		return sess, "created", nil
	}

	m.mu.Unlock()

	// --- Case 2: existing session, flow matches ------------------------------
	sess.mu.Lock()
	defer sess.mu.Unlock()

	// If the adapter is still alive, just return it.
	if sess.Adapter.IsRunning() {
		return sess, "existing", nil
	}

	// Agent process died — auto-resume.
	m.logger.Info("auto-resuming dead process",
		"sessionId", sessionID,
		"flow", flow,
	)

	// Cancel the old context and create a fresh one.
	if sess.cancel != nil {
		sess.cancel()
	}
	sessCtx, cancel := context.WithCancel(ctx)
	sess.ctx = sessCtx
	sess.cancel = cancel

	// Create a fresh adapter instance (processes are not reusable after death).
	adapter, err := agent.NewAdapter(flow)
	if err != nil {
		sess.Status = "error"
		return nil, "", fmt.Errorf("recreate adapter %q: %w", flow, err)
	}

	if err := adapter.Start(sessCtx, sess.startOpts); err != nil {
		sess.Status = "error"
		cancel()
		return nil, "", fmt.Errorf("resume agent %q: %w", flow, err)
	}

	// Transfer attached skills and MCPs from the dead adapter to the new one
	// so session-level attachments survive process restarts.
	for _, s := range sess.Adapter.AttachedSkills() {
		adapter.AttachSkill(s)
	}
	for _, m := range sess.Adapter.AttachedMCPs() {
		adapter.AttachMCP(m)
	}

	sess.Adapter = adapter
	sess.Status = "running"

	m.logger.Info("session resumed",
		"sessionId", sessionID,
		"flow", flow,
	)

	return sess, "resumed", nil
}

// Get returns a session by ID (no routing logic, just lookup).
func (m *Manager) Get(id string) (*Session, bool) {
	m.mu.RLock()
	defer m.mu.RUnlock()
	sess, ok := m.sessions[id]
	return sess, ok
}

// ValidateFlow checks if a session exists and the flow matches.
// Returns the session, or an error with a specific code.
func (m *Manager) ValidateFlow(sessionID, flow string) (*Session, error) {
	m.mu.RLock()
	sess, exists := m.sessions[sessionID]
	m.mu.RUnlock()

	if !exists {
		return nil, fmt.Errorf("SESSION_NOT_FOUND: session %q does not exist", sessionID)
	}
	if sess.Flow != flow {
		return nil, fmt.Errorf(
			"FLOW_MISMATCH: session %q is bound to flow %q, cannot use flow %q",
			sessionID, sess.Flow, flow,
		)
	}
	return sess, nil
}

// List returns all sessions.
func (m *Manager) List() []protocol.SessionInfo {
	m.mu.RLock()
	defer m.mu.RUnlock()
	result := make([]protocol.SessionInfo, 0, len(m.sessions))
	for _, s := range m.sessions {
		result = append(result, protocol.SessionInfo{
			SessionID:  s.ID,
			Flow:       s.Flow,
			Status:     s.Status,
			CreatedAt:  s.CreatedAt,
			WorkingDir: s.WorkingDir,
		})
	}
	return result
}

// End stops a session and removes it from the map permanently.
func (m *Manager) End(id string) error {
	m.mu.Lock()
	sess, ok := m.sessions[id]
	if !ok {
		m.mu.Unlock()
		return fmt.Errorf("session %q not found", id)
	}
	delete(m.sessions, id)
	m.mu.Unlock()

	sess.mu.Lock()
	defer sess.mu.Unlock()

	sess.Status = "stopped"
	if sess.cancel != nil {
		sess.cancel()
	}
	if err := sess.Adapter.Stop(context.Background()); err != nil {
		m.logger.Warn("error stopping adapter", "sessionId", id, "error", err)
		return err
	}

	m.logger.Info("session ended", "sessionId", id, "flow", sess.Flow)
	return nil
}

// StopAll gracefully shuts down every session.
func (m *Manager) StopAll() {
	m.mu.Lock()
	ids := make([]string, 0, len(m.sessions))
	for id := range m.sessions {
		ids = append(ids, id)
	}
	m.mu.Unlock()

	for _, id := range ids {
		_ = m.End(id)
	}
}

// Context returns the session's context.
func (s *Session) Context() context.Context {
	return s.ctx
}

// SetActivePromptCancel registers the cancel function for the current in-flight prompt.
// The hub calls ClearActivePromptCancel with the same function when the prompt finishes.
func (s *Session) SetActivePromptCancel(cancel context.CancelFunc) {
	s.muPrompt.Lock()
	defer s.muPrompt.Unlock()
	s.activePromptCancel = cancel
}

// ClearActivePromptCancel clears the active prompt cancel (call when the prompt goroutine exits).
func (s *Session) ClearActivePromptCancel() {
	s.muPrompt.Lock()
	defer s.muPrompt.Unlock()
	s.activePromptCancel = nil
}

// CancelActivePrompt cancels the in-flight prompt (prompt.cancel).
func (s *Session) CancelActivePrompt() {
	s.muPrompt.Lock()
	defer s.muPrompt.Unlock()
	if s.activePromptCancel != nil {
		s.activePromptCancel()
	}
}

// PromptLock serializes prompt handling for this session (one in-flight prompt).
func (s *Session) PromptLock() {
	s.promptMu.Lock()
}

// PromptUnlock pairs with PromptLock.
func (s *Session) PromptUnlock() {
	s.promptMu.Unlock()
}
