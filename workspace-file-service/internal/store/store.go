// Package store manages on-disk workspace directories per session id.
package store

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/dorsiav2/workspace-file-service/internal/sessionid"
)

// Store maps session IDs to directories under Root.
type Store struct {
	Root string // absolute path
}

// New creates a Store with an absolute, cleaned root path.
func New(root string) (*Store, error) {
	abs, err := filepath.Abs(root)
	if err != nil {
		return nil, err
	}
	abs = filepath.Clean(abs)
	if err := os.MkdirAll(abs, 0o755); err != nil {
		return nil, fmt.Errorf("create workspace root: %w", err)
	}
	return &Store{Root: abs}, nil
}

// SessionDir returns the absolute directory for a session (may not exist yet).
func (s *Store) SessionDir(sessionID string) (string, error) {
	if err := sessionid.Validate(sessionID); err != nil {
		return "", err
	}
	return filepath.Join(s.Root, sessionID), nil
}

// Ensure creates the session directory if missing.
func (s *Store) Ensure(sessionID string) (path string, created bool, err error) {
	dir, err := s.SessionDir(sessionID)
	if err != nil {
		return "", false, err
	}
	fi, statErr := os.Stat(dir)
	if statErr == nil {
		if !fi.IsDir() {
			return "", false, fmt.Errorf("session path exists but is not a directory: %s", dir)
		}
		return dir, false, nil
	}
	if !errors.Is(statErr, os.ErrNotExist) {
		return "", false, statErr
	}
	if mkErr := os.MkdirAll(dir, 0o755); mkErr != nil {
		return "", false, mkErr
	}
	return dir, true, nil
}

// Exists reports whether the session directory exists and is a directory.
func (s *Store) Exists(sessionID string) (bool, error) {
	dir, err := s.SessionDir(sessionID)
	if err != nil {
		return false, err
	}
	fi, err := os.Stat(dir)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return false, nil
		}
		return false, err
	}
	return fi.IsDir(), nil
}

// ResolvePath returns an absolute path for a relative path inside the session dir.
// rel may be "" (session root). Path traversal is rejected.
func (s *Store) ResolvePath(sessionID, rel string) (string, error) {
	base, err := s.SessionDir(sessionID)
	if err != nil {
		return "", err
	}
	rel = strings.TrimSpace(rel)
	rel = strings.TrimPrefix(rel, "/")
	if rel == "" || rel == "." {
		return base, nil
	}
	if filepath.IsAbs(rel) {
		return "", fmt.Errorf("absolute path not allowed")
	}
	full := filepath.Join(base, filepath.FromSlash(rel))
	full = filepath.Clean(full)
	r, err := filepath.Rel(base, full)
	if err != nil || r == ".." || strings.HasPrefix(r, ".."+string(os.PathSeparator)) {
		return "", fmt.Errorf("path escapes session directory")
	}
	return full, nil
}
