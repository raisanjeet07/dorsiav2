// Package agenthttp provides HTTP handlers for the agent management endpoints:
// modes, skills, MCP server configurations, and session-level attachment APIs.
//
// All new APIs (modes, skills, MCPs) are HTTP-only. WebSocket messages are
// reserved for the prompt/streaming lifecycle.
package agenthttp

import (
	"context"
	"encoding/json"
	"net/http"
	"time"

	"github.com/cli-agents-go-wrapper-service/internal/agent"
	"github.com/cli-agents-go-wrapper-service/internal/config"
	"github.com/cli-agents-go-wrapper-service/internal/mcp"
	"github.com/cli-agents-go-wrapper-service/internal/session"
	"github.com/cli-agents-go-wrapper-service/internal/skill"
)

// -----------------------------------------------------------------------
// Modes — GET /agents/{agent}/modes
// -----------------------------------------------------------------------

// HandleAgentModels returns the list of models for the named agent.
//
// Resolution order (first non-empty wins):
//  1. Config-provided override (agents.<name>.models in config JSON)
//  2. Dynamic fetch via the agent's API (adapter implements ModelLister)
//  3. Empty list — the agent selects its own default
func HandleAgentModels(cfg *config.Config) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		agentName := r.PathValue("agent")
		if agentName == "" {
			respondError(w, http.StatusBadRequest, "missing agent name in path")
			return
		}

		a, err := agent.NewAdapter(agentName)
		if err != nil {
			respondError(w, http.StatusNotFound, "unknown agent: "+agentName)
			return
		}

		// 1. Config override wins.
		if cfg != nil {
			if agentCfg, ok := cfg.Agents[agentName]; ok && len(agentCfg.Models) > 0 {
				respondJSON(w, map[string]any{"agentName": agentName, "models": agentCfg.Models, "source": "config"})
				return
			}
		}

		// 2. Dynamic fetch from the agent's API.
		if lister, ok := agent.AsModelLister(a); ok {
			ctx, cancel := context.WithTimeout(r.Context(), 10*time.Second)
			defer cancel()
			models, err := lister.ListModels(ctx)
			if err == nil && len(models) > 0 {
				respondJSON(w, map[string]any{"agentName": agentName, "models": models, "source": "api"})
				return
			}
			// Log but don't fail — fall through to empty list.
			_ = err
		}

		// 3. No models available — agent will use its own default.
		respondJSON(w, map[string]any{"agentName": agentName, "models": []string{}, "source": "none"})
	}
}

// HandleAgentModes returns the operating modes supported by the named agent.
// Uses Go 1.22 net/http path value: the route must be registered as
// "GET /agents/{agent}/modes".
func HandleAgentModes(w http.ResponseWriter, r *http.Request) {
	agentName := r.PathValue("agent")
	if agentName == "" {
		respondError(w, http.StatusBadRequest, "missing agent name in path")
		return
	}

	a, err := agent.NewAdapter(agentName)
	if err != nil {
		respondError(w, http.StatusNotFound, "unknown agent: "+agentName)
		return
	}

	modes := a.Modes()
	if modes == nil {
		modes = []agent.AgentMode{}
	}
	respondJSON(w, map[string]any{
		"agentName": agentName,
		"modes":     modes,
	})
}

// -----------------------------------------------------------------------
// Skills — /skills and /agents/{agent}/skills
// -----------------------------------------------------------------------

// HandleSkills serves GET /skills (list all) and POST /skills (register new).
func HandleSkills(reg *skill.Registry) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		switch r.Method {
		case http.MethodGet:
			skills := reg.All()
			if skills == nil {
				skills = []agent.Skill{}
			}
			respondJSON(w, map[string]any{"skills": skills})

		case http.MethodPost:
			var s agent.Skill
			if err := json.NewDecoder(r.Body).Decode(&s); err != nil {
				respondError(w, http.StatusBadRequest, "invalid JSON: "+err.Error())
				return
			}
			if err := reg.Register(s); err != nil {
				respondError(w, http.StatusBadRequest, err.Error())
				return
			}
			w.WriteHeader(http.StatusCreated)
			respondJSON(w, s)

		default:
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		}
	}
}

// HandleSkillByName serves DELETE /skills/{name}.
func HandleSkillByName(reg *skill.Registry) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		name := r.PathValue("name")
		if r.Method != http.MethodDelete {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		if !reg.Remove(name) {
			respondError(w, http.StatusNotFound, "skill not found: "+name)
			return
		}
		respondJSON(w, map[string]any{"deleted": name})
	}
}

// HandleAgentSkills serves GET /agents/{agent}/skills — lists skills
// scoped to the specified agent (global + agent-specific).
func HandleAgentSkills(reg *skill.Registry) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		agentName := r.PathValue("agent")
		skills := reg.List(agentName)
		if skills == nil {
			skills = []agent.Skill{}
		}
		respondJSON(w, map[string]any{
			"agentName": agentName,
			"skills":    skills,
		})
	}
}

// -----------------------------------------------------------------------
// MCPs — /mcps and /agents/{agent}/mcps
// -----------------------------------------------------------------------

// HandleMCPs serves GET /mcps (list all) and POST /mcps (register new).
func HandleMCPs(reg *mcp.Registry) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		switch r.Method {
		case http.MethodGet:
			mcps := reg.All()
			if mcps == nil {
				mcps = []agent.MCPServer{}
			}
			respondJSON(w, map[string]any{"mcps": mcps})

		case http.MethodPost:
			var m agent.MCPServer
			if err := json.NewDecoder(r.Body).Decode(&m); err != nil {
				respondError(w, http.StatusBadRequest, "invalid JSON: "+err.Error())
				return
			}
			if err := reg.Register(m); err != nil {
				respondError(w, http.StatusBadRequest, err.Error())
				return
			}
			w.WriteHeader(http.StatusCreated)
			respondJSON(w, m)

		default:
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		}
	}
}

// HandleMCPByName serves DELETE /mcps/{name}.
func HandleMCPByName(reg *mcp.Registry) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		name := r.PathValue("name")
		if r.Method != http.MethodDelete {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		if !reg.Remove(name) {
			respondError(w, http.StatusNotFound, "mcp not found: "+name)
			return
		}
		respondJSON(w, map[string]any{"deleted": name})
	}
}

// HandleAgentMCPs serves GET /agents/{agent}/mcps — lists MCPs visible to
// the specified agent (global + agent-specific).
func HandleAgentMCPs(reg *mcp.Registry) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		agentName := r.PathValue("agent")
		mcps := reg.List(agentName)
		if mcps == nil {
			mcps = []agent.MCPServer{}
		}
		respondJSON(w, map[string]any{
			"agentName": agentName,
			"mcps":      mcps,
		})
	}
}

// -----------------------------------------------------------------------
// Session-level skill attachment — /sessions/{sessionId}/skills
// -----------------------------------------------------------------------

// HandleSessionSkills serves:
//
//	GET    /sessions/{sessionId}/skills           — list skills with attachment status
//	POST   /sessions/{sessionId}/skills/{name}    — attach a skill to the session
//	DELETE /sessions/{sessionId}/skills/{name}    — detach a skill from the session
func HandleSessionSkills(sessMgr *session.Manager, skillReg *skill.Registry) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		sessionID := r.PathValue("sessionId")
		sess, ok := sessMgr.Get(sessionID)
		if !ok {
			respondError(w, http.StatusNotFound, "session not found: "+sessionID)
			return
		}

		skillName := r.PathValue("skillName") // empty on GET /sessions/{id}/skills

		switch r.Method {
		case http.MethodGet:
			available := skillReg.List(sess.Flow)
			attached := sess.Adapter.AttachedSkills()
			attachedSet := make(map[string]struct{}, len(attached))
			for _, s := range attached {
				attachedSet[s.Name] = struct{}{}
			}
			type skillStatus struct {
				agent.Skill
				Attached bool `json:"attached"`
			}
			result := make([]skillStatus, len(available))
			for i, s := range available {
				_, isAttached := attachedSet[s.Name]
				result[i] = skillStatus{Skill: s, Attached: isAttached}
			}
			respondJSON(w, map[string]any{"sessionId": sessionID, "skills": result})

		case http.MethodPost:
			s, found := skillReg.Get(skillName)
			if !found {
				respondError(w, http.StatusNotFound, "skill not registered: "+skillName)
				return
			}
			sess.Adapter.AttachSkill(s)
			respondJSON(w, map[string]any{"attached": skillName, "sessionId": sessionID})

		case http.MethodDelete:
			if !sess.Adapter.DetachSkill(skillName) {
				respondError(w, http.StatusNotFound, "skill not attached: "+skillName)
				return
			}
			respondJSON(w, map[string]any{"detached": skillName, "sessionId": sessionID})

		default:
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		}
	}
}

// -----------------------------------------------------------------------
// Session-level MCP attachment — /sessions/{sessionId}/mcps
// -----------------------------------------------------------------------

// HandleSessionMCPs serves:
//
//	GET    /sessions/{sessionId}/mcps             — list MCPs with attachment status
//	POST   /sessions/{sessionId}/mcps/{name}      — attach an MCP to the session
//	DELETE /sessions/{sessionId}/mcps/{name}      — detach an MCP from the session
func HandleSessionMCPs(sessMgr *session.Manager, mcpReg *mcp.Registry) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		sessionID := r.PathValue("sessionId")
		sess, ok := sessMgr.Get(sessionID)
		if !ok {
			respondError(w, http.StatusNotFound, "session not found: "+sessionID)
			return
		}

		mcpName := r.PathValue("mcpName") // empty on GET /sessions/{id}/mcps

		switch r.Method {
		case http.MethodGet:
			available := mcpReg.List(sess.Flow)
			attached := sess.Adapter.AttachedMCPs()
			attachedSet := make(map[string]struct{}, len(attached))
			for _, m := range attached {
				attachedSet[m.Name] = struct{}{}
			}
			type mcpStatus struct {
				agent.MCPServer
				Attached bool `json:"attached"`
			}
			result := make([]mcpStatus, len(available))
			for i, m := range available {
				_, isAttached := attachedSet[m.Name]
				result[i] = mcpStatus{MCPServer: m, Attached: isAttached}
			}
			respondJSON(w, map[string]any{"sessionId": sessionID, "mcps": result})

		case http.MethodPost:
			m, found := mcpReg.Get(mcpName)
			if !found {
				respondError(w, http.StatusNotFound, "mcp not registered: "+mcpName)
				return
			}
			sess.Adapter.AttachMCP(m)
			respondJSON(w, map[string]any{"attached": mcpName, "sessionId": sessionID})

		case http.MethodDelete:
			if !sess.Adapter.DetachMCP(mcpName) {
				respondError(w, http.StatusNotFound, "mcp not attached: "+mcpName)
				return
			}
			respondJSON(w, map[string]any{"detached": mcpName, "sessionId": sessionID})

		default:
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		}
	}
}

// -----------------------------------------------------------------------
// Helpers
// -----------------------------------------------------------------------

func respondJSON(w http.ResponseWriter, v any) {
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(v)
}

func respondError(w http.ResponseWriter, code int, msg string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(map[string]string{"error": msg})
}
