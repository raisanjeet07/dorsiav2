package agent

import "testing"

func TestAdapterSessionUUIDStable(t *testing.T) {
	t.Parallel()
	a := AdapterSessionUUID("wf-1-reviewer", "claude-code")
	b := AdapterSessionUUID("wf-1-reviewer", "claude-code")
	if a == "" || a != b {
		t.Fatalf("expected stable non-empty UUID, got %q vs %q", a, b)
	}
	if got := AdapterSessionUUID("wf-1-reviewer", "gemini"); got == a {
		t.Fatal("different flow must produce different UUID")
	}
	if got := AdapterSessionUUID("", "claude-code"); got != "" {
		t.Fatalf("empty session id: %q", got)
	}
}

func TestSessionRoutingKeyTrim(t *testing.T) {
	t.Parallel()
	a := AdapterSessionUUID("  wf-1  ", "claude-code")
	b := AdapterSessionUUID("wf-1", "claude-code")
	if a != b {
		t.Fatalf("trim should match: %q vs %q", a, b)
	}
	if got := SessionRoutingKey("a", "b"); got != "a\x1eb" {
		t.Fatalf("routing key: %q", got)
	}
}

func TestAdapterSessionUUID_SHA256Env(t *testing.T) {
	base := AdapterSessionUUID("x", "claude-code")
	t.Setenv("GATEWAY_ADAPTER_SESSION_SHA256", "1")
	sha := AdapterSessionUUID("x", "claude-code")
	if sha == base {
		t.Fatal("SHA256 mode should differ from SHA1 default")
	}
}
