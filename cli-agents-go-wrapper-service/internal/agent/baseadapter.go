package agent

import (
	"context"
	"fmt"
	"sync"

	"github.com/cli-agents-go-wrapper-service/internal/protocol"
)

// BaseAdapter provides common plumbing that most adapters need.
// Embed this in your concrete adapter to get default implementations
// for Modes, skill/MCP attachment, and context cancellation.
type BaseAdapter struct {
	mu             sync.Mutex
	running        bool
	cancelFn       context.CancelFunc
	attachedSkills []Skill     // per-session attached skills
	attachedMCPs   []MCPServer // per-session attached MCP server configs
}

// SetRunning sets the running state thread-safely.
func (b *BaseAdapter) SetRunning(v bool) {
	b.mu.Lock()
	b.running = v
	b.mu.Unlock()
}

// IsRunning reports the running state.
func (b *BaseAdapter) IsRunning() bool {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.running
}

// SetCancel stores a cancel function for stopping.
func (b *BaseAdapter) SetCancel(fn context.CancelFunc) {
	b.mu.Lock()
	b.cancelFn = fn
	b.mu.Unlock()
}

// Cancel calls the stored cancel function if set.
func (b *BaseAdapter) Cancel() {
	b.mu.Lock()
	fn := b.cancelFn
	b.mu.Unlock()
	if fn != nil {
		fn()
	}
}

// Modes default: no configurable modes.
func (b *BaseAdapter) Modes() []AgentMode {
	return nil
}

// CancelPrompt default implementation cancels via context.
func (b *BaseAdapter) CancelPrompt(_ context.Context) error {
	b.Cancel()
	return nil
}

// ApproveToolUse default: not supported.
func (b *BaseAdapter) ApproveToolUse(_ context.Context, _ string) error {
	return fmt.Errorf("tool approval not supported by this adapter")
}

// RejectToolUse default: not supported.
func (b *BaseAdapter) RejectToolUse(_ context.Context, _ string, _ string) error {
	return fmt.Errorf("tool rejection not supported by this adapter")
}

// GetHistory default: not supported.
func (b *BaseAdapter) GetHistory(_ context.Context, _ *protocol.HistoryRequestPayload) (*protocol.HistoryResultPayload, error) {
	return nil, fmt.Errorf("history not supported by this adapter")
}

// -----------------------------------------------------------------------
// Skill attachment
// -----------------------------------------------------------------------

// AttachSkill adds a skill to this adapter's session-local list.
// Idempotent: attaching the same name again replaces the existing entry.
func (b *BaseAdapter) AttachSkill(s Skill) {
	b.mu.Lock()
	defer b.mu.Unlock()
	for i, existing := range b.attachedSkills {
		if existing.Name == s.Name {
			b.attachedSkills[i] = s
			return
		}
	}
	b.attachedSkills = append(b.attachedSkills, s)
}

// DetachSkill removes a skill by name. Returns false if not found.
func (b *BaseAdapter) DetachSkill(name string) bool {
	b.mu.Lock()
	defer b.mu.Unlock()
	for i, s := range b.attachedSkills {
		if s.Name == name {
			b.attachedSkills = append(b.attachedSkills[:i], b.attachedSkills[i+1:]...)
			return true
		}
	}
	return false
}

// AttachedSkills returns a snapshot of the currently attached skills.
func (b *BaseAdapter) AttachedSkills() []Skill {
	b.mu.Lock()
	defer b.mu.Unlock()
	out := make([]Skill, len(b.attachedSkills))
	copy(out, b.attachedSkills)
	return out
}

// -----------------------------------------------------------------------
// MCP attachment
// -----------------------------------------------------------------------

// AttachMCP adds an MCP server config. Idempotent by name.
func (b *BaseAdapter) AttachMCP(m MCPServer) {
	b.mu.Lock()
	defer b.mu.Unlock()
	for i, existing := range b.attachedMCPs {
		if existing.Name == m.Name {
			b.attachedMCPs[i] = m
			return
		}
	}
	b.attachedMCPs = append(b.attachedMCPs, m)
}

// DetachMCP removes an MCP server config by name. Returns false if not found.
func (b *BaseAdapter) DetachMCP(name string) bool {
	b.mu.Lock()
	defer b.mu.Unlock()
	for i, m := range b.attachedMCPs {
		if m.Name == name {
			b.attachedMCPs = append(b.attachedMCPs[:i], b.attachedMCPs[i+1:]...)
			return true
		}
	}
	return false
}

// AttachedMCPs returns a snapshot of the currently attached MCP server configs.
func (b *BaseAdapter) AttachedMCPs() []MCPServer {
	b.mu.Lock()
	defer b.mu.Unlock()
	out := make([]MCPServer, len(b.attachedMCPs))
	copy(out, b.attachedMCPs)
	return out
}
