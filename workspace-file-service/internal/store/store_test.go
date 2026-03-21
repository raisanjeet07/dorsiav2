package store

import (
	"os"
	"path/filepath"
	"testing"
)

func TestStoreEnsureAndResolve(t *testing.T) {
	root := t.TempDir()
	s, err := New(root)
	if err != nil {
		t.Fatal(err)
	}
	path, created, err := s.Ensure("sess-a")
	if err != nil {
		t.Fatal(err)
	}
	if !created {
		t.Fatal("expected created")
	}
	if _, err := os.Stat(path); err != nil {
		t.Fatal(err)
	}
	_, created2, err := s.Ensure("sess-a")
	if err != nil || created2 {
		t.Fatalf("second ensure: created=%v err=%v", created2, err)
	}
	full, err := s.ResolvePath("sess-a", "docs/readme.md")
	if err != nil {
		t.Fatal(err)
	}
	want := filepath.Join(s.Root, "sess-a", "docs", "readme.md")
	if filepath.Clean(full) != filepath.Clean(want) {
		t.Fatalf("resolve: got %s want %s", full, want)
	}
	_, err = s.ResolvePath("sess-a", "../other")
	if err == nil {
		t.Fatal("expected traversal error")
	}
}
