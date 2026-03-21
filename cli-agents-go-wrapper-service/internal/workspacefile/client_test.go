package workspacefile

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestClientEnsureWorkspace(t *testing.T) {
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet || r.URL.Path != "/api/v1/sessions/sess-1" {
			http.NotFound(w, r)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		_ = json.NewEncoder(w).Encode(ensureResponse{
			SessionID:     "sess-1",
			WorkspacePath: "/tmp/ws/sess-1",
			Created:       true,
		})
	}))
	defer ts.Close()

	c := NewClient(ts.URL)
	path, err := c.EnsureWorkspace(context.Background(), "sess-1")
	if err != nil || path != "/tmp/ws/sess-1" {
		t.Fatalf("got path=%q err=%v", path, err)
	}
}
