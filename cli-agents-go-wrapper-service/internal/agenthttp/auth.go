package agenthttp

// Auth HTTP handlers — HTTP-only, not exposed over WebSocket.
//
// Routes (registered in cmd/server/main.go):
//
//	GET    /agents/{agent}/auth          — check login status (uses cache)
//	POST   /agents/{agent}/auth/login    — trigger login flow, returns browser URL
//	DELETE /agents/{agent}/auth          — invalidate cached state, force re-check

import (
	"context"
	"net/http"
	"time"

	"github.com/cli-agents-go-wrapper-service/internal/agent"
	"github.com/cli-agents-go-wrapper-service/internal/auth"
)

// authStatusResponse is the JSON shape returned by GET /agents/{agent}/auth.
type authStatusResponse struct {
	AgentName     string    `json:"agentName"`
	LoggedIn      bool      `json:"loggedIn"`
	Detail        string    `json:"detail,omitempty"`
	CheckedAt     time.Time `json:"checkedAt,omitempty"`
	CacheHit      bool      `json:"cacheHit"`
	AuthSupported bool      `json:"authSupported"`
}

// HandleAgentAuth serves:
//
//	GET    /agents/{agent}/auth    — return cached (or freshly checked) auth status
//	DELETE /agents/{agent}/auth    — invalidate the cache for this agent
func HandleAgentAuth(authMgr *auth.Manager) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		agentName := r.PathValue("agent")
		if agentName == "" {
			respondError(w, http.StatusBadRequest, "missing agent name in path")
			return
		}

		switch r.Method {
		case http.MethodGet:
			handleGetAgentAuth(w, r, agentName, authMgr)
		case http.MethodDelete:
			handleDeleteAgentAuth(w, agentName, authMgr)
		default:
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		}
	}
}

func handleGetAgentAuth(w http.ResponseWriter, r *http.Request, agentName string, authMgr *auth.Manager) {
	// Check whether this agent type even supports auth.
	a, err := agent.NewAdapter(agentName)
	if err != nil {
		respondError(w, http.StatusNotFound, "unknown agent: "+agentName)
		return
	}
	_, supportsAuth := agent.AsAuthenticator(a)

	if !supportsAuth {
		respondJSON(w, authStatusResponse{
			AgentName:     agentName,
			LoggedIn:      true, // auth not required — always OK
			AuthSupported: false,
			CacheHit:      false,
		})
		return
	}

	// Check cache.
	loggedIn, detail, checkedAt, cacheHit := authMgr.Status(agentName)
	if cacheHit {
		respondJSON(w, authStatusResponse{
			AgentName:     agentName,
			LoggedIn:      loggedIn,
			Detail:        detail,
			CheckedAt:     checkedAt,
			CacheHit:      true,
			AuthSupported: true,
		})
		return
	}

	// No cache — run live check.
	auth, _ := agent.AsAuthenticator(a)
	ctx, cancel := context.WithTimeout(r.Context(), 10*time.Second)
	defer cancel()

	status, err := auth.CheckAuth(ctx)
	if err != nil {
		respondError(w, http.StatusInternalServerError, "auth check failed: "+err.Error())
		return
	}
	authMgr.SetStatus(agentName, status.LoggedIn, status.Detail)

	respondJSON(w, authStatusResponse{
		AgentName:     agentName,
		LoggedIn:      status.LoggedIn,
		Detail:        status.Detail,
		CheckedAt:     checkedAt,
		CacheHit:      false,
		AuthSupported: true,
	})
}

func handleDeleteAgentAuth(w http.ResponseWriter, agentName string, authMgr *auth.Manager) {
	authMgr.Invalidate(agentName)
	respondJSON(w, map[string]string{"invalidated": agentName})
}

// HandleAgentAuthLogin serves POST /agents/{agent}/auth/login.
//
// It starts the agent's login flow and immediately returns the browser URL.
// The login process runs in the background — the agent CLI will wait for the
// user to complete the OAuth flow in their browser.
func HandleAgentAuthLogin(authMgr *auth.Manager) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}

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

		authenticator, ok := agent.AsAuthenticator(a)
		if !ok {
			respondJSON(w, map[string]any{
				"agentName":     agentName,
				"authSupported": false,
				"message":       "this agent does not require login",
			})
			return
		}

		// Invalidate any stale cache entry before re-logging in.
		authMgr.Invalidate(agentName)

		ctx, cancel := context.WithTimeout(r.Context(), 15*time.Second)
		defer cancel()

		flow, err := authenticator.Login(ctx)
		if err != nil {
			respondError(w, http.StatusInternalServerError, "login failed: "+err.Error())
			return
		}

		// Monitor login completion in the background and update the cache.
		if flow.Done != nil {
			go func() {
				bgCtx, bgCancel := context.WithTimeout(context.Background(), 5*time.Minute)
				defer bgCancel()
				select {
				case err := <-flow.Done:
					if err == nil {
						authMgr.SetStatus(agentName, true, "logged in via browser")
					}
				case <-bgCtx.Done():
				}
			}()
		}

		resp := map[string]any{
			"agentName":     agentName,
			"authSupported": true,
		}
		if flow.URL != "" {
			resp["url"] = flow.URL
			resp["message"] = "visit the URL in your browser to complete login"
		} else {
			// Login completed synchronously (e.g. already logged in).
			authMgr.SetStatus(agentName, true, "logged in")
			resp["message"] = "already logged in"
			resp["loggedIn"] = true
		}
		respondJSON(w, resp)
	}
}
