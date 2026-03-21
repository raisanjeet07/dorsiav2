// Package skill manages the global registry of Skills that can be attached
// to agent sessions as system prompt injections.
//
// Skills are scoped either "global" (available to any agent) or to a specific
// agent name (e.g. "claude-code"). The registry is safe for concurrent use.
package skill

import (
	"fmt"
	"sync"

	"github.com/cli-agents-go-wrapper-service/internal/agent"
)

// Registry is an in-memory, thread-safe store of Skills keyed by name.
type Registry struct {
	mu     sync.RWMutex
	skills map[string]agent.Skill
}

// NewRegistry creates an empty skill registry.
func NewRegistry() *Registry {
	return &Registry{
		skills: make(map[string]agent.Skill),
	}
}

// Register adds or replaces a skill. Returns an error if the skill Name is empty.
func (r *Registry) Register(s agent.Skill) error {
	if s.Name == "" {
		return fmt.Errorf("skill name must not be empty")
	}
	if s.Scope == "" {
		s.Scope = "global"
	}
	r.mu.Lock()
	r.skills[s.Name] = s
	r.mu.Unlock()
	return nil
}

// Remove deletes a skill by name. Returns false if it was not registered.
func (r *Registry) Remove(name string) bool {
	r.mu.Lock()
	defer r.mu.Unlock()
	if _, ok := r.skills[name]; !ok {
		return false
	}
	delete(r.skills, name)
	return true
}

// Get returns a single skill by name.
func (r *Registry) Get(name string) (agent.Skill, bool) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	s, ok := r.skills[name]
	return s, ok
}

// List returns all skills visible to the given agentName.
//   - agentName == "" → return every registered skill
//   - agentName != "" → return skills where Scope == "global" OR Scope == agentName
func (r *Registry) List(agentName string) []agent.Skill {
	r.mu.RLock()
	defer r.mu.RUnlock()
	out := make([]agent.Skill, 0, len(r.skills))
	for _, s := range r.skills {
		if agentName == "" || s.Scope == "global" || s.Scope == agentName {
			out = append(out, s)
		}
	}
	return out
}

// All returns every registered skill regardless of scope (for admin use).
func (r *Registry) All() []agent.Skill {
	return r.List("")
}
