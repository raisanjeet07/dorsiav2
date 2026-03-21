// Package mcp manages the global registry of MCP (Model Context Protocol)
// server configurations that can be attached to agent sessions.
//
// MCP servers are scoped either "global" (available to any agent) or to a
// specific agent name. The registry is safe for concurrent use.
package mcp

import (
	"fmt"
	"sync"

	"github.com/cli-agents-go-wrapper-service/internal/agent"
)

// Registry is an in-memory, thread-safe store of MCPServer configs keyed by name.
type Registry struct {
	mu   sync.RWMutex
	mcps map[string]agent.MCPServer
}

// NewRegistry creates an empty MCP registry.
func NewRegistry() *Registry {
	return &Registry{
		mcps: make(map[string]agent.MCPServer),
	}
}

// Register adds or replaces an MCP server config. Returns an error if Name is empty.
func (r *Registry) Register(m agent.MCPServer) error {
	if m.Name == "" {
		return fmt.Errorf("mcp server name must not be empty")
	}
	if m.Scope == "" {
		m.Scope = "global"
	}
	if m.Type == "" {
		m.Type = agent.MCPServerTypeStdio
	}
	r.mu.Lock()
	r.mcps[m.Name] = m
	r.mu.Unlock()
	return nil
}

// Remove deletes an MCP server config by name. Returns false if not registered.
func (r *Registry) Remove(name string) bool {
	r.mu.Lock()
	defer r.mu.Unlock()
	if _, ok := r.mcps[name]; !ok {
		return false
	}
	delete(r.mcps, name)
	return true
}

// Get returns a single MCP server config by name.
func (r *Registry) Get(name string) (agent.MCPServer, bool) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	m, ok := r.mcps[name]
	return m, ok
}

// List returns all MCP server configs visible to the given agentName.
//   - agentName == "" → return every registered MCP
//   - agentName != "" → return MCPs where Scope == "global" OR Scope == agentName
func (r *Registry) List(agentName string) []agent.MCPServer {
	r.mu.RLock()
	defer r.mu.RUnlock()
	out := make([]agent.MCPServer, 0, len(r.mcps))
	for _, m := range r.mcps {
		if agentName == "" || m.Scope == "global" || m.Scope == agentName {
			out = append(out, m)
		}
	}
	return out
}

// All returns every registered MCP regardless of scope (for admin use).
func (r *Registry) All() []agent.MCPServer {
	return r.List("")
}
