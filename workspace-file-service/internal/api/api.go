// Package api implements HTTP handlers for session workspaces and file browsing.
package api

import (
	"encoding/json"
	"errors"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strings"

	"github.com/dorsiav2/workspace-file-service/internal/sessionid"
	"github.com/dorsiav2/workspace-file-service/internal/store"
)

// Server exposes REST + file browsing.
type Server struct {
	Store *store.Store
}

// NewServer creates an API server.
func NewServer(st *store.Store) *Server {
	return &Server{Store: st}
}

// SessionResponse is returned for session location APIs.
type SessionResponse struct {
	SessionID     string `json:"session_id"`
	WorkspacePath string `json:"workspace_path"`
	Created       bool   `json:"created,omitempty"`
}

// ErrorBody is JSON error payload.
type ErrorBody struct {
	Error string `json:"error"`
	Code  string `json:"code,omitempty"`
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

func writeErr(w http.ResponseWriter, status int, code, msg string) {
	writeJSON(w, status, ErrorBody{Error: msg, Code: code})
}

func mapSessionErr(w http.ResponseWriter, err error) {
	switch {
	case errors.Is(err, sessionid.ErrEmpty),
		errors.Is(err, sessionid.ErrInvalid),
		errors.Is(err, sessionid.ErrTooLong):
		writeErr(w, http.StatusBadRequest, "BAD_SESSION_ID", err.Error())
	default:
		writeErr(w, http.StatusBadRequest, "BAD_REQUEST", err.Error())
	}
}

// Health returns 200 JSON for load balancers.
func (s *Server) Health(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
}

// CreateSession POST /api/v1/sessions — body {"session_id":"..."}; ensures directory exists.
func (s *Server) CreateSession(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	var body struct {
		SessionID string `json:"session_id"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeErr(w, http.StatusBadRequest, "BAD_REQUEST", "invalid JSON body")
		return
	}
	path, created, err := s.Store.Ensure(body.SessionID)
	if err != nil {
		if errors.Is(err, sessionid.ErrEmpty) || errors.Is(err, sessionid.ErrInvalid) || errors.Is(err, sessionid.ErrTooLong) {
			mapSessionErr(w, err)
			return
		}
		writeErr(w, http.StatusInternalServerError, "INTERNAL", err.Error())
		return
	}
	writeJSON(w, http.StatusCreated, SessionResponse{
		SessionID:     strings.TrimSpace(body.SessionID),
		WorkspacePath: path,
		Created:       created,
	})
}

// GetSession GET /api/v1/sessions/{sessionId}
// Ensures the session directory exists (creates it if missing) and returns the absolute path.
func (s *Server) GetSession(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	id := strings.TrimSpace(r.PathValue("sessionId"))
	path, created, err := s.Store.Ensure(id)
	if err != nil {
		if errors.Is(err, sessionid.ErrEmpty) || errors.Is(err, sessionid.ErrInvalid) || errors.Is(err, sessionid.ErrTooLong) {
			mapSessionErr(w, err)
			return
		}
		writeErr(w, http.StatusInternalServerError, "INTERNAL", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, SessionResponse{
		SessionID:     id,
		WorkspacePath: path,
		Created:       created,
	})
}

// GetSessionLocation GET /api/v1/sessions/{sessionId}/location
func (s *Server) GetSessionLocation(w http.ResponseWriter, r *http.Request) {
	s.GetSession(w, r)
}

// ServeFiles GET /files/... — path is /files/{sessionId}/optional/relative/path
func (s *Server) ServeFiles(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet && r.Method != http.MethodHead {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	trim := strings.TrimPrefix(r.URL.Path, "/files")
	trim = strings.TrimPrefix(trim, "/")
	parts := strings.SplitN(trim, "/", 2)
	if len(parts) < 1 || parts[0] == "" {
		http.NotFound(w, r)
		return
	}
	id := parts[0]
	rel := ""
	if len(parts) > 1 {
		rel = parts[1]
	}
	decoded, err := url.PathUnescape(rel)
	if err != nil {
		writeErr(w, http.StatusBadRequest, "BAD_PATH", "invalid path encoding")
		return
	}
	rel = decoded

	if err := sessionid.Validate(id); err != nil {
		mapSessionErr(w, err)
		return
	}
	ok, err := s.Store.Exists(id)
	if err != nil {
		writeErr(w, http.StatusInternalServerError, "INTERNAL", err.Error())
		return
	}
	if !ok {
		http.NotFound(w, r)
		return
	}
	sessionDir, err := s.Store.SessionDir(id)
	if err != nil {
		mapSessionErr(w, err)
		return
	}
	full, err := s.Store.ResolvePath(id, rel)
	if err != nil {
		writeErr(w, http.StatusForbidden, "FORBIDDEN", "invalid path")
		return
	}
	fi, err := os.Stat(full)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			http.NotFound(w, r)
			return
		}
		writeErr(w, http.StatusInternalServerError, "INTERNAL", err.Error())
		return
	}
	if fi.IsDir() {
		req := r.Clone(r.Context())
		sub := "/" + filepath.ToSlash(rel)
		if sub == "//" || sub == "/." {
			sub = "/"
		}
		req.URL.Path = sub
		req.URL.RawPath = ""
		http.FileServer(http.Dir(sessionDir)).ServeHTTP(w, req)
		return
	}
	http.ServeFile(w, r, full)
}
