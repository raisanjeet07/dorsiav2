package api

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/dorsiav2/workspace-file-service/internal/store"
)

func TestCreateAndGetSession(t *testing.T) {
	st, err := store.New(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	s := NewServer(st)

	t.Run("create", func(t *testing.T) {
		body := bytes.NewBufferString(`{"session_id":"api-test-1"}`)
		req := httptest.NewRequest(http.MethodPost, "/api/v1/sessions", body)
		rec := httptest.NewRecorder()
		s.CreateSession(rec, req)
		if rec.Code != http.StatusCreated {
			t.Fatalf("status %d body %s", rec.Code, rec.Body.String())
		}
	})

	t.Run("get location", func(t *testing.T) {
		req := httptest.NewRequest(http.MethodGet, "/api/v1/sessions/api-test-1/location", nil)
		req.SetPathValue("sessionId", "api-test-1")
		rec := httptest.NewRecorder()
		s.GetSessionLocation(rec, req)
		if rec.Code != http.StatusOK {
			t.Fatalf("status %d", rec.Code)
		}
		var out SessionResponse
		if err := json.NewDecoder(rec.Body).Decode(&out); err != nil {
			t.Fatal(err)
		}
		if out.SessionID != "api-test-1" || out.WorkspacePath == "" {
			t.Fatalf("bad response %+v", out)
		}
	})

	t.Run("get ensures without prior post", func(t *testing.T) {
		req := httptest.NewRequest(http.MethodGet, "/api/v1/sessions/brand-new-id", nil)
		req.SetPathValue("sessionId", "brand-new-id")
		rec := httptest.NewRecorder()
		s.GetSession(rec, req)
		if rec.Code != http.StatusOK {
			t.Fatalf("status %d", rec.Code)
		}
		var out SessionResponse
		if err := json.NewDecoder(rec.Body).Decode(&out); err != nil {
			t.Fatal(err)
		}
		if !out.Created || out.WorkspacePath == "" {
			t.Fatalf("expected created dir and path, got %+v", out)
		}
	})
}
